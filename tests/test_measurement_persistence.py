"""
Tests for Checkpoint 11a: Handle Writer and Schema Metadata.

Verifies:
- One-row metadata, blank separator, and data table CSV layout (Section 7.1 & 8.1).
- Single UTF-8 text handle writer with flush and fsync (Section 8.1 Rule 3 & 4).
- Exact JSON unit round trips via compact sorted column_units_json (Section 7.1).
- Unitless fields with null / None representation (Section 7.1).
- Non-ASCII and Unicode metadata round-trip preservation (Section 8.4).
- Reader helper (read_measurement_csv) recovering metadata, data table, and unit mapping.
- Validation of column units matching data columns without omission (Section 7.1).
- Utilities helper (metadata_and_data_to_csv) writing through single handle.
"""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
from typing import Dict, Optional
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd
import pytest

from piec.analysis.utilities import metadata_and_data_to_csv
from piec.measurement import (
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


# ============================================================================
# 1. Exact JSON Unit Round Trips (Section 7.1)
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
