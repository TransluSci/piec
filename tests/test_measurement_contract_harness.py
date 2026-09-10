"""Regression tests for reference/target selection and scientific comparisons."""
import copy
import json
import subprocess

import pandas as pd
import pytest

from tests.fixtures.measurement_compatibility import harness as h


@pytest.mark.parametrize("side", ["actual", "reference"])
def test_missing_iv_current_fails(side):
    actual = pd.DataFrame({"voltage": [0., 1.], "current": [0., .01]})
    reference = actual.rename(columns={"voltage": "voltage (V)", "current": "current (A)"})
    if side == "actual":
        actual = actual.drop(columns="current")
    else:
        reference = reference.drop(columns="current (A)")
    with pytest.raises(AssertionError, match=f"Missing {side} column: current"):
        h.assert_numerical_data_matches_reference(actual, reference, "IVSweep")


@pytest.mark.parametrize("family", ["DiscreteWaveform", "HysteresisLoop", "ThreePulsePund"])
def test_waveform_timing_including_pretrigger_is_scientific(family):
    reference = pd.DataFrame({"time (s)": [-1e-6, 0., 1e-6], "voltage (V)": [0., 1., 0.]})
    actual = reference.rename(columns={"time (s)": "time", "voltage (V)": "voltage"})
    h.assert_numerical_data_matches_reference(actual, reference, family, view="raw")
    actual["time"] *= 1000
    with pytest.raises(AssertionError, match="Numerical mismatch"):
        h.assert_numerical_data_matches_reference(actual, reference, family, view="raw")


def test_processed_fe_requires_polarization_not_just_raw_columns():
    data = pd.DataFrame({"time": [0.], "voltage": [1.]})
    with pytest.raises(AssertionError, match="Missing actual column: current"):
        h.assert_numerical_data_matches_reference(data, data, "HysteresisLoop")


def moke_data():
    return pd.DataFrame({
        "time": [0., 1.], "cycle": [0, 0], "point": [0, 1], "direction": [1, 1],
        "source_output": [0., 1.], "field_calibrated": [0., 100.], "detector_voltage": [.5, .6],
    })


@pytest.mark.parametrize("output_unit,field_unit", [("V", "Oe"), ("A", "T")])
def test_moke_reference_unit_headers_resolve_and_elapsed_time_can_vary(output_unit, field_unit):
    actual = moke_data()
    reference = actual.rename(columns={
        "time": "time (s)", "source_output": f"source_output ({output_unit})",
        "field_calibrated": f"field_calibrated ({field_unit})", "detector_voltage": "detector_voltage (V)",
    })
    actual["time"] = [0., 2.]
    h.assert_numerical_data_matches_reference(actual, reference, "MokeMeasurement")


@pytest.mark.parametrize("column", ["field_measured", "field_time"])
@pytest.mark.parametrize("side", ["actual", "reference"])
def test_optional_moke_columns_cannot_disappear_on_one_side(column, side):
    actual = moke_data()
    actual["field_measured"] = [0., 99.]
    actual["field_time"] = [.1, 1.1]
    reference = actual.copy()
    if side == "actual":
        actual = actual.drop(columns=column)
    else:
        reference = reference.drop(columns=column)
    with pytest.raises(AssertionError, match=f"Missing {side} column"):
        h.assert_numerical_data_matches_reference(actual, reference, "MokeMeasurement")


@pytest.mark.parametrize("times", [[0., -1.], [0., float("nan")], [1., 0.]])
def test_elapsed_moke_clocks_still_validated(times):
    reference = moke_data()
    actual = reference.copy()
    actual["time"] = times
    with pytest.raises(AssertionError, match="elapsed time"):
        h.assert_numerical_data_matches_reference(actual, reference, "MokeMeasurement")


def test_golden_waveform_time_is_compared_by_default(tmp_path):
    from piec.analysis.utilities import metadata_and_data_to_csv
    metadata = pd.DataFrame([{"measurement_schema": "discrete_waveform"}])
    data = pd.DataFrame({"time": [-1e-6, 0., 1e-6], "voltage": [0., 1., 0.]})
    reference = tmp_path / "reference.csv"
    actual = tmp_path / "actual.csv"
    metadata_and_data_to_csv(metadata, data, reference)
    metadata_and_data_to_csv(metadata, data, actual)
    h.assert_golden_csv_matches(actual, reference)
    data["time"] *= 2  # Microsecond-scale regressions must not hide under voltage tolerances.
    metadata_and_data_to_csv(metadata, data, actual)
    with pytest.raises(AssertionError, match="Data mismatch"):
        h.assert_golden_csv_matches(actual, reference)


def test_moke_reference_is_from_committed_prototype():
    original = json.loads(subprocess.check_output([
        "git", "show", "69548ab:tests/fixtures/measurement_compatibility/manifest.json",
    ], text=True))["families"]["MokeMeasurement"]
    reference = h.get_family_reference_observations("MokeMeasurement")
    for key in ("constructor", "properties", "data_columns"):
        assert reference[key] == original[key]


class TargetMeasurement:
    def __init__(self, sourcemeter, *, gain=1): pass
    def run_experiment(self, *, on_update=None, save=True, save_partial=None, options=None):
        return pd.DataFrame()
    def configure_instruments(self): pass
    def capture_data(self, *, on_update=None): pass
    def session(self, *, save=False, save_partial=None, options=None): pass
    def safe_shutdown(self): pass
    def request_stop(self): pass
    def request_pause(self, paused=True): pass
    def snapshot(self): pass


def test_migration_switch_selects_target_instead_of_old_signature(monkeypatch):
    manifest = copy.deepcopy(h.load_manifest())
    manifest["migrated_families"] = []
    monkeypatch.setattr(h, "load_manifest", lambda: manifest)
    # No construction or hardware calls; validate the selector structurally.
    with pytest.raises(AssertionError):
        h.assert_family_interface(TargetMeasurement, "IVSweep")
    manifest["migrated_families"] = ["IVSweep"]
    h.assert_family_interface(TargetMeasurement, "IVSweep")
    assert h.is_family_migrated("IVSweep")


@pytest.mark.parametrize("signature", [
    "self, save=True",  # positional options
    "self, *, on_update=None, save=False, save_partial=None, options=None",  # wrong default
    "self, *, on_update=None, save=True, save_partial=None",  # missing options
])
def test_migrated_runner_rejects_nonstandard_signatures(monkeypatch, signature):
    manifest = copy.deepcopy(h.load_manifest())
    manifest["migrated_families"] = ["IVSweep"]
    monkeypatch.setattr(h, "load_manifest", lambda: manifest)
    namespace = {}
    exec(f"def run_experiment({signature}): pass", namespace)
    cls = type("InvalidTarget", (TargetMeasurement,), namespace)
    with pytest.raises(AssertionError):
        h.assert_family_interface(cls, "IVSweep")


def test_migrated_constructor_rejects_positional_settings(monkeypatch):
    manifest = copy.deepcopy(h.load_manifest())
    manifest["migrated_families"] = ["IVSweep"]
    monkeypatch.setattr(h, "load_manifest", lambda: manifest)
    class BadSettings(TargetMeasurement):
        def __init__(self, sourcemeter, gain=1): pass
    with pytest.raises(AssertionError, match="keyword-only"):
        h.assert_family_interface(BadSettings, "IVSweep")
