"""Failure and ownership regressions for the shared persistence engine."""
import os
from pathlib import Path

import pandas as pd
import pytest

from piec.measurement import BaseMeasurement, RunState, SafetyReport, SafetyStatus
from piec.measurement import persistence as p


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
