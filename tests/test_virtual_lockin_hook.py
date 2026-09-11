"""
Tests for VirtualLockin generic per-instance virtual hooks (Checkpoint 28a).

Validates:
- Generic per-instance hook injection (xy_reader and transport_hook);
- Explicit injection precedence over deprecated global sample fallback;
- Material-specific logic kept strictly outside generic driver;
- Explicit excitation current settings and forwarding;
- Plain 2-tuple (X, Y) voltage responses without compatibility wrappers;
- Declared physical units;
- Deterministic reset behavior preserving hooks;
- Strict response validation and error handling.
"""

from __future__ import annotations

import math
from typing import Tuple

import numpy as np
import pytest

from piec.drivers.lockin.virtual_lockin import VirtualLockin
from piec.simulation.magnetic_material import MagneticSample


class TestVirtualLockinHookInjection:
    """Validation of hook injection, aliases, and properties."""

    def test_constructor_accepts_xy_reader(self):
        hook = lambda: (0.1, 0.02)
        lockin = VirtualLockin(xy_reader=hook)
        assert lockin.xy_reader is hook
        assert lockin.transport_hook is hook

    def test_constructor_accepts_transport_hook_alias(self):
        hook = lambda: (0.05, 0.001)
        lockin = VirtualLockin(transport_hook=hook)
        assert lockin.xy_reader is hook
        assert lockin.transport_hook is hook

    def test_constructor_identical_hooks_accepted(self):
        hook = lambda: (0.05, 0.001)
        lockin = VirtualLockin(xy_reader=hook, transport_hook=hook)
        assert lockin.xy_reader is hook

    def test_constructor_conflicting_hooks_rejected(self):
        hook1 = lambda: (0.1, 0.0)
        hook2 = lambda: (0.2, 0.0)
        with pytest.raises(ValueError, match="Cannot specify both"):
            VirtualLockin(xy_reader=hook1, transport_hook=hook2)

    def test_constructor_rejects_non_callable_hook(self):
        with pytest.raises(TypeError, match="xy_reader must be callable or None"):
            VirtualLockin(xy_reader="not_a_callable")

    def test_method_and_property_injection(self):
        lockin = VirtualLockin()
        assert lockin.xy_reader is None

        hook1 = lambda: (0.01, 0.002)
        lockin.set_xy_reader(hook1)
        assert lockin.xy_reader is hook1

        hook2 = lambda: (0.02, 0.004)
        lockin.set_transport_hook(hook2)
        assert lockin.xy_reader is hook2

        hook3 = lambda: (0.03, 0.006)
        lockin.xy_reader = hook3
        assert lockin.xy_reader is hook3

        hook4 = lambda: (0.04, 0.008)
        lockin.transport_hook = hook4
        assert lockin.transport_hook is hook4

        lockin.set_xy_reader(None)
        assert lockin.xy_reader is None

    def test_injection_rejects_non_callable(self):
        lockin = VirtualLockin()
        with pytest.raises(TypeError, match="xy_reader must be callable or None"):
            lockin.set_xy_reader(12345)
        with pytest.raises(TypeError, match="xy_reader must be callable or None"):
            lockin.xy_reader = [1, 2]


class TestPrecedenceAndDecoupling:
    """Precedence of explicit injection over global fallback and material decoupling."""

    def test_explicit_injection_takes_precedence_over_mag_sample(self):
        class DeterministicSample:
            def get_voltage_response(self, *, excitation_current):
                return (100.0 * excitation_current, 0.0)

        sample = DeterministicSample()
        lockin = VirtualLockin(excitation_current=1e-3)
        lockin.mag_sample = sample

        # Without hook: uses fallback sample
        fallback_read = lockin.quick_read()
        assert fallback_read == (0.1, 0.0)

        # Inject explicit hook: must take precedence
        hook_resp = (0.987, -0.123)
        lockin.set_xy_reader(lambda: hook_resp)
        assert lockin.quick_read() == hook_resp
        assert lockin.get_X() == 0.987
        assert lockin.get_Y() == -0.123
        assert lockin.read_data()["X"] == 0.987
        assert lockin.read_data()["Y"] == -0.123

        # Clear hook: falls back to sample again
        lockin.set_xy_reader(None)
        assert lockin.quick_read() == (0.1, 0.0)

    def test_material_logic_remains_outside_generic_driver(self):
        """VirtualLockin does not compute AMR or know about angle/field; hook handles it."""
        sample = MagneticSample(r_base=200.0, amr_ratio=0.05, seed=123)
        sample.current_angle = 0.0
        sample.current_field = 100.0

        # Create hook that queries material
        def material_hook(excitation_current=1e-3):
            return sample.get_voltage_response(excitation_current=excitation_current)

        lockin = VirtualLockin(excitation_current=1e-3, xy_reader=material_hook)
        x0, y0 = lockin.quick_read()
        # R_base is 200, at angle 0 R ≈ 200 * 1.05 = 210, so X ≈ 0.21 V with 1e-3 A
        assert x0 == pytest.approx(0.21, rel=1e-3)
        assert y0 == 0.0

        # Rotate sample angle externally — driver sees updated voltages via hook
        sample.current_angle = 90.0
        x90, y90 = lockin.quick_read()
        # At angle 90 R ≈ 200, so X ≈ 0.20 V with 1e-3 A
        assert x90 == pytest.approx(0.20, rel=1e-3)
        assert x90 < x0

    def test_default_fallback_without_mag_sample(self):
        lockin = VirtualLockin()
        lockin.mag_sample = None
        assert lockin.quick_read() == (0.0001, 0.0002)


class TestExcitationForwardingAndUnits:
    """Explicit excitation current handling, declared units, and response types."""

    def test_hook_receives_declared_excitation_current_keyword(self):
        received_currents = []

        def kw_hook(*, excitation_current):
            received_currents.append(excitation_current)
            return (excitation_current * 50.0, 0.0)

        lockin = VirtualLockin(excitation_current=0.002, xy_reader=kw_hook)
        x, y = lockin.quick_read()
        assert received_currents == [0.002]
        assert x == pytest.approx(0.1)

    def test_hook_receives_declared_excitation_current_positional(self):
        received_currents = []

        def pos_hook(current):
            received_currents.append(current)
            return (current * 100.0, 0.0)

        lockin = VirtualLockin(excitation_current=0.005, xy_reader=pos_hook)
        x, y = lockin.quick_read()
        assert received_currents == [0.005]
        assert x == pytest.approx(0.5)

    def test_hook_without_arguments_called_cleanly(self):
        call_count = [0]

        def zero_arg_hook():
            call_count[0] += 1
            return (0.015, -0.002)

        lockin = VirtualLockin(xy_reader=zero_arg_hook)
        x, y = lockin.quick_read()
        assert call_count[0] == 1
        assert (x, y) == (0.015, -0.002)

    def test_plain_tuple_response_no_compatibility_wrapper(self):
        lockin = VirtualLockin(xy_reader=lambda: (0.1, 0.02))
        resp = lockin.quick_read()

        assert type(resp) is tuple
        assert len(resp) == 2
        assert not isinstance(resp, float)
        assert isinstance(resp[0], float)
        assert isinstance(resp[1], float)

    def test_declared_units(self):
        lockin = VirtualLockin()
        units = lockin.declared_units
        assert units["x"] == "V"
        assert units["y"] == "V"
        assert units["excitation_current"] == "A"


class TestDeterministicResetAndState:
    """Reset restoration and state isolation."""

    def test_reset_restores_initial_excitation_and_preserves_hook(self):
        hook = lambda: (0.03, 0.001)
        lockin = VirtualLockin(excitation_current=0.005, xy_reader=hook)
        assert lockin.excitation_current == 0.005

        # Mutate excitation and state
        lockin.excitation_current = 0.02
        lockin.configure_reference(voltage=3.5, frequency=5000.0)
        assert lockin.get_amplitude() == 3.5
        assert lockin.get_frequency() == 5000.0

        # Reset
        lockin.reset()
        assert lockin.excitation_current == 0.005
        assert lockin.get_amplitude() == 0.0
        assert lockin.get_frequency() == 1000.0
        assert lockin.xy_reader is hook
        assert lockin.quick_read() == (0.03, 0.001)

    def test_setters_and_getters(self):
        lockin = VirtualLockin()
        lockin.set_amplitude(2.5)
        assert lockin.get_amplitude() == 2.5

        lockin.set_frequency(2500.0)
        assert lockin.get_frequency() == 2500.0

        with pytest.raises(ValueError):
            lockin.set_amplitude(float("nan"))
        with pytest.raises(ValueError):
            lockin.set_frequency(-10.0)

    def test_clear_is_safe_noop(self):
        lockin = VirtualLockin()
        lockin.clear()  # Should not raise


class TestResponseValidationAndErrors:
    """Validation of hook returns and constructor parameters."""

    def test_constructor_excitation_validation(self):
        for invalid in [float("nan"), float("inf")]:
            with pytest.raises(ValueError):
                VirtualLockin(excitation_current=invalid)

    @pytest.mark.parametrize("bad_return", [
        None,
        42.0,
        "string",
        (1.0,),
        (1.0, 2.0, 3.0),
        ("not_a_number", 0.0),
        (float("nan"), 0.0),
        (0.0, float("inf")),
    ])
    def test_invalid_hook_returns_rejected(self, bad_return):
        lockin = VirtualLockin(xy_reader=lambda: bad_return)
        with pytest.raises((TypeError, ValueError)):
            lockin.quick_read()


@pytest.mark.parametrize("error_type", [RuntimeError, TypeError])
def test_positional_hook_error_is_preserved_and_not_retried(error_type):
    calls = []
    error = error_type("failure inside hook")
    def reader(current):
        calls.append(current)
        raise error
    lockin = VirtualLockin(xy_reader=reader)
    with pytest.raises(error_type) as result:
        lockin.quick_read()
    assert result.value is error
    assert calls == [lockin.excitation_current]


def test_positional_only_current_and_optional_current_are_forwarded():
    def reader(excitation_current, /):
        return (excitation_current, 0)
    lockin = VirtualLockin(excitation_current=0.002, xy_reader=reader)
    assert lockin.quick_read() == (0.002, 0)
    lockin.xy_reader = lambda current=42: (current, 0)
    assert lockin.quick_read() == (0.002, 0)


def test_zero_and_signed_excitation_validate_assignments_and_reset():
    lockin = VirtualLockin(excitation_current=0, xy_reader=lambda current: (100 * current, 0))
    assert lockin.quick_read() == (0, 0)
    lockin.excitation_current = -0.001
    assert lockin.quick_read() == (-0.1, 0)
    for invalid in (float("nan"), float("inf")):
        with pytest.raises(ValueError):
            lockin.excitation_current = invalid
        assert lockin.excitation_current == -0.001
    lockin.reset()
    assert lockin.quick_read() == (0, 0)


@pytest.mark.parametrize("settings", [
    {"voltage": float("nan")}, {"voltage": -1},
    {"frequency": 0}, {"frequency": float("inf")},
    {"source": "invalid"}, {"phase": float("nan")},
])
def test_reference_configuration_validates_before_updating(settings):
    lockin = VirtualLockin()
    before = lockin.get_state()
    with pytest.raises(ValueError):
        lockin.configure_reference(**({"voltage": 2} | settings))
    assert lockin.get_state() == before


@pytest.mark.parametrize("xy,angle", [((0, 1), 90), ((-1, 1), 135), ((1, -1), -45)])
def test_read_data_phase_agrees_with_xy(xy, angle):
    lockin = VirtualLockin(xy_reader=lambda: xy)
    assert lockin.read_data()["Theta"] == pytest.approx(angle)


def test_hook_and_sample_assignment_are_isolated_from_other_instances(monkeypatch):
    from piec.drivers.virtual_instrument import VirtualInstrument
    class Sample:
        def get_voltage_response(self, *, excitation_current):
            return (excitation_current, 0)
    shared = Sample()
    monkeypatch.setattr(VirtualInstrument, "_shared_mag_sample", shared)
    first, second = VirtualLockin(), VirtualLockin()
    assert first.mag_sample is second.mag_sample is shared
    first.mag_sample = None
    first.xy_reader = lambda: (2, 3)
    first.reset()
    assert first.quick_read() == (2, 3)
    assert second.quick_read() == (second.excitation_current, 0)
    assert VirtualInstrument._shared_mag_sample is shared
    del first.mag_sample
    first.xy_reader = None
    assert first.mag_sample is shared


def test_hook_precedence_does_not_access_fallback_property():
    class HookOnly(VirtualLockin):
        @property
        def mag_sample(self):
            raise AssertionError("fallback must not be accessed")
    assert HookOnly(xy_reader=lambda: (1, 2)).quick_read() == (1, 2)


@pytest.mark.parametrize("value", [np.array(1), np.ones((2, 1)), np.ones((2, 2))])
def test_response_rejects_non_vector_arrays(value):
    with pytest.raises((TypeError, ValueError)):
        VirtualLockin(xy_reader=lambda: value).quick_read()

def test_hook_exception_propagates_cleanly():
    def failing_hook():
        raise RuntimeError("Hardware communication timeout in hook")

    lockin = VirtualLockin(xy_reader=failing_hook)
    with pytest.raises(RuntimeError, match="Hardware communication timeout"):
        lockin.quick_read()
