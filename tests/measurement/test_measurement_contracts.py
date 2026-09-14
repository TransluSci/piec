"""
Dynamic measurement contract and interface inspection tests.

Discovers all concrete BaseMeasurement subclasses, inspects their signatures
and lifecycle contracts, and validates that running each measurement with
virtual instruments produces compliant pandas DataFrames without relying
on brittle numerical math formulas.
"""
from __future__ import annotations

import inspect
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from piec.measurement.base import BaseMeasurement
from piec.measurement.contracts import RunState, SafetyStatus
from piec.measurement.persistence import read_measurement_csv
from tests.support.discovery import (
    assert_all_measurements_registered,
    discover_measurement_classes,
)
from tests.support.measurement_cases import MEASUREMENT_CASES

MEASUREMENT_CLASSES = discover_measurement_classes()
CASE_BY_NAME = {case.name: case for case in MEASUREMENT_CASES}

KNOWN_INSTRUMENT_PARAM_KEYS = {
    "sourcemeter", "source", "sm", "meter", "awg", "osc",
    "oscilloscope", "dmm", "lockin", "stepper", "motor",
    "arduino", "calibrator", "daq", "pulser", "profile",
}


def test_all_discovered_measurements_have_cases():
    """Ensure every discovered BaseMeasurement has an executable test case."""
    assert_all_measurements_registered({case.cls for case in MEASUREMENT_CASES})


@pytest.mark.parametrize("name,meas_cls", sorted(MEASUREMENT_CLASSES.items()))
class TestMeasurementContractInspection:
    """Inspects class definitions, constructor signatures, and lifecycle contracts."""

    def test_inherits_base_measurement(self, name: str, meas_cls: type[BaseMeasurement]):
        """Verify dynamic discovery finds concrete subclasses of BaseMeasurement."""
        assert issubclass(meas_cls, BaseMeasurement), f"{name} must inherit BaseMeasurement"
        assert not inspect.isabstract(meas_cls), f"{name} must not be an abstract class"

    def test_constructor_signature_accepts_instruments(self, name: str, meas_cls: type[BaseMeasurement]):
        """Verify through inspection that measurement constructor accepts instrument dependencies."""
        sig = inspect.signature(meas_cls.__init__)
        params = list(sig.parameters.values())[1:]  # Skip 'self'
        assert len(params) >= 1, f"{name}.__init__ must take parameters"

        param_names = {p.name.lower() for p in params}
        has_instrument_param = any(
            any(inst in p_name for inst in KNOWN_INSTRUMENT_PARAM_KEYS)
            for p_name in param_names
        )
        assert has_instrument_param, (
            f"{name}.__init__ parameters {sorted(param_names)} must include at least one "
            f"instrument dependency (e.g., sourcemeter, awg, osc, dmm, lockin, stepper, etc.)"
        )

    def test_implements_required_lifecycle_hooks(self, name: str, meas_cls: type[BaseMeasurement]):
        """Verify that concrete measurement implements internal lifecycle contracts."""
        for hook_name in ("_configure_instruments", "_capture_data", "_safe_shutdown"):
            assert hasattr(meas_cls, hook_name), f"{name} missing lifecycle hook {hook_name}"
            hook = getattr(meas_cls, hook_name)
            assert callable(hook), f"{name}.{hook_name} must be callable"

    def test_implements_public_control_contract(self, name: str, meas_cls: type[BaseMeasurement]):
        """Verify standard public lifecycle controls: run_experiment, request_stop, _reserve."""
        for method_name in ("run_experiment", "request_stop", "_reserve"):
            assert hasattr(meas_cls, method_name), f"{name} missing control method {method_name}"
            assert callable(getattr(meas_cls, method_name))

    def test_execution_returns_valid_dataframe_format(self, name: str, meas_cls: type[BaseMeasurement], monkeypatch):
        """Verify that running experiment dynamically returns a non-empty DataFrame with proper format."""
        assert name in CASE_BY_NAME, f"Missing case for {name}"
        case = CASE_BY_NAME[name]
        instruments, calls, construct = case.build(monkeypatch)
        meas = construct()

        df = meas.run_experiment(save=False)

        # Type validation: Must return a pandas DataFrame
        assert isinstance(df, pd.DataFrame), f"{name} must return a pandas DataFrame, got {type(df)}"
        assert not df.empty, f"{name} returned an empty DataFrame"

        # Schema & columns validation: Column names must match declared units schema
        assert set(df.columns) == set(case.units.keys()), (
            f"{name} columns {list(df.columns)} do not match expected schema units {list(case.units.keys())}"
        )
        assert meas.column_units == case.units

        # Data format validation: All columns must be numeric, and all values finite (no NaN, no Inf)
        for col in df.columns:
            assert pd.api.types.is_numeric_dtype(df[col].dtype), (
                f"{name} column '{col}' has non-numeric dtype {df[col].dtype}"
            )
        assert np.isfinite(df.to_numpy()).all(), f"{name} returned non-finite values (NaN or Inf)"

        # State & Safety contract
        assert meas.run_state == RunState.COMPLETED
        assert meas.safety_status == SafetyStatus.SAFE
        case.assert_safe(instruments, calls)

    def test_saved_output_obeys_piec_csv_layout(self, name: str, meas_cls: type[BaseMeasurement], monkeypatch, tmp_path):
        """Verify saved measurement adheres to PIEC 1-row metadata and tabular format without data corruption."""
        assert name in CASE_BY_NAME, f"Missing case for {name}"
        case = CASE_BY_NAME[name]
        instruments, calls, construct = case.build(monkeypatch)
        meas = construct()
        meas.output_dir = tmp_path

        df = meas.run_experiment(save=True)

        assert meas.filename is not None
        file_path = Path(meas.filename)
        assert file_path.is_file(), f"Output file {file_path} was not created"

        # Layout validation: Line 1 metadata, line 2 headers, line 3 blank separator
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        assert len(lines) >= 3, f"{file_path} is too short to be a valid PIEC CSV file"
        assert lines[2].strip() == "", f"Line 3 of {file_path} must be blank separator line"

        # Roundtrip reader validation
        meta, saved_df, units = read_measurement_csv(file_path)
        assert isinstance(saved_df, pd.DataFrame)
        assert len(saved_df) == len(df)
        assert list(saved_df.columns) == list(df.columns)
        assert units == case.units
        assert meta["measurement_schema"] == case.schema
        assert meas.safety_status == SafetyStatus.SAFE
        case.assert_safe(instruments, calls)
