"""
Tests for Checkpoint 11b: Atomic No-Replace Publication.

Verifies:
- Atomic no-replace publication primitive (atomic_publish_no_replace) (Section 8.1 Rule 6 & 7).
- Rejection of pre-existing targets with FileExistsError without silent overwrite.
- Preservation of staging files on collision for data recovery (Section 8.3).
- Multiple simultaneous writers racing on the same target filename: exactly one winner, losers get FileExistsError, no file corruption.
- Safe staging in destination directory via tempfile.mkstemp() (Section 8.1 Rule 2).
- Clean recovery and cleanup: incomplete staging files cleaned up on write/sync failure; completed staging files preserved on publication collision.
- Strict mode failing clearly with UnsupportedFilesystemError when atomic no-replace is unavailable.
- Opt-in non-strict mode with collision-resistant fallback.
- Local NTFS atomic rename verification.
- Explicit opt-in SMB test gate (PIEC_TEST_SMB_PATH).
"""

from __future__ import annotations

import concurrent.futures
import io
import os
from pathlib import Path
import tempfile
from unittest.mock import patch
import uuid

import pandas as pd
import pytest

from piec.measurement.persistence import (
    AtomicPublishError,
    UnsupportedFilesystemError,
    _collision_resistant_publish,
    atomic_publish_measurement_csv,
    atomic_publish_no_replace,
    create_staging_file,
    read_measurement_csv,
    write_measurement_csv,
)


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
