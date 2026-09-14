"""
Dynamic measurement contract and interface inspection tests.

Discovers all concrete BaseMeasurement subclasses, inspects their constructor
signatures to verify instrument dependencies, and ensures standard lifecycle
hooks and control contracts are implemented without hardcoded setups or options.
"""
from __future__ import annotations

import inspect

import pytest

from piec.measurement.base import BaseMeasurement
from tests.support.discovery import discover_measurement_classes

MEASUREMENT_CLASSES = discover_measurement_classes()

KNOWN_INSTRUMENT_PARAM_KEYS = {
    "sourcemeter", "source", "sm", "meter", "awg", "osc",
    "oscilloscope", "dmm", "lockin", "stepper", "motor",
    "arduino", "calibrator", "daq", "pulser", "profile",
}


def test_concrete_measurements_discovered():
    """Ensure dynamic discovery successfully finds concrete BaseMeasurement classes."""
    assert len(MEASUREMENT_CLASSES) > 0, "No concrete BaseMeasurement classes discovered"


@pytest.mark.parametrize("name,meas_cls", sorted(MEASUREMENT_CLASSES.items()))
class TestMeasurementDynamicContracts:
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
