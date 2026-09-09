"""
Tests for Checkpoint 11c: Bundles, Partials, and Recovery.

Verifies:
- Candidate filename reservation grammar {index}_{measurement_schema}.csv and marker ownership (Section 8.1 Rule 5).
- Reservation marker stores full owner UUID; never reserves by creating empty completed-looking CSV.
- Multi-threaded candidate reservation race condition resistance.
- Stale marker age-gated recovery.
- Multi-artifact bundle publication: side artifacts published first, completed CSV published last (Section 8.2).
- Never overwrite existing side artifacts; clean rollback on failure removing only current reservation artifacts.
- In-progress checkpoints and terminal partial CSVs using full-run-ID .partial.csv grammar (Section 8.3).
- Safe intentional overwrite of checkpoints owned by the same run.
- Completed CSV identification ignoring partial, temporary, and marker files (Section 8.1 Rule 9).
- Explicit, ownership-checked, age-gated stale reservation and partial cleanup.
"""

from __future__ import annotations

import concurrent.futures
import io
import os
from pathlib import Path
import time
from unittest.mock import patch

import pandas as pd
import pytest

from piec.measurement.persistence import (
    AtomicPublishError,
    BundlePublishError,
    CandidateReservation,
    cleanup_stale_partials,
    cleanup_stale_reservations,
    create_staging_file,
    is_completed_measurement_file,
    publish_artifact_bundle,
    read_measurement_csv,
    reserve_candidate_filename,
    write_measurement_handle,
    write_partial_csv,
)


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
            tmp_path, "iv_sweep", "active-run", stale_age_seconds=600
        )
        # Reclaimed stale candidate 0001
        assert res.index == 1
        assert res.candidate_path.name == "0001_iv_sweep.csv"
        content = res.marker_path.read_text(encoding="utf-8")
        assert "owner_uuid=active-run" in content
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

        cleaned = cleanup_stale_reservations(tmp_path, max_age_seconds=3600)
        assert stale_marker in cleaned
        assert not stale_marker.exists()
        assert active_marker.exists()
        assert regular_file.exists()

    def test_cleanup_stale_partials(self, tmp_path):
        """Explicit, age-gated partial file cleanup."""
        # Create a partial file
        partial_file = tmp_path / "0001_iv_sweep.old-run.partial.csv"
        partial_file.write_text("partial data", encoding="utf-8")

        # Backdate its mtime
        old_time = time.time() - 10000
        os.utime(partial_file, (old_time, old_time))

        # Recent partial file
        recent_partial = tmp_path / "0002_iv_sweep.new-run.partial.csv"
        recent_partial.write_text("recent data", encoding="utf-8")

        cleaned = cleanup_stale_partials(tmp_path, max_age_seconds=3600)
        assert partial_file in cleaned
        assert not partial_file.exists()
        assert recent_partial.exists()
