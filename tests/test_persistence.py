"""
Consolidated Persistence, Atomic Publication, Bundles, and Recovery Tests.

Consolidates Checkpoint 11a, 11b, 11c, recovery, and regression tests:
- Handle writer, schema metadata, and exact JSON column units (Section 7.1 & 8.1).
- Atomic no-replace publication, collision safety, and safe staging (Section 8.1 & 8.3).
- Candidate reservations {index:04d}_{schema}.csv, markers, and cleanup (Section 8.1).
- Multi-artifact bundles, rollback, and partial checkpoints (Section 8.2 & 8.3).
- Failure recovery, error precedence, and Unicode metadata preservation.
"""

from __future__ import annotations

import concurrent.futures
import errno
import io
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple
from unittest.mock import MagicMock, Mock, call, patch
import uuid
import warnings

import numpy as np
import pandas as pd
import pytest

from piec.analysis.utilities import metadata_and_data_to_csv, standard_csv_to_metadata_and_data
from piec.measurement import (
    BaseMeasurement,
    RunState,
    SafetyReport,
    SafetyStatus,
    REQUIRED_METADATA_FIELDS,
    STANDARD_COLUMNS,
    STANDARD_SCHEMAS,
    deserialize_column_units,
    read_measurement_csv,
    serialize_column_units,
    validate_column_units,
    validate_metadata,
    write_measurement_csv,
    write_measurement_handle,
)
from piec.measurement.persistence import (
    AtomicPublishError,
    BundlePublishError,
    CandidateReservation,
    UnsupportedFilesystemError,
    _collision_resistant_publish,
    atomic_publish_measurement_csv,
    atomic_publish_no_replace,
    cleanup_stale_partials,
    cleanup_stale_reservations,
    create_staging_file,
    is_completed_measurement_file,
    publish_artifact_bundle,
    reserve_candidate_filename,
    write_partial_csv,
)
import piec.measurement.persistence as p


# ============================================================================
# Part 1: Handle Writer & Schema Metadata (Checkpoint 11a)
# ============================================================================

class TestColumnUnitsSerialization:
    """Verifies column units serialization, compaction, sorting, and round trips."""

    def test_compact_sorted_json_serialization(self):
        """serialize_column_units produces compact, sorted JSON without extraneous whitespace."""
        units = {
            "voltage": "V",
            "current": "A",
            "time": "s",
        }
        serialized = serialize_column_units(units)
        # Must be sorted keys and compact separators
        assert serialized == '{"current":"A","time":"s","voltage":"V"}'
        assert " " not in serialized

    def test_unitless_columns_represented_as_null(self):
        """Unitless columns with None serialize to JSON null and deserialize back to None."""
        units = {
            "cycle": None,
            "point": None,
            "direction": None,
            "time": "s",
            "detector_voltage": "V",
        }
        serialized = serialize_column_units(units)
        assert '"cycle":null' in serialized
        assert '"direction":null' in serialized
        assert '"point":null' in serialized

        recovered = deserialize_column_units(serialized)
        assert recovered == units
        assert recovered["cycle"] is None
        assert recovered["time"] == "s"

    def test_round_trip_with_scientific_units(self):
        """Complex units (uC/cm^2, Oe, deg, ohm) round trip identically."""
        units = {
            "angle": "deg",
            "field": "Oe",
            "polarization": "uC/cm^2",
            "resistance": "ohm",
            "voltage": "V",
        }
        json_str = serialize_column_units(units)
        recovered = deserialize_column_units(json_str)
        assert recovered == units
        assert json.loads(json_str) == units

    def test_invalid_unit_type_rejected(self):
        """Non-string/non-None units raise TypeError."""
        with pytest.raises(TypeError, match="string or None"):
            serialize_column_units({"voltage": 123})  # type: ignore

    def test_deserialize_invalid_json_rejected(self):
        """Invalid JSON input raises appropriate exceptions."""
        with pytest.raises(TypeError):
            deserialize_column_units(123)  # type: ignore
        with pytest.raises(json.JSONDecodeError):
            deserialize_column_units("{invalid json")
        with pytest.raises(ValueError, match="JSON object"):
            deserialize_column_units('["list", "not", "dict"]')


# ============================================================================
# 2. Column Units Validation (Section 7.1)
# ============================================================================

class TestColumnUnitsValidation:
    """Verifies that all saved columns must have declared units."""

    def test_validation_succeeds_when_all_columns_declared(self):
        columns = ["voltage", "current"]
        units = {"voltage": "V", "current": "A"}
        validated = validate_column_units(columns, units)
        assert validated == {"voltage": "V", "current": "A"}

    def test_validation_fails_when_column_missing(self):
        columns = ["time", "voltage", "current"]
        units = {"voltage": "V", "current": "A"}
        with pytest.raises(ValueError, match="Missing unit specification for data column.*time"):
            validate_column_units(columns, units)


# ============================================================================
# 3. Handle-Based Writer & CSV Layout (Section 7.1 & 8.1)
# ============================================================================

class TestHandleBasedWriter:
    """Verifies one-row metadata, blank separator, and data table layout through a single handle."""

    def test_exact_csv_layout(self):
        """Output CSV has metadata header (row 0), metadata values (row 1), blank line (row 2), data header (row 3)."""
        buf = io.StringIO()
        metadata = {
            "measurement_schema": "iv_sweep",
            "measurement_schema_version": 1,
            "run_id": "test-uuid-1234",
            "outcome": "COMPLETED",
            "partial": False,
            "save_requested": True,
            "compliance": 0.05,
        }
        data = pd.DataFrame({
            "voltage": [0.0, 1.0, 2.0],
            "current": [0.0, 0.01, 0.02],
        })
        units = {"voltage": "V", "current": "A"}

        write_measurement_handle(buf, metadata, data, column_units=units, sync=False)
        content = buf.getvalue()
        lines = content.splitlines()

        # Check line-by-line structure
        assert len(lines) == 7  # 2 metadata + 1 blank + 4 data (header + 3 rows)

        # Line 0: metadata header
        meta_header = lines[0].split(",")
        assert "measurement_schema" in meta_header
        assert "measurement_schema_version" in meta_header
        assert "column_units_json" in meta_header
        assert "run_id" in meta_header

        # Line 1: metadata row
        assert "iv_sweep" in lines[1]
        assert "test-uuid-1234" in lines[1]

        # Line 2: blank line separator
        assert lines[2] == ""

        # Line 3: data header
        assert lines[3] == "voltage,current"

        # Lines 4-6: data rows
        assert lines[4] == "0.0,0.0"
        assert lines[5] == "1.0,0.01"
        assert lines[6] == "2.0,0.02"

    def test_handle_writer_flushes_and_fsyncs(self, tmp_path):
        """write_measurement_csv flushes and fsyncs the open handle."""
        target_file = tmp_path / "sync_test.csv"
        metadata = {
            "measurement_schema": "moke",
            "measurement_schema_version": 1,
            "run_id": "uuid-sync",
            "outcome": "COMPLETED",
            "partial": False,
            "save_requested": True,
        }
        data = pd.DataFrame({"time": [0.1], "detector_voltage": [1.23]})
        units = {"time": "s", "detector_voltage": "V"}

        with patch("os.fsync") as mock_fsync:
            write_measurement_csv(target_file, metadata, data, column_units=units, sync=True)
            mock_fsync.assert_called_once()

        assert target_file.exists()

    def test_missing_column_in_units_rejected_by_writer(self):
        """write_measurement_handle rejects data columns missing from column_units_json."""
        buf = io.StringIO()
        metadata = {
            "measurement_schema": "iv_sweep",
            "measurement_schema_version": 1,
            "run_id": "test-uuid",
            "outcome": "COMPLETED",
            "partial": False,
            "save_requested": True,
            "column_units_json": '{"voltage":"V"}',  # Missing current!
        }
        data = pd.DataFrame({"voltage": [1.0], "current": [0.01]})

        with pytest.raises(ValueError, match="missing entries for columns.*current"):
            write_measurement_handle(buf, metadata, data, sync=False)

    def test_single_handle_utilities_function(self, tmp_path):
        """piec.analysis.utilities.metadata_and_data_to_csv writes through single handle with exact layout."""
        target = tmp_path / "util_test.csv"
        meta_df = pd.DataFrame([{"schema": "test", "version": 1}])
        data_df = pd.DataFrame({"x": [1, 2], "y": [10, 20]})

        metadata_and_data_to_csv(meta_df, data_df, str(target))

        content = target.read_text(encoding="utf-8")
        lines = content.splitlines()
        assert lines[0] == "schema,version"
        assert lines[1] == "test,1"
        assert lines[2] == ""
        assert lines[3] == "x,y"
        assert lines[4] == "1,10"
        assert lines[5] == "2,20"

    def test_write_handle_with_dataframe_metadata_and_units(self):
        """Passing a DataFrame for metadata with column_units adds column_units_json correctly."""
        buf = io.StringIO()
        meta_df = pd.DataFrame([{
            "measurement_schema": "iv_sweep",
            "measurement_schema_version": 1,
            "run_id": "uuid-df-meta",
            "outcome": "COMPLETED",
            "partial": False,
            "save_requested": True,
        }])
        data = pd.DataFrame({"voltage": [1.0], "current": [0.01]})
        units = {"voltage": "V", "current": "A"}

        write_measurement_handle(buf, meta_df, data, column_units=units, sync=False)
        content = buf.getvalue()
        assert "column_units_json" in content
        meta_out, data_out, units_out = read_measurement_csv(io.StringIO(content))
        assert units_out == units
        assert meta_out["column_units_json"] == '{"current":"A","voltage":"V"}'

    def test_multi_row_metadata_dataframe_rejected(self):
        """write_measurement_handle rejects a metadata DataFrame with more than 1 row."""
        buf = io.StringIO()
        meta_df = pd.DataFrame([
            {"measurement_schema": "iv_sweep", "run_id": "1"},
            {"measurement_schema": "iv_sweep", "run_id": "2"},
        ])
        data = pd.DataFrame({"voltage": [1.0], "current": [0.01]})

        with pytest.raises(ValueError, match="Metadata DataFrame must have exactly 1 row"):
            write_measurement_handle(buf, meta_df, data, sync=False)

    def test_conflicting_column_units_rejected(self):
        """Providing conflicting column_units argument and column_units_json in metadata raises ValueError."""
        buf = io.StringIO()
        metadata = {
            "measurement_schema": "iv_sweep",
            "measurement_schema_version": 1,
            "run_id": "test-conflict",
            "outcome": "COMPLETED",
            "partial": False,
            "save_requested": True,
            "column_units_json": '{"current":"A","voltage":"V"}',
        }
        data = pd.DataFrame({"voltage": [1.0], "current": [0.01]})
        conflicting_units = {"voltage": "mV", "current": "A"}

        with pytest.raises(ValueError, match="Conflicting column_units provided"):
            write_measurement_handle(buf, metadata, data, column_units=conflicting_units, sync=False)

    def test_extraneous_column_in_pre_serialized_units_rejected(self):
        """Pre-serialized column_units_json containing columns not in data raises ValueError."""
        buf = io.StringIO()
        metadata = {
            "measurement_schema": "iv_sweep",
            "measurement_schema_version": 1,
            "run_id": "test-extra",
            "outcome": "COMPLETED",
            "partial": False,
            "save_requested": True,
            "column_units_json": '{"current":"A","extra":"V","voltage":"V"}',
        }
        data = pd.DataFrame({"voltage": [1.0], "current": [0.01]})

        with pytest.raises(ValueError, match="extraneous columns not in data"):
            write_measurement_handle(buf, metadata, data, sync=False)


# ============================================================================
# 4. Non-ASCII & Unicode Metadata Preservation (Section 8.4)
# ============================================================================

class TestUnicodeMetadataPreservation:
    """Verifies non-ASCII characters in metadata and units survive write/read cycles."""

    def test_unicode_metadata_round_trip(self, tmp_path):
        target = tmp_path / "unicode_test.csv"
        metadata = {
            "measurement_schema": "amr",
            "measurement_schema_version": 1,
            "run_id": "uuid-unicode",
            "outcome": "COMPLETED",
            "partial": False,
            "save_requested": True,
            "sample_notes": "Sample θ-axis annealed at 300°C (μm scale)",
            "operator": "山田太郎",
        }
        data = pd.DataFrame({"angle": [0.0, 45.0], "field": [100.0, 100.0]})
        units = {"angle": "°", "field": "Oe"}

        write_measurement_csv(target, metadata, data, column_units=units)

        # Read back
        meta_loaded, data_loaded, units_loaded = read_measurement_csv(target)
        assert meta_loaded["sample_notes"] == "Sample θ-axis annealed at 300°C (μm scale)"
        assert meta_loaded["operator"] == "山田太郎"
        assert units_loaded["angle"] == "°"
        assert units_loaded["field"] == "Oe"
        pd.testing.assert_frame_equal(data_loaded, data)


# ============================================================================
# 5. Reader Helper (read_measurement_csv)
# ============================================================================

class TestMeasurementReader:
    """Verifies that read_measurement_csv correctly extracts metadata, units, and data."""

    def test_full_round_trip_all_standard_schemas(self, tmp_path):
        """Round trips all standard schema names defined in Section 7.1."""
        for schema_name, version in STANDARD_SCHEMAS.items():
            target = tmp_path / f"{schema_name}_test.csv"
            metadata = {
                "measurement_schema": schema_name,
                "measurement_schema_version": version,
                "run_id": f"uuid-{schema_name}",
                "outcome": "COMPLETED",
                "partial": False,
                "save_requested": True,
                "step_count": 10,
            }
            data = pd.DataFrame({"col_a": [1.0, 2.0], "col_b": [10.0, 20.0]})
            units = {"col_a": "s", "col_b": None}

            write_measurement_csv(target, metadata, data, column_units=units)
            meta_out, data_out, units_out = read_measurement_csv(target)

            assert meta_out["measurement_schema"] == schema_name
            assert meta_out["measurement_schema_version"] == version
            assert meta_out["run_id"] == f"uuid-{schema_name}"
            assert units_out == units
            pd.testing.assert_frame_equal(data_out, data)

    def test_reader_rejects_truncated_file(self):
        """Truncated files with fewer than 3 lines raise ValueError."""
        buf = io.StringIO("header1,header2\nvalue1,value2\n")
        with pytest.raises(ValueError, match="must contain metadata"):
            read_measurement_csv(buf)

    def test_reader_handles_empty_data_table(self, tmp_path):
        """Handles files with metadata but empty data table cleanly."""
        target = tmp_path / "empty_data.csv"
        metadata = {
            "measurement_schema": "iv_sweep",
            "measurement_schema_version": 1,
            "run_id": "uuid-empty",
            "outcome": "ABORTED",
            "partial": True,
            "save_requested": False,
        }
        data = pd.DataFrame(columns=["voltage", "current"])
        units = {"voltage": "V", "current": "A"}

        write_measurement_csv(target, metadata, data, column_units=units)
        meta_out, data_out, units_out = read_measurement_csv(target)

        assert meta_out["outcome"] == "ABORTED"
        assert meta_out["partial"] is True or meta_out["partial"] == "True"
        assert list(data_out.columns) == ["voltage", "current"]
        assert len(data_out) == 0
        assert units_out == units

    def test_reader_rejects_missing_blank_separator_line(self):
        """Files without a blank separator at line 3 (index 2) raise ValueError."""
        buf = io.StringIO("meta_a,meta_b\n1,2\nnot_blank_line\ncol_a,col_b\n10,20\n")
        with pytest.raises(ValueError, match="blank separator line"):
            read_measurement_csv(buf)


# ============================================================================
# 6. Scalar Metadata Validation (Section 7.1)
# ============================================================================

class TestMetadataValidation:
    """Verifies validation of required scalar metadata fields and schemas."""

    def test_validate_metadata_passes_with_all_required_fields(self):
        meta = {
            "measurement_schema": "iv_sweep",
            "measurement_schema_version": 1,
            "run_id": "test-uuid-1",
            "outcome": "COMPLETED",
            "partial": False,
            "save_requested": True,
            "column_units_json": '{"current":"A","voltage":"V"}',
            "temperature_k": 300.0,
        }
        validated = validate_metadata(meta)
        assert validated["measurement_schema"] == "iv_sweep"
        assert validated["temperature_k"] == 300.0

    def test_validate_metadata_fails_when_field_missing(self):
        meta = {
            "measurement_schema": "iv_sweep",
            "measurement_schema_version": 1,
            # run_id is missing!
            "outcome": "COMPLETED",
            "partial": False,
            "save_requested": True,
            "column_units_json": '{"voltage":"V"}',
        }
        with pytest.raises(ValueError, match="Missing required metadata field.*run_id"):
            validate_metadata(meta)

    def test_validate_metadata_strict_schema_checks(self):
        meta = {
            "measurement_schema": "unknown_schema",
            "measurement_schema_version": 1,
            "run_id": "test-uuid-2",
            "outcome": "COMPLETED",
            "partial": False,
            "save_requested": True,
            "column_units_json": "{}",
        }
        with pytest.raises(ValueError, match="Unknown measurement_schema 'unknown_schema'"):
            validate_metadata(meta, strict_schema=True)

        meta["measurement_schema"] = "iv_sweep"
        meta["measurement_schema_version"] = 99  # Invalid version!
        with pytest.raises(ValueError, match="Invalid measurement_schema_version 99"):
            validate_metadata(meta, strict_schema=True)

    def test_validate_metadata_empty_dataframe_rejected(self):
        with pytest.raises(ValueError, match="exactly 1 row"):
            validate_metadata(pd.DataFrame())


# ============================================================================
# 7. Standard Schemas and Target Columns (Section 7.1 & 7.2)
# ============================================================================

class TestStandardSchemaConstants:
    """Verifies that standard schemas and target columns match Section 7.1 and 7.2 specifications."""

    def test_standard_schemas_match_plan(self):
        expected = {
            "iv_sweep": 1,
            "moke": 1,
            "discrete_waveform": 1,
            "hysteresis": 1,
            "three_pulse_pund": 1,
            "amr": 1,
        }
        assert STANDARD_SCHEMAS == expected

    def test_standard_columns_match_plan(self):
        assert STANDARD_COLUMNS["iv_sweep"] == ("voltage", "current")
        assert STANDARD_COLUMNS["discrete_waveform"] == ("time", "voltage")
        assert STANDARD_COLUMNS["amr"] == ("angle", "field", "x", "y")
        assert STANDARD_COLUMNS["hysteresis"] == (
            "time",
            "voltage",
            "current",
            "polarization",
            "applied_voltage",
        )
        assert STANDARD_COLUMNS["three_pulse_pund"] == (
            "time",
            "voltage",
            "current",
            "polarization",
            "polarization_p_hat",
            "polarization_p_star",
            "polarization_p_hat_r",
            "polarization_p_star_r",
            "delta_polarization",
            "applied_voltage",
        )
        assert STANDARD_COLUMNS["moke"] == (
            "time",
            "cycle",
            "point",
            "direction",
            "source_output",
            "field_calibrated",
            "detector_voltage",
        )

# ============================================================================
# Part 2: Atomic No-Replace Publication & Staging (Checkpoint 11b)
# ============================================================================

def sample_metadata(run_id: str = "run-uuid-001") -> dict:
    return {
        "measurement_schema": "iv_sweep",
        "measurement_schema_version": 1,
        "run_id": run_id,
        "outcome": "COMPLETED",
        "partial": False,
        "save_requested": True,
        "column_units_json": '{"current":"A","voltage":"V"}',
    }


def sample_data() -> pd.DataFrame:
    return pd.DataFrame({"voltage": [0.0, 1.0, 2.0], "current": [0.0, 0.01, 0.02]})


# ============================================================================
# 1. Atomic No-Replace Primitives (Section 8.1 Rule 6)
# ============================================================================

class TestAtomicPublishNoReplace:
    """Verifies atomic_publish_no_replace behavior and guarantees."""

    def test_publish_new_file_succeeds(self, tmp_path):
        """Staged file is atomically published to target path."""
        target = tmp_path / "published.csv"
        fd, staging = create_staging_file(tmp_path)
        os.close(fd)
        staging.write_text("test data content", encoding="utf-8")

        result = atomic_publish_no_replace(staging, target)
        assert result == target
        assert target.exists()
        assert target.read_text(encoding="utf-8") == "test data content"
        assert not staging.exists(), "Staging file should have been moved"

    def test_publish_rejects_existing_target_without_overwrite(self, tmp_path):
        """If target exists, publication fails with FileExistsError and preserves both files."""
        target = tmp_path / "existing.csv"
        target.write_text("ORIGINAL CONTENT", encoding="utf-8")

        fd, staging = create_staging_file(tmp_path)
        os.close(fd)
        staging.write_text("NEW CONTENT", encoding="utf-8")

        with pytest.raises(FileExistsError, match="Target file already exists"):
            atomic_publish_no_replace(staging, target)

        # Target must remain completely unmodified
        assert target.read_text(encoding="utf-8") == "ORIGINAL CONTENT"
        # Staging file must be preserved for recovery
        assert staging.exists()
        assert staging.read_text(encoding="utf-8") == "NEW CONTENT"

    def test_publish_rejects_missing_staging_file(self, tmp_path):
        """Missing staging file raises FileNotFoundError."""
        target = tmp_path / "output.csv"
        nonexistent = tmp_path / "nonexistent.tmp"

        with pytest.raises(FileNotFoundError, match="Staging file does not exist"):
            atomic_publish_no_replace(nonexistent, target)

    def test_publish_rejects_same_path(self, tmp_path):
        """Providing same path for staging and target raises ValueError."""
        same = tmp_path / "same.csv"
        same.write_text("data", encoding="utf-8")

        with pytest.raises(ValueError, match="cannot be the same"):
            atomic_publish_no_replace(same, same)

    def test_publish_creates_target_parent_directory(self, tmp_path):
        """Parent directories of target are created if they do not exist."""
        nested_target = tmp_path / "sub" / "deep" / "target.csv"
        fd, staging = create_staging_file(tmp_path)
        os.close(fd)
        staging.write_text("deep data", encoding="utf-8")

        atomic_publish_no_replace(staging, nested_target)
        assert nested_target.exists()
        assert nested_target.read_text(encoding="utf-8") == "deep data"


# ============================================================================
# 2. NTFS Concurrent Publication & Collision Resistance (Section 8.4)
# ============================================================================

class TestNTFSConcurrentPublish:
    """Verifies behavior under simultaneous publication attempts to the same target."""

    def test_simultaneous_writers_same_candidate(self, tmp_path):
        """Multiple threads racing to publish to the same target: exactly 1 wins, others fail cleanly."""
        target = tmp_path / "race_target.csv"
        num_writers = 10

        # Prepare staging files for each writer
        staging_files = []
        for i in range(num_writers):
            fd, stg = create_staging_file(tmp_path, prefix=f".writer-{i}-")
            os.close(fd)
            stg.write_text(f"CONTENT FROM WRITER {i}\n", encoding="utf-8")
            staging_files.append((i, stg))

        results = {}

        def attempt_publish(writer_id, stg_path):
            try:
                atomic_publish_no_replace(stg_path, target)
                return ("SUCCESS", writer_id)
            except FileExistsError:
                return ("COLLISION", writer_id)

        with concurrent.futures.ThreadPoolExecutor(max_workers=num_writers) as executor:
            futures = [
                executor.submit(attempt_publish, wid, sp)
                for wid, sp in staging_files
            ]
            for f in concurrent.futures.as_completed(futures):
                status, wid = f.result()
                results[wid] = status

        successes = [wid for wid, s in results.items() if s == "SUCCESS"]
        collisions = [wid for wid, s in results.items() if s == "COLLISION"]

        # Exactly ONE writer must succeed
        assert len(successes) == 1, f"Expected exactly 1 winner, got {len(successes)}"
        assert len(collisions) == num_writers - 1

        winner_id = successes[0]
        # Target must match winner's exact content
        assert target.read_text(encoding="utf-8") == f"CONTENT FROM WRITER {winner_id}\n"

        # Staging files of all losing writers must remain intact on disk
        for wid, stg in staging_files:
            if wid == winner_id:
                assert not stg.exists(), f"Winner staging {stg} should have been moved"
            else:
                assert stg.exists(), f"Loser staging {stg} must be preserved for recovery"
                assert stg.read_text(encoding="utf-8") == f"CONTENT FROM WRITER {wid}\n"

    def test_simultaneous_writers_measurement_csv(self, tmp_path):
        """Multiple threads racing with atomic_publish_measurement_csv."""
        target = tmp_path / "race_measurement.csv"
        num_writers = 8

        def write_worker(idx):
            meta = sample_metadata(run_id=f"run-{idx:03d}")
            data = pd.DataFrame({"voltage": [float(idx)], "current": [float(idx) * 0.01]})
            try:
                atomic_publish_measurement_csv(target, meta, data)
                return ("SUCCESS", idx)
            except FileExistsError:
                return ("COLLISION", idx)

        with concurrent.futures.ThreadPoolExecutor(max_workers=num_writers) as executor:
            futures = [executor.submit(write_worker, i) for i in range(num_writers)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        successes = [idx for status, idx in results if status == "SUCCESS"]
        collisions = [idx for status, idx in results if status == "COLLISION"]

        assert len(successes) == 1
        assert len(collisions) == num_writers - 1

        winner_idx = successes[0]
        meta_read, data_read, _ = read_measurement_csv(target)
        assert meta_read["run_id"] == f"run-{winner_idx:03d}"
        assert data_read.iloc[0]["voltage"] == float(winner_idx)


# ============================================================================
# 3. Atomic Measurement CSV Publisher (Section 8.1 & 8.3)
# ============================================================================

class TestAtomicPublishMeasurementCSV:
    """Verifies atomic_publish_measurement_csv and integration with write_measurement_csv."""

    def test_atomic_publish_measurement_csv_success(self, tmp_path):
        """Publishing a measurement CSV atomically creates valid file and cleans staging."""
        target = tmp_path / "clean_run.csv"
        meta = sample_metadata("clean-uuid")
        data = sample_data()

        result = atomic_publish_measurement_csv(target, meta, data)
        assert result == target
        assert target.exists()

        meta_loaded, data_loaded, units_loaded = read_measurement_csv(target)
        assert meta_loaded["run_id"] == "clean-uuid"
        pd.testing.assert_frame_equal(data_loaded, data)
        assert units_loaded == {"voltage": "V", "current": "A"}

        # No staging files left behind
        staging_files = [f for f in tmp_path.iterdir() if f.name.startswith(".staging-")]
        assert len(staging_files) == 0

    def test_atomic_publish_rejects_preexisting_target_without_truncation(self, tmp_path):
        """Pre-existing target is never truncated or overwritten."""
        target = tmp_path / "important_data.csv"
        target.write_text("CRITICAL EXISTING DATA", encoding="utf-8")

        meta = sample_metadata("overwrite-attempt")
        data = sample_data()

        with pytest.raises(FileExistsError, match="Target file already exists"):
            atomic_publish_measurement_csv(target, meta, data)

        assert target.read_text(encoding="utf-8") == "CRITICAL EXISTING DATA"

    def test_atomic_publish_fails_before_write_on_invalid_metadata(self, tmp_path):
        """Validation occurs before touching disk: no staging file or directory is created."""
        target = tmp_path / "never_created" / "test.csv"
        invalid_meta = {"outcome": "COMPLETED"}  # Missing required fields
        data = sample_data()

        with pytest.raises(ValueError, match="Missing required"):
            atomic_publish_measurement_csv(target, invalid_meta, data)

        assert not target.parent.exists()

    def test_atomic_publish_cleans_up_staging_on_write_error(self, tmp_path):
        """If handle write/fsync fails, incomplete staging file is cleaned up."""
        target = tmp_path / "sync_fail.csv"
        meta = sample_metadata("sync-fail-uuid")
        data = sample_data()

        error = OSError("simulated disk flush failure")
        with patch("os.fsync", side_effect=error):
            with pytest.raises(OSError, match="simulated disk flush failure"):
                atomic_publish_measurement_csv(target, meta, data)

        assert not target.exists()
        # Incomplete staging file was cleaned up
        staging_files = [f for f in tmp_path.iterdir() if f.name.startswith(".staging-")]
        assert len(staging_files) == 0

    def test_write_measurement_csv_atomic_flag(self, tmp_path):
        """write_measurement_csv with atomic=True enforces no-replace semantics."""
        target = tmp_path / "atomic_flag.csv"
        meta = sample_metadata("flag-test")
        data = sample_data()

        # First write succeeds
        write_measurement_csv(target, meta, data, atomic=True)
        assert target.exists()

        # Second write with atomic=True fails with FileExistsError
        with pytest.raises(FileExistsError):
            write_measurement_csv(target, meta, data, atomic=True)

    def test_write_measurement_csv_non_atomic_overwrites(self, tmp_path):
        """write_measurement_csv with atomic=False (default) acts as path writer (11a behavior)."""
        target = tmp_path / "overwrite_flag.csv"
        meta1 = sample_metadata("run-1")
        meta2 = sample_metadata("run-2")
        data = sample_data()

        write_measurement_csv(target, meta1, data, atomic=False)
        assert read_measurement_csv(target)[0]["run_id"] == "run-1"

        # Overwrite with atomic=False succeeds
        write_measurement_csv(target, meta2, data, atomic=False)
        assert read_measurement_csv(target)[0]["run_id"] == "run-2"


# ============================================================================
# 4. Strict vs Non-Strict Filesystem Modes (Section 8.1 Rule 7)
# ============================================================================

class TestStrictAndFallbackModes:
    """Verifies strict failure mode and non-strict collision-resistant fallback."""

    def test_strict_mode_rejects_cross_volume_move(self, tmp_path):
        """Cross-drive/volume move in strict mode raises UnsupportedFilesystemError."""
        fd, staging = create_staging_file(tmp_path)
        os.close(fd)
        staging.write_text("data", encoding="utf-8")
        target = tmp_path / "target.csv"

        cross_drive_error = OSError()
        cross_drive_error.winerror = 17  # ERROR_NOT_SAME_DEVICE

        with patch("os.rename", side_effect=cross_drive_error):
            with pytest.raises(UnsupportedFilesystemError, match="Cannot atomically publish across"):
                atomic_publish_no_replace(staging, target, strict=True)

        # Staging remains intact
        assert staging.exists()

    def test_non_strict_fallback_performs_collision_resistant_publish(self, tmp_path):
        """In non-strict mode (strict=False), cross-volume error falls back to collision-resistant publish."""
        dir_a = tmp_path / "volume_a"
        dir_b = tmp_path / "volume_b"
        dir_a.mkdir()
        dir_b.mkdir()

        fd, staging = create_staging_file(dir_a)
        os.close(fd)
        staging.write_text("fallback data", encoding="utf-8")
        target = dir_b / "target.csv"

        real_rename = os.rename

        def mock_rename(src, dst):
            # Simulate cross-volume move failure on direct rename from dir_a to dir_b
            if str(src) == str(staging):
                err = OSError("The system cannot move the file to a different disk drive")
                err.winerror = 17
                raise err
            return real_rename(src, dst)

        with patch("os.rename", side_effect=mock_rename):
            result = atomic_publish_no_replace(staging, target, strict=False)
            assert result == target
            assert target.exists()
            assert target.read_text(encoding="utf-8") == "fallback data"
            # Hidden reservation marker must be cleaned up
            assert not (dir_b / ".target.csv.res").exists()

    def test_collision_resistant_fallback_rejects_existing_target(self, tmp_path):
        """_collision_resistant_publish rejects existing target with FileExistsError."""
        target = tmp_path / "collision_target.csv"
        target.write_text("ALREADY HERE", encoding="utf-8")

        fd, staging = create_staging_file(tmp_path)
        os.close(fd)
        staging.write_text("NEW DATA", encoding="utf-8")

        with pytest.raises(FileExistsError, match="Target file already exists"):
            _collision_resistant_publish(staging, target)

        assert target.read_text(encoding="utf-8") == "ALREADY HERE"
        assert staging.exists()
        assert not (tmp_path / ".collision_target.csv.res").exists()

    def test_collision_resistant_fallback_rejects_active_reservation(self, tmp_path):
        """If reservation marker already exists, fallback rejects with FileExistsError."""
        target = tmp_path / "reserved_target.csv"
        marker = tmp_path / ".reserved_target.csv.res"
        marker.write_text("pid=99999", encoding="utf-8")

        fd, staging = create_staging_file(tmp_path)
        os.close(fd)
        staging.write_text("NEW DATA", encoding="utf-8")

        with pytest.raises(FileExistsError, match="Target file is currently reserved"):
            _collision_resistant_publish(staging, target)

        # Target was never created!
        assert not target.exists()
        assert staging.exists()

    def test_collision_resistant_fallback_no_empty_csv_on_interruption(self, tmp_path):
        """An interruption during fallback copying never exposes an empty completed-looking CSV."""
        dir_a = tmp_path / "source"
        dir_b = tmp_path / "dest"
        dir_a.mkdir()
        dir_b.mkdir()

        fd, staging = create_staging_file(dir_a)
        os.close(fd)
        staging.write_text("STAGING DATA", encoding="utf-8")
        target = dir_b / "final.csv"

        # Simulate interruption during copy
        with patch("shutil.copyfileobj", side_effect=KeyboardInterrupt("Interrupted!")):
            with pytest.raises(KeyboardInterrupt):
                _collision_resistant_publish(staging, target)

        # CRITICAL: final.csv was NEVER created on disk!
        assert not target.exists()
        # Original staging preserved intact for recovery
        assert staging.exists()
        assert staging.read_text(encoding="utf-8") == "STAGING DATA"
        # Marker cleaned up
        assert not (dir_b / ".final.csv.res").exists()

    def test_competing_writer_creates_target_during_publication(self, tmp_path):
        """If a competing writer creates target during publication, FileExistsError is raised,
        competing target is never overwritten, and staging is preserved intact."""
        fd, staging = create_staging_file(tmp_path)
        os.close(fd)
        staging.write_text("MY VALUABLE STAGING DATA", encoding="utf-8")
        target = tmp_path / "race_target.csv"

        real_rename = os.rename

        def mock_rename_with_collision(src, dst):
            # Competing writer creates target immediately before publish move
            target.write_text("COMPETING WRITER CONTENT", encoding="utf-8")
            return real_rename(src, dst)

        with patch("os.rename", side_effect=mock_rename_with_collision):
            with pytest.raises(FileExistsError):
                atomic_publish_no_replace(staging, target)

        # Competing target is unmodified
        assert target.read_text(encoding="utf-8") == "COMPETING WRITER CONTENT"
        # Staging file is preserved intact for recovery
        assert staging.exists()
        assert staging.read_text(encoding="utf-8") == "MY VALUABLE STAGING DATA"

    def test_posix_fallback_without_safe_no_replace_raises_unsupported_and_preserves_staging(self, tmp_path):
        """On POSIX where no safe no-replace operation is available (e.g. link fails with EOPNOTSUPP),
        UnsupportedFilesystemError is raised, check-then-rename is NOT performed, and staging is preserved."""
        fd, staging = create_staging_file(tmp_path)
        os.close(fd)
        staging.write_text("VALUABLE STAGING DATA", encoding="utf-8")
        target = tmp_path / "posix_target.csv"

        link_err = OSError(errno.EOPNOTSUPP, "Operation not supported")

        with patch("os.name", "posix"):
            with patch("os.link", side_effect=link_err):
                with pytest.raises(UnsupportedFilesystemError, match="does not support safe atomic no-replace"):
                    _collision_resistant_publish(staging, target)

        # Staging must be preserved intact for recovery
        assert staging.exists()
        assert staging.read_text(encoding="utf-8") == "VALUABLE STAGING DATA"
        # Target was never created
        assert not target.exists()

    def test_reservation_marker_records_full_owner_uuid(self, tmp_path):
        """Reservation marker stores the full owner UUID (Section 8.1 Rule 5)."""
        dir_a = tmp_path / "vol_a"
        dir_b = tmp_path / "vol_b"
        dir_a.mkdir()
        dir_b.mkdir()

        fd, staging = create_staging_file(dir_a)
        os.close(fd)
        staging.write_text("data", encoding="utf-8")
        target = dir_b / "marked.csv"

        test_owner_uuid = "12345678-abcd-ef01-2345-6789abcdef01"
        real_rename = os.rename

        def mock_rename_inspect_marker(src, dst):
            if str(src) == str(staging):
                err = OSError("cross drive")
                err.winerror = 17
                raise err
            # When intra-volume publish executes, verify reservation marker content
            marker = dir_b / ".marked.csv.res"
            assert marker.exists()
            content = marker.read_text(encoding="utf-8")
            assert f"owner_uuid={test_owner_uuid}" in content
            return real_rename(src, dst)

        with patch("os.rename", side_effect=mock_rename_inspect_marker):
            atomic_publish_no_replace(
                staging, target, strict=False, owner_uuid=test_owner_uuid
            )

        assert target.exists()
        # Marker cleaned up on completion
        assert not (dir_b / ".marked.csv.res").exists()


# ============================================================================
# 5. Explicit Opt-In SMB Tests (Section 8.4 & Checkpoint 11b)
# ============================================================================

class TestOptInSMBPublish:
    """
    Opt-in SMB publication tests.

    Section 8.4:
    "the lab SMB path only when explicitly configured. SMB results are recorded
     for the tested server/filesystem and are not generalized to all network shares."

    Checkpoint 11b:
    "explicit opt-in SMB tests; untested filesystems not claimed safe"
    """

    @pytest.mark.skipif(
        not os.environ.get("PIEC_TEST_SMB_PATH"),
        reason="Opt-in SMB test skipped: PIEC_TEST_SMB_PATH environment variable not set",
    )
    def test_smb_atomic_publish_no_replace(self):
        """Verifies atomic no-replace publication against configured lab SMB path."""
        smb_base = Path(os.environ["PIEC_TEST_SMB_PATH"])
        assert smb_base.is_dir(), f"Configured PIEC_TEST_SMB_PATH does not exist: {smb_base}"

        # Use a uniquely created test directory for this invocation
        test_dir_str = tempfile.mkdtemp(prefix="piec_test_atomic_", dir=smb_base)
        test_dir = Path(test_dir_str)
        invocation_artifacts: list[Path] = []
        target = test_dir / "smb_published.csv"
        invocation_artifacts.append(target)

        test_run_id = f"smb-test-{uuid.uuid4()}"
        try:
            # 1. Publish new file
            meta = sample_metadata(test_run_id)
            data = sample_data()
            atomic_publish_measurement_csv(target, meta, data)
            assert target.exists()

            # 2. Reject existing file without overwrite; staging file is preserved for recovery
            stg_before = set(test_dir.iterdir())
            with pytest.raises(FileExistsError):
                atomic_publish_measurement_csv(target, meta, data)
            stg_after = set(test_dir.iterdir()) - stg_before
            invocation_artifacts.extend(stg_after)

            # 3. Read back and verify
            meta_loaded, data_loaded, _ = read_measurement_csv(target)
            assert meta_loaded["run_id"] == test_run_id
            pd.testing.assert_frame_equal(data_loaded, data)
        finally:
            # Restrict cleanup strictly to this invocation's artifacts
            for artifact in invocation_artifacts:
                try:
                    artifact.unlink(missing_ok=True)
                except OSError:
                    pass
            try:
                test_dir.rmdir()
            except OSError:
                pass

# ============================================================================
# Part 3: Bundles, Candidate Reservations & Partials (Checkpoint 11c)
# ============================================================================

def sample_metadata(run_id: str = "run-uuid-11c", partial: bool = False) -> dict:
    return {
        "measurement_schema": "iv_sweep",
        "measurement_schema_version": 1,
        "run_id": run_id,
        "outcome": "COMPLETED" if not partial else "ABORTED",
        "partial": partial,
        "save_requested": True,
        "column_units_json": '{"current":"A","voltage":"V"}',
    }


def sample_data(rows: int = 3) -> pd.DataFrame:
    return pd.DataFrame({
        "voltage": [float(i) for i in range(rows)],
        "current": [float(i) * 0.01 for i in range(rows)],
    })


def create_staged_csv(destination_dir: Path, metadata: dict, data: pd.DataFrame) -> Path:
    fd, staging = create_staging_file(destination_dir, prefix=".stg-csv-", suffix=".tmp")
    with io.open(fd, "w", encoding="utf-8", newline="") as h:
        write_measurement_handle(h, metadata, data)
    return staging


# ============================================================================
# 1. Candidate Reservation (Section 8.1 Rule 5)
# ============================================================================

class TestCandidateReservation:
    """Verifies candidate filename reservation grammar, markers, and collisions."""

    def test_reserve_first_candidate(self, tmp_path):
        """First reservation in empty directory claims index 1 with marker storing owner UUID."""
        run_id = "test-owner-uuid-001"
        res = reserve_candidate_filename(tmp_path, "iv_sweep", run_id)

        assert res.candidate_path.name == "0001_iv_sweep.csv"
        assert res.marker_path.name == ".0001_iv_sweep.csv.res"
        assert res.candidate_basename == "0001_iv_sweep"
        assert res.index == 1
        assert res.run_id == run_id

        # Target completed CSV must NOT exist (never reserve with empty CSV)
        assert not res.candidate_path.exists()
        # Marker must exist and contain owner_uuid
        assert res.marker_path.exists()
        content = res.marker_path.read_text(encoding="utf-8")
        assert f"owner_uuid={run_id}" in content

        res.release()
        assert not res.marker_path.exists()

    def test_reserve_skips_existing_targets(self, tmp_path):
        """Reservation iterates past existing completed CSV targets."""
        # Pre-create 0001 and 0002
        (tmp_path / "0001_iv_sweep.csv").write_text("existing 1", encoding="utf-8")
        (tmp_path / "0002_iv_sweep.csv").write_text("existing 2", encoding="utf-8")

        res = reserve_candidate_filename(tmp_path, "iv_sweep", "run-003")
        assert res.candidate_path.name == "0003_iv_sweep.csv"
        res.release()

    def test_reserve_skips_active_reservation_markers(self, tmp_path):
        """Reservation iterates past markers held by other writers."""
        (tmp_path / ".0001_iv_sweep.csv.res").write_text(
            f"owner_uuid=other\ntimestamp={time.time()}\n", encoding="utf-8"
        )

        res = reserve_candidate_filename(tmp_path, "iv_sweep", "run-my-uuid")
        assert res.candidate_path.name == "0002_iv_sweep.csv"
        res.release()

    def test_concurrent_reservation_race(self, tmp_path):
        """Multiple threads reserving concurrently each get a distinct candidate index without collision."""
        num_threads = 10
        reservations = []

        def reserve_worker(idx):
            r = reserve_candidate_filename(tmp_path, "iv_sweep", f"uuid-{idx}")
            return r

        with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(reserve_worker, i) for i in range(num_threads)]
            for f in concurrent.futures.as_completed(futures):
                reservations.append(f.result())

        indices = [r.index for r in reservations]
        assert len(indices) == num_threads
        assert len(set(indices)) == num_threads, "All indices must be strictly unique"
        assert set(indices) == set(range(1, num_threads + 1))

        # Cleanup
        for r in reservations:
            r.release()

    def test_stale_marker_reuse_policy(self, tmp_path):
        """A stale marker older than stale_age_seconds is approved for reuse."""
        marker = tmp_path / ".0001_iv_sweep.csv.res"
        old_time = time.time() - 3600  # 1 hour ago
        marker.write_text(f"owner_uuid=stale-run\ntimestamp={old_time}\n", encoding="utf-8")

        res = reserve_candidate_filename(
            tmp_path, "iv_sweep", "stale-run", stale_age_seconds=600
        )
        # Reclaimed stale candidate 0001
        assert res.index == 1
        assert res.candidate_path.name == "0001_iv_sweep.csv"
        content = res.marker_path.read_text(encoding="utf-8")
        assert "owner_uuid=stale-run" in content
        res.release()

    def test_reservation_context_manager_releases_marker(self, tmp_path):
        """Context manager cleans up marker upon exit."""
        with reserve_candidate_filename(tmp_path, "iv_sweep", "run-cm") as res:
            assert res.marker_path.exists()
        assert not res.marker_path.exists()


# ============================================================================
# 2. Multi-Artifact Bundles (Section 8.2)
# ============================================================================

class TestMultiArtifactBundle:
    """Verifies multi-artifact bundle publication ordering, atomicity, and rollback."""

    def test_publish_bundle_happy_path(self, tmp_path):
        """Side artifacts published first, completed CSV published last, marker released."""
        run_id = "bundle-run-001"
        res = reserve_candidate_filename(tmp_path, "iv_sweep", run_id)
        base = res.candidate_basename

        # Prepare staged CSV
        meta = sample_metadata(run_id)
        data = sample_data()
        staged_csv = create_staged_csv(tmp_path, meta, data)

        # Prepare staged side artifacts (e.g. plot PNG and raw trace)
        fd_plot, staged_plot = create_staging_file(tmp_path, prefix=f".{base}_plot-", suffix=".png")
        os.close(fd_plot)
        staged_plot.write_bytes(b"SIMULATED_PNG_BINARY_DATA")

        target_plot = tmp_path / f"{base}_plot.png"
        side_artifacts = [(staged_plot, target_plot)]

        # Publish bundle
        published_csv = publish_artifact_bundle(
            res, staged_csv, side_artifacts=side_artifacts
        )

        assert published_csv == res.candidate_path
        assert published_csv.exists()
        assert target_plot.exists()
        assert target_plot.read_bytes() == b"SIMULATED_PNG_BINARY_DATA"

        # Staging files should have been moved
        assert not staged_csv.exists()
        assert not staged_plot.exists()
        # Marker released
        assert not res.marker_path.exists()

        # Verify CSV content
        meta_loaded, data_loaded, _ = read_measurement_csv(published_csv)
        assert meta_loaded["run_id"] == run_id
        pd.testing.assert_frame_equal(data_loaded, data)

    def test_bundle_rejects_existing_side_artifact_without_touching_csv(self, tmp_path):
        """Pre-existing side artifact causes immediate failure; no CSV is published."""
        run_id = "bundle-collision-run"
        res = reserve_candidate_filename(tmp_path, "iv_sweep", run_id)
        base = res.candidate_basename

        # Target side artifact already exists
        target_side = tmp_path / f"{base}_trace.bin"
        target_side.write_bytes(b"PRE_EXISTING_TRACE")

        fd_stg, staged_side = create_staging_file(tmp_path)
        os.close(fd_stg)
        staged_side.write_bytes(b"NEW_TRACE")

        staged_csv = create_staged_csv(tmp_path, sample_metadata(run_id), sample_data())

        with pytest.raises(FileExistsError, match="Side artifact target already exists"):
            publish_artifact_bundle(
                res, staged_csv, side_artifacts=[(staged_side, target_side)]
            )

        # Pre-existing file unmodified
        assert target_side.read_bytes() == b"PRE_EXISTING_TRACE"
        # Completed CSV was never published
        assert not res.candidate_path.exists()
        # Staging files preserved for recovery
        assert staged_csv.exists()
        assert staged_side.exists()
        res.release()

    def test_bundle_rollback_on_completed_csv_failure(self, tmp_path):
        """If completed CSV publish fails, published side artifacts of this reservation are rolled back."""
        run_id = "bundle-fail-csv"
        res = reserve_candidate_filename(tmp_path, "iv_sweep", run_id)
        base = res.candidate_basename

        # Prepare 2 side artifacts
        target_side1 = tmp_path / f"{base}_plot.png"
        target_side2 = tmp_path / f"{base}_raw.dat"

        fd1, stg1 = create_staging_file(tmp_path)
        os.close(fd1)
        stg1.write_bytes(b"PLOT_DATA")

        fd2, stg2 = create_staging_file(tmp_path)
        os.close(fd2)
        stg2.write_bytes(b"RAW_DATA")

        staged_csv = create_staged_csv(tmp_path, sample_metadata(run_id), sample_data())

        real_rename = os.rename

        def mock_rename_fail_csv(src, dst):
            # Allow side artifacts to publish, but fail on the completed CSV publish
            if str(dst) == str(res.candidate_path):
                raise OSError("Simulated disk error publishing final completed CSV")
            return real_rename(src, dst)

        with patch("os.rename", side_effect=mock_rename_fail_csv):
            with pytest.raises(BundlePublishError) as exc_info:
                publish_artifact_bundle(
                    res,
                    staged_csv,
                    side_artifacts=[(stg1, target_side1), (stg2, target_side2)],
                )

        # Rollback: published side artifacts were cleaned up
        assert not target_side1.exists(), "Side artifact 1 should have been rolled back"
        assert not target_side2.exists(), "Side artifact 2 should have been rolled back"
        # Completed CSV does not exist
        assert not res.candidate_path.exists()

        # All staging files must remain intact for data recovery
        assert staged_csv.exists()
        err = exc_info.value
        assert staged_csv in err.recoverable_staging_paths


# ============================================================================
# 3. In-Progress Checkpoints and Partials (Section 8.3)
# ============================================================================

class TestPartialCheckpoints:
    """Verifies in-progress checkpoints and terminal partial CSV handling."""

    def test_write_partial_csv_naming_and_metadata(self, tmp_path):
        """write_partial_csv enforces {candidate_basename}.{run_id}.partial.csv naming and partial=True."""
        run_id = "partial-run-uuid-123"
        candidate_base = "0001_iv_sweep"
        meta = sample_metadata(run_id, partial=False)  # Should be forced to True
        data = sample_data(rows=2)

        partial_path = write_partial_csv(
            tmp_path, candidate_base, run_id, meta, data
        )

        assert partial_path.name == f"{candidate_base}.{run_id}.partial.csv"
        assert partial_path.exists()

        meta_loaded, data_loaded, _ = read_measurement_csv(partial_path)
        assert meta_loaded["partial"] is True
        assert meta_loaded["run_id"] == run_id
        pd.testing.assert_frame_equal(data_loaded, data)

    def test_partial_checkpoint_intentional_overwrite(self, tmp_path):
        """Updating checkpoint for the same run is an intentional overwrite (Section 8.3)."""
        run_id = "checkpoint-run-uuid"
        candidate_base = "0002_iv_sweep"

        # Checkpoint 1: 2 rows
        data1 = sample_data(rows=2)
        p1 = write_partial_csv(tmp_path, candidate_base, run_id, sample_metadata(run_id), data1)
        assert len(read_measurement_csv(p1)[1]) == 2

        # Checkpoint 2: 5 rows (same run_id updates checkpoint)
        data2 = sample_data(rows=5)
        p2 = write_partial_csv(tmp_path, candidate_base, run_id, sample_metadata(run_id), data2)

        assert p1 == p2
        assert len(read_measurement_csv(p2)[1]) == 5

    def test_independent_partial_files_for_different_runs(self, tmp_path):
        """Different runs produce distinct partial files and do not overwrite each other."""
        candidate_base = "0001_iv_sweep"
        p_a = write_partial_csv(tmp_path, candidate_base, "run-aaa", sample_metadata("run-aaa"), sample_data(1))
        p_b = write_partial_csv(tmp_path, candidate_base, "run-bbb", sample_metadata("run-bbb"), sample_data(2))

        assert p_a != p_b
        assert p_a.exists() and p_b.exists()


# ============================================================================
# 4. Completed File Identification & Cleanup (Section 8.1 Rule 9 & 8.3)
# ============================================================================

class TestCompletedFileFilterAndCleanup:
    """Verifies is_completed_measurement_file and age-gated stale cleanup."""

    def test_is_completed_measurement_file(self):
        """Filters completed CSVs from partials, staging files, and markers."""
        assert is_completed_measurement_file("0001_iv_sweep.csv") is True
        assert is_completed_measurement_file("0002_moke.csv") is True

        # Rejected patterns
        assert is_completed_measurement_file("0001_iv_sweep.uuid.partial.csv") is False
        assert is_completed_measurement_file(".0001_iv_sweep.csv.res") is False
        assert is_completed_measurement_file(".staging-0001.tmp") is False
        assert is_completed_measurement_file(".hidden.csv") is False
        assert is_completed_measurement_file("plot.png") is False

    def test_cleanup_stale_reservations(self, tmp_path):
        """Explicit, ownership-checked, age-gated stale reservation cleanup."""
        now = time.time()
        # Stale marker (2 hours old)
        stale_marker = tmp_path / ".0001_iv_sweep.csv.res"
        stale_marker.write_text(f"owner_uuid=old-uuid\ntimestamp={now - 7200}\n", encoding="utf-8")

        # Active marker (10 seconds old)
        active_marker = tmp_path / ".0002_iv_sweep.csv.res"
        active_marker.write_text(f"owner_uuid=active-uuid\ntimestamp={now - 10}\n", encoding="utf-8")

        # Regular file (never deleted)
        regular_file = tmp_path / "0001_iv_sweep.csv"
        regular_file.write_text("data", encoding="utf-8")

        cleaned = cleanup_stale_reservations(tmp_path, max_age_seconds=3600, owner_uuid="old-uuid")
        assert stale_marker in cleaned
        assert not stale_marker.exists()
        assert active_marker.exists()
        assert regular_file.exists()

    def test_cleanup_stale_partials(self, tmp_path):
        """Explicit, age-gated partial file cleanup."""
        # Create a partial file
        partial_file = tmp_path / "0001_iv_sweep.old-run.partial.csv"
        write_partial_csv(tmp_path, "0001_iv_sweep", "old-run", sample_metadata("old-run"), sample_data())

        # Backdate its mtime
        old_time = time.time() - 10000
        os.utime(partial_file, (old_time, old_time))

        # Recent partial file
        recent_partial = tmp_path / "0002_iv_sweep.new-run.partial.csv"
        recent_partial.write_text("recent data", encoding="utf-8")

        cleaned = cleanup_stale_partials(tmp_path, max_age_seconds=3600, owner_uuid="old-run")
        assert partial_file in cleaned
        assert not partial_file.exists()
        assert recent_partial.exists()

# ============================================================================
# Part 4: Persistence Recovery & Rollback Regressions
# ============================================================================

def metadata(owner="owner"):
    return dict(measurement_schema="iv_sweep", measurement_schema_version=1,
                run_id=owner, outcome="ABORTED", partial=True, save_requested=True)


def frame():
    return pd.DataFrame({"voltage": [0., 1.], "current": [0., .01]})


UNITS = {"voltage": "V", "current": "A"}


def test_bundle_failure_retains_every_original(tmp_path, monkeypatch):
    reservation = p.reserve_candidate_filename(tmp_path, "iv_sweep", "owner")
    csv = tmp_path / ".csv-stage"
    raw = tmp_path / ".raw-stage"
    csv.write_bytes(b"CSV")
    raw.write_bytes(b"ONLY RAW COPY")
    target = tmp_path / (reservation.candidate_basename + "_raw.dat")
    publish = p.atomic_publish_no_replace

    def fail_csv(source, destination, **kwargs):
        if destination == reservation.candidate_path:
            raise OSError("CSV publication failed")
        return publish(source, destination, **kwargs)

    monkeypatch.setattr(p, "atomic_publish_no_replace", fail_csv)
    with pytest.raises(p.BundlePublishError) as error:
        p.publish_artifact_bundle(reservation, csv, [(raw, target)])
    assert raw.read_bytes() == b"ONLY RAW COPY"
    assert csv.read_bytes() == b"CSV"
    assert set(error.value.recoverable_staging_paths) == {raw, csv}
    assert not target.exists()
    assert not reservation.marker_path.exists()


def test_foreign_marker_is_not_reclaimed_and_old_owner_cannot_release_new_claim(tmp_path):
    old = p.reserve_candidate_filename(tmp_path, "iv_sweep", "old")
    claim = old.marker_path.read_text()
    old.marker_path.write_text(claim.replace(claim.split("timestamp=")[1].strip(), "0"))
    new = p.reserve_candidate_filename(tmp_path, "iv_sweep", "new", stale_age_seconds=1)
    assert new.index == 2
    # Explicit cleanup of the old run permits a later claim at index 1.
    p.cleanup_stale_reservations(tmp_path, 1, owner_uuid="old")
    replacement = p.reserve_candidate_filename(tmp_path, "iv_sweep", "replacement")
    old.release()
    assert replacement.marker_path.exists()
    replacement.validate()
    new.release()
    replacement.release()


def test_cleanup_requires_owner_and_valid_partial_metadata(tmp_path):
    unknown = tmp_path / "0001_iv_sweep.owner.partial.csv"
    unknown.write_text("unrelated data")
    os.utime(unknown, (0, 0))
    assert p.cleanup_stale_partials(tmp_path, 1) == []
    assert p.cleanup_stale_partials(tmp_path, 1, owner_uuid="owner") == []
    assert unknown.exists()
    with pytest.raises((ValueError, FileExistsError)):
        p.write_partial_csv(tmp_path, "0001_iv_sweep", "owner", metadata(), frame(), column_units=UNITS)
    assert unknown.read_text() == "unrelated data"


def test_invalid_partial_does_not_allocate_staging(tmp_path, monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("Staging allocated before metadata validation")
    monkeypatch.setattr(p, "create_staging_file", unexpected)
    with pytest.raises(ValueError):
        p.write_partial_csv(tmp_path, "0001_iv_sweep", "owner", {}, frame())
    assert list(tmp_path.iterdir()) == []


@pytest.mark.skipif(os.name != "nt", reason="Windows cross-volume simulation")
def test_cross_volume_bundle_reuses_owned_reservation(tmp_path, monkeypatch):
    reservation = p.reserve_candidate_filename(tmp_path, "iv_sweep", "owner")
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    source = source_dir / ".stage"
    source.write_text("CSV")
    rename = os.rename

    def cross_volume(src, dst):
        if Path(src) == source:
            exc = OSError("Cross volume")
            exc.winerror = 17
            raise exc
        return rename(src, dst)

    monkeypatch.setattr(os, "rename", cross_volume)
    published = p.publish_artifact_bundle(reservation, source, strict=False)
    assert published.read_text() == "CSV"
    assert not source.exists()
    assert not reservation.marker_path.exists()


def test_preflight_failure_releases_marker(tmp_path):
    reservation = p.reserve_candidate_filename(tmp_path, "iv_sweep", "owner")
    with pytest.raises(FileNotFoundError):
        p.publish_artifact_bundle(reservation, tmp_path / "missing")
    assert not reservation.marker_path.exists()


class DiskMeasurement(BaseMeasurement):
    def __init__(self, directory, abort=False, fail=False):
        super().__init__(output_dir=directory, measurement_schema="iv_sweep", column_units=UNITS)
        self.abort = abort
        self.fail = fail

    def _configure_instruments(self, request):
        pass

    def _capture_data(self, request, on_update=None):
        if self.abort:
            self.request_stop()
        if self.fail:
            self._raw_data = frame()
            raise RuntimeError("capture failed")
        return frame()

    def _safe_shutdown(self):
        return SafetyReport(status=SafetyStatus.SAFE)


@pytest.mark.parametrize("session", [False, True])
@pytest.mark.parametrize("abort", [False, True])
def test_engine_writes_real_completed_and_partial_files(tmp_path, session, abort):
    measurement = DiskMeasurement(tmp_path, abort=abort)
    if session:
        with measurement.session(save=True) as scope:
            scope.configure_instruments()
            scope.capture_data()
    else:
        measurement.run_experiment(save=True)
    path = measurement.partial_filename if abort else measurement.filename
    assert path and Path(path).is_file()
    meta, data, units = p.read_measurement_csv(path)
    assert meta["outcome"] == ("ABORTED" if abort else "COMPLETED")
    assert meta["partial"] is abort
    assert units == UNITS
    pd.testing.assert_frame_equal(data, frame())
    if abort:
        assert measurement.filename is None
    assert not list(tmp_path.glob("*.res"))


def test_engine_save_failure_reports_recovery_and_retains_memory(tmp_path, monkeypatch):
    measurement = DiskMeasurement(tmp_path)
    def fail(*args, **kwargs):
        raise OSError("Publication failed")
    monkeypatch.setattr(p, "atomic_publish_no_replace", fail)
    with pytest.raises(p.BundlePublishError):
        measurement.run_experiment(save=True)
    assert measurement.filename is None
    assert measurement.run_state == RunState.FAILED
    pd.testing.assert_frame_equal(measurement.raw_data, frame())
    assert measurement.recoverable_staging_paths
    assert all(Path(path).is_file() for path in measurement.recoverable_staging_paths)


def test_failed_acquisition_partial_has_failed_outcome(tmp_path):
    measurement = DiskMeasurement(tmp_path, fail=True)
    with pytest.raises(RuntimeError, match="capture failed"):
        measurement.run_experiment(save=True, save_partial=True)
    assert measurement.filename is None
    assert p.read_measurement_csv(measurement.partial_filename)[0]["outcome"] == "FAILED"


def test_engine_without_persistence_configuration_cannot_report_fake_save():
    measurement = DiskMeasurement(None)
    with pytest.raises(ValueError, match="Saving requires"):
        measurement.run_experiment(save=True)
    assert measurement.filename is None
    assert measurement.run_state == RunState.FAILED


def test_cleanup_cannot_remove_checkpoint_while_writer_holds_guard(tmp_path):
    path = p.write_partial_csv(tmp_path, "0001_iv_sweep", "owner", metadata(), frame(), column_units=UNITS)
    os.utime(path, (0, 0))
    with p._marker_guard(path) as locked:
        assert locked
        assert p.cleanup_stale_partials(tmp_path, 1, owner_uuid="owner") == []
    assert path.exists()
    assert p.cleanup_stale_partials(tmp_path, 1, owner_uuid="owner") == [path]


def test_rollback_retains_replaced_side_artifact(tmp_path, monkeypatch):
    reservation = p.reserve_candidate_filename(tmp_path, "iv_sweep", "owner")
    csv, raw = tmp_path / ".csv", tmp_path / ".raw"
    csv.write_text("CSV")
    raw.write_text("RAW")
    target = tmp_path / (reservation.candidate_basename + "_raw.dat")
    publish = p.atomic_publish_no_replace
    def fail_csv(source, destination, **kwargs):
        if destination == reservation.candidate_path:
            target.write_text("FOREIGN REPLACEMENT")
            raise OSError("CSV failure")
        return publish(source, destination, **kwargs)
    monkeypatch.setattr(p, "atomic_publish_no_replace", fail_csv)
    with pytest.raises(p.BundlePublishError) as error:
        p.publish_artifact_bundle(reservation, csv, [(raw, target)])
    assert target.read_text() == "FOREIGN REPLACEMENT"
    assert raw.read_text() == "RAW"
    assert error.value.orphan_cleanup_failures


def test_partial_replace_failure_reports_staging_and_preserves_old_checkpoint(tmp_path, monkeypatch):
    path = p.write_partial_csv(tmp_path, "0001_iv_sweep", "owner", metadata(), frame(), column_units=UNITS)
    before = path.read_bytes()
    def fail(*args):
        raise OSError("replace failed")
    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(OSError) as error:
        p.write_partial_csv(tmp_path, "0001_iv_sweep", "owner", metadata(), frame().iloc[:1], column_units=UNITS)
    assert path.read_bytes() == before
    recovered = error.value.recoverable_staging_paths
    assert len(recovered) == 1
    assert len(p.read_measurement_csv(recovered[0])[1]) == 1

# ============================================================================
# Part 5: Additional Metadata & Error Propagation Regressions
# ============================================================================

def regression_metadata():
    return dict(measurement_schema='iv_sweep', measurement_schema_version=1,
                run_id='00123', outcome='COMPLETED', partial=False,
                save_requested=True, column_units_json='{"voltage":"V"}')


@pytest.mark.parametrize('field', REQUIRED_METADATA_FIELDS)
@pytest.mark.parametrize('as_frame', [False, True])
def test_missing_metadata_fails_before_writing(field, as_frame):
    meta = regression_metadata()
    del meta[field]
    if as_frame:
        meta = pd.DataFrame([meta])
    stream = io.StringIO()
    with pytest.raises(ValueError, match='Missing required'):
        write_measurement_handle(stream, meta, pd.DataFrame({'voltage': [1.]}))
    assert stream.getvalue() == ''


def test_invalid_path_write_does_not_truncate_or_create_directories(tmp_path):
    existing = tmp_path / 'existing.csv'
    existing.write_text('original', encoding='utf-8')
    new = tmp_path / 'new' / 'invalid.csv'
    for path in (existing, new):
        with pytest.raises(ValueError):
            write_measurement_csv(path, {}, pd.DataFrame({'voltage': [1.]}))
    assert existing.read_text(encoding='utf-8') == 'original'
    assert not new.parent.exists()


@pytest.mark.parametrize('utility', [False, True])
def test_disk_sync_failure_propagates(tmp_path, utility):
    data = pd.DataFrame({'voltage': [1.]})
    error = OSError('disk synchronization failed')
    with patch('os.fsync', side_effect=error):
        with pytest.raises(OSError) as caught:
            if utility:
                metadata_and_data_to_csv(pd.DataFrame([regression_metadata()]), data, tmp_path / 'a.csv')
            else:
                write_measurement_csv(tmp_path / 'b.csv', regression_metadata(), data)
    assert caught.value is error


def test_fileno_io_failure_is_not_treated_as_memory_stream():
    class BrokenHandle(io.StringIO):
        def fileno(self):
            raise OSError('broken descriptor')
    with pytest.raises(OSError, match='broken descriptor'):
        write_measurement_handle(BrokenHandle(), regression_metadata(), pd.DataFrame({'voltage': [1.]}))


@pytest.mark.parametrize('as_frame', [False, True])
def test_missing_units_cell_can_be_filled_by_explicit_mapping(as_frame):
    meta = regression_metadata()
    meta['column_units_json'] = None
    stream = io.StringIO()
    write_measurement_handle(stream, pd.DataFrame([meta]) if as_frame else meta,
                             pd.DataFrame({'voltage': [1.]}), column_units={'voltage': 'V'})
    stream.seek(0)
    assert read_measurement_csv(stream)[2] == {'voltage': 'V'}


@pytest.mark.parametrize('note', ['first\nsecond', 'first\r\nsecond', 'a,"b"\n\n山田'])
def test_text_and_multiline_metadata_round_trip(tmp_path, note):
    meta = dict(regression_metadata(), note=note, sample='00007', operator='NA', label='False', empty='')
    data = pd.DataFrame({'voltage': [1., 2.]})
    stream = io.StringIO()
    write_measurement_handle(stream, meta, data)
    stream.seek(0)
    loaded, recovered, units = read_measurement_csv(stream)
    assert loaded == meta
    pd.testing.assert_frame_equal(recovered, data)
    assert units == {'voltage': 'V'}
    path = tmp_path / 'round_trip.csv'
    write_measurement_csv(path, meta, data)
    assert read_measurement_csv(path)[0] == meta


@pytest.mark.parametrize('units', ['{"voltage":12}', '{"voltage":{}}'])
def test_invalid_unit_values_rejected_before_write(units):
    stream = io.StringIO()
    with pytest.raises(TypeError):
        write_measurement_handle(stream, dict(regression_metadata(), column_units_json=units),
                                 pd.DataFrame({'voltage': [1.]}))
    assert stream.getvalue() == ''
