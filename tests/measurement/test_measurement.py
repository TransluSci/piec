"""
Dynamic measurement contract and interface inspection tests.

Discovers all concrete BaseMeasurement subclasses, inspects their constructor
signatures to verify instrument dependencies derived dynamically from the
drivers category folders, and ensures standard lifecycle hooks and control
contracts are implemented without hardcoded setups, numbers, or options.
"""
from __future__ import annotations

import inspect
import types
import typing
from typing import Any, get_args, get_origin

import pytest

from piec.drivers.instrument import Instrument
from piec.measurement.base import BaseMeasurement
from tests.support.discovery import discover_measurement_classes

MEASUREMENT_CLASSES = discover_measurement_classes()


def is_instrument_type(annotation: Any) -> bool:
    """Check if a type annotation represents an Instrument or subclass of Instrument."""
    if annotation is None or annotation is inspect.Parameter.empty or annotation is Any:
        return False
    origin = get_origin(annotation)
    if origin in (typing.Union, types.UnionType):
        return any(is_instrument_type(arg) for arg in get_args(annotation))
    return inspect.isclass(annotation) and issubclass(annotation, Instrument)


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
        """Verify through type inspection that measurement constructor declares at least one Instrument parameter."""
        sig = inspect.signature(meas_cls.__init__)
        params = list(sig.parameters.values())[1:]  # Skip 'self'
        assert len(params) >= 1, f"{name}.__init__ must take parameters"

        type_hints = typing.get_type_hints(meas_cls.__init__)
        instrument_params = [
            p.name for p in params
            if is_instrument_type(type_hints.get(p.name, p.annotation))
        ]
        assert len(instrument_params) >= 1, (
            f"{name}.__init__ must declare at least one parameter typed as an Instrument subclass "
            f"(found parameters: {[p.name for p in params]}, annotations: {type_hints})"
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
