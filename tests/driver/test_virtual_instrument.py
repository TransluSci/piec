"""
Tests for shared virtual instrument behavior and generic hook contracts.

Consolidates repeated virtual hook assertions across all 7 virtual drivers:
- VirtualAwg
- VirtualScope
- VirtualSourcemeter
- VirtualDMM
- VirtualLockin
- VirtualStepper
- VirtualCalibrator

Also covers VirtualInstrument base simulation policies, material decoupling,
and cross-virtual waveform regressions.
"""

from __future__ import annotations

import math
import warnings
from typing import Any, Callable, Dict, List, Mapping, NamedTuple, Type
from unittest.mock import MagicMock
import numpy as np
import pytest

from piec.drivers.virtual_instrument import (
    VirtualInstrument,
    coerce_simulation_points,
    warn_for_large_simulation_input,
    warn_for_large_simulation_points,
)
from piec.drivers.awg.virtual_awg import VirtualAwg
from piec.drivers.oscilloscope.virtual_oscilloscope import VirtualScope
from piec.drivers.sourcemeter.virtual_sourcemeter import VirtualSourcemeter
from piec.drivers.dmm.virtual_dmm import VirtualDMM
from piec.drivers.lockin.virtual_lockin import VirtualLockin
from piec.drivers.stepper_motor.virtual_stepper import VirtualStepper
from piec.drivers.dc_calibrator.virtual_calibrator import VirtualCalibrator
from piec.simulation.fe_material import Ferroelectric
from piec.simulation.magnetic_material import MagneticSample


# ============================================================================
# 1. VirtualInstrument Base Class & Simulation Policies
# ============================================================================

class TestVirtualInstrumentBase:
    """Test shared base properties, simulation point coercion, and policy warnings."""

    def test_shared_samples_initialized(self):
        vi = VirtualInstrument()
        assert vi.sample is not None
        assert isinstance(vi.sample, Ferroelectric)
        assert vi.mag_sample is not None
        assert isinstance(vi.mag_sample, MagneticSample)
        assert vi.virtual_sample is vi.sample

    def test_set_virtual_sample(self):
        old_sample = VirtualInstrument._shared_fe_sample
        new_sample = MagicMock(spec=Ferroelectric)
        try:
            VirtualInstrument.set_virtual_sample(new_sample)
            vi = VirtualInstrument()
            assert vi.sample is new_sample
        finally:
            VirtualInstrument.set_virtual_sample(old_sample)

    def test_coerce_simulation_points(self):
        assert coerce_simulation_points(None, default=5000) == 5000
        assert coerce_simulation_points(100, default=5000) == 100
        assert coerce_simulation_points(np.int64(250), default=5000) == 250

        with pytest.raises(TypeError, match="must be an integer"):
            coerce_simulation_points("invalid", default=5000)

        with pytest.raises(ValueError, match="must be at least 2"):
            coerce_simulation_points(1, default=5000)

        with pytest.raises(ValueError, match="must be at least 2"):
            coerce_simulation_points(0, default=5000)

    def test_warn_for_large_simulation_points(self):
        with pytest.warns(RuntimeWarning, match="exceeding the recommended"):
            warn_for_large_simulation_points(1_500_000, label="test data")

        # Below threshold should not warn
        with warnings.catch_warnings(record=True) as recorded:
            warnings.simplefilter("always")
            warn_for_large_simulation_points(100_000, label="test data")
            assert len(recorded) == 0

    def test_warn_for_large_simulation_input(self):
        large_list = [0] * (VirtualInstrument.SIMULATION_POINTS_WARNING_THRESHOLD + 10)
        with pytest.warns(RuntimeWarning, match="exceeding the recommended"):
            warn_for_large_simulation_input(large_list, label="synthetic input")

        small_list = [0, 1, 2]
        with warnings.catch_warnings(record=True) as recorded:
            warnings.simplefilter("always")
            warn_for_large_simulation_input(small_list, label="synthetic input")
            assert len(recorded) == 0


# ============================================================================
# 2. Reusable Generic Virtual Hook Adapter Specifications
# ============================================================================

class VirtualHookSpec(NamedTuple):
    name: str
    driver_class: Type[VirtualInstrument]
    primary_kwarg: str
    aliases: List[str]
    setter_name: str
    trigger_op: Callable[[Any], Any]
    valid_return: Any
    declared_units: Dict[str, str]
    fallback_attr: str


def _trigger_awg(inst: VirtualAwg):
    inst.create_arb_waveform(1, "test_arb", [0.0, 1.0])
    inst.set_arb_waveform(1, "test_arb")
    inst.output_trigger()


def _trigger_scope(inst: VirtualScope):
    return inst.get_data(1)


def _trigger_sourcemeter(inst: VirtualSourcemeter):
    inst.state["output_on"] = True
    return inst.get_voltage(1)


def _trigger_dmm(inst: VirtualDMM):
    return inst.get_voltage()


def _trigger_lockin(inst: VirtualLockin):
    return inst.quick_read()


def _trigger_stepper(inst: VirtualStepper):
    inst.step(10, 1)


def _trigger_calibrator(inst: VirtualCalibrator):
    inst.set_voltage(1.0)


HOOK_SPECS: List[VirtualHookSpec] = [
    VirtualHookSpec(
        name="VirtualAwg",
        driver_class=VirtualAwg,
        primary_kwarg="waveform_hook",
        aliases=["apply_hook", "trigger_hook"],
        setter_name="set_waveform_hook",
        trigger_op=_trigger_awg,
        valid_return=None,
        declared_units={"voltage": "V", "frequency": "Hz", "time": "s"},
        fallback_attr="sample",
    ),
    VirtualHookSpec(
        name="VirtualScope",
        driver_class=VirtualScope,
        primary_kwarg="waveform_hook",
        aliases=["channel_hook", "data_hook"],
        setter_name="set_waveform_hook",
        trigger_op=_trigger_scope,
        valid_return={"time": [0.0, 1e-6], "voltage": [1.0, 2.0]},
        declared_units={"voltage": "V", "time": "s"},
        fallback_attr="sample",
    ),
    VirtualHookSpec(
        name="VirtualSourcemeter",
        driver_class=VirtualSourcemeter,
        primary_kwarg="load_hook",
        aliases=["source_hook", "measure_hook", "transport_hook"],
        setter_name="set_load_hook",
        trigger_op=_trigger_sourcemeter,
        valid_return=(1.0, 0.001),
        declared_units={"voltage": "V", "current": "A"},
        fallback_attr="mag_sample",
    ),
    VirtualHookSpec(
        name="VirtualDMM",
        driver_class=VirtualDMM,
        primary_kwarg="voltage_reader",
        aliases=["reader_hook"],
        setter_name="set_voltage_reader",
        trigger_op=_trigger_dmm,
        valid_return=2.5,
        declared_units={"voltage": "V"},
        fallback_attr="mag_sample",
    ),
    VirtualHookSpec(
        name="VirtualLockin",
        driver_class=VirtualLockin,
        primary_kwarg="xy_reader",
        aliases=["transport_hook"],
        setter_name="set_xy_reader",
        trigger_op=_trigger_lockin,
        valid_return=(0.1, 0.02),
        declared_units={"x": "V", "y": "V", "excitation_current": "A"},
        fallback_attr="mag_sample",
    ),
    VirtualHookSpec(
        name="VirtualStepper",
        driver_class=VirtualStepper,
        primary_kwarg="angle_hook",
        aliases=["position_hook", "step_hook"],
        setter_name="set_angle_hook",
        trigger_op=_trigger_stepper,
        valid_return=None,
        declared_units={"angle": "deg", "position": "steps"},
        fallback_attr="mag_sample",
    ),
    VirtualHookSpec(
        name="VirtualCalibrator",
        driver_class=VirtualCalibrator,
        primary_kwarg="output_hook",
        aliases=["field_hook"],
        setter_name="set_output_hook",
        trigger_op=_trigger_calibrator,
        valid_return=None,
        declared_units={"voltage": "V", "current": "A"},
        fallback_attr="mag_sample",
    ),
]


# ============================================================================
# 3. Parametrized Common Virtual Hook Contract Tests
# ============================================================================

class TestCommonVirtualHookContract:
    """Parametrized suite verifying virtual hook rules across all 7 drivers."""

    @pytest.mark.parametrize("spec", HOOK_SPECS, ids=lambda s: s.name)
    def test_constructor_primary_injection(self, spec: VirtualHookSpec):
        hook = lambda *a, **k: spec.valid_return
        inst = spec.driver_class(**{spec.primary_kwarg: hook})
        assert getattr(inst, spec.primary_kwarg) is hook
        for alias in spec.aliases:
            assert getattr(inst, alias) is hook

    @pytest.mark.parametrize("spec", HOOK_SPECS, ids=lambda s: s.name)
    def test_constructor_alias_injection(self, spec: VirtualHookSpec):
        for alias in spec.aliases:
            hook = lambda *a, **k: spec.valid_return
            inst = spec.driver_class(**{alias: hook})
            assert getattr(inst, spec.primary_kwarg) is hook
            assert getattr(inst, alias) is hook

    @pytest.mark.parametrize("spec", HOOK_SPECS, ids=lambda s: s.name)
    def test_constructor_identical_aliases_accepted(self, spec: VirtualHookSpec):
        hook = lambda *a, **k: spec.valid_return
        kwargs = {spec.primary_kwarg: hook}
        for alias in spec.aliases:
            kwargs[alias] = hook
        inst = spec.driver_class(**kwargs)
        assert getattr(inst, spec.primary_kwarg) is hook

    @pytest.mark.parametrize("spec", HOOK_SPECS, ids=lambda s: s.name)
    def test_constructor_conflicting_aliases_rejected(self, spec: VirtualHookSpec):
        if not spec.aliases:
            pytest.skip("No aliases defined for this driver")
        hook1 = lambda *a, **k: spec.valid_return
        hook2 = lambda *a, **k: spec.valid_return
        kwargs = {spec.primary_kwarg: hook1, spec.aliases[0]: hook2}
        with pytest.raises(ValueError):
            spec.driver_class(**kwargs)

    @pytest.mark.parametrize("spec", HOOK_SPECS, ids=lambda s: s.name)
    def test_constructor_non_callable_rejected(self, spec: VirtualHookSpec):
        with pytest.raises(TypeError, match="must be callable"):
            spec.driver_class(**{spec.primary_kwarg: "not_a_callable"})

    @pytest.mark.parametrize("spec", HOOK_SPECS, ids=lambda s: s.name)
    def test_setter_methods_and_clearing(self, spec: VirtualHookSpec):
        inst = spec.driver_class()
        assert getattr(inst, spec.primary_kwarg) is None

        hook = lambda *a, **k: spec.valid_return
        setter = getattr(inst, spec.setter_name)
        setter(hook)
        assert getattr(inst, spec.primary_kwarg) is hook

        # Clearing hook
        setter(None)
        assert getattr(inst, spec.primary_kwarg) is None

    @pytest.mark.parametrize("spec", HOOK_SPECS, ids=lambda s: s.name)
    def test_declared_units(self, spec: VirtualHookSpec):
        inst = spec.driver_class()
        declared = inst.declared_units
        for k, v in spec.declared_units.items():
            assert k in declared
            assert declared[k] == v
        # Ensure declared_units is read-only
        with pytest.raises((TypeError, AttributeError)):
            declared["test_mutation"] = "unit"  # type: ignore

    @pytest.mark.parametrize("spec", HOOK_SPECS, ids=lambda s: s.name)
    def test_hook_exact_once_invocation(self, spec: VirtualHookSpec):
        calls = []

        def recording_hook(*a, **k):
            calls.append((a, k))
            return spec.valid_return

        inst = spec.driver_class(**{spec.primary_kwarg: recording_hook})
        spec.trigger_op(inst)
        assert len(calls) == 1

    @pytest.mark.parametrize("spec", HOOK_SPECS, ids=lambda s: s.name)
    def test_hook_fallback_not_accessed_when_hook_present(self, spec: VirtualHookSpec):
        class GuardedDriver(spec.driver_class):
            @property
            def sample(self):
                raise AssertionError("sample fallback must not be accessed when hook is present")

            @property
            def mag_sample(self):
                raise AssertionError("mag_sample fallback must not be accessed when hook is present")

        inst = GuardedDriver(**{spec.primary_kwarg: lambda *a, **k: spec.valid_return})
        # Triggering operation must succeed without accessing the guarded fallback property
        spec.trigger_op(inst)

    @pytest.mark.parametrize("spec", HOOK_SPECS, ids=lambda s: s.name)
    @pytest.mark.parametrize("err_cls", [RuntimeError, TypeError, ValueError, ZeroDivisionError])
    def test_hook_exception_propagates_unchanged_without_retries(
        self, spec: VirtualHookSpec, err_cls: Type[Exception]
    ):
        calls = []
        sentinel_error = err_cls("Injected test fault inside hook")

        def failing_hook(*a, **k):
            calls.append(1)
            raise sentinel_error

        inst = spec.driver_class(**{spec.primary_kwarg: failing_hook})
        with pytest.raises(err_cls) as exc_info:
            spec.trigger_op(inst)

        assert exc_info.value is sentinel_error
        assert len(calls) == 1

    @pytest.mark.parametrize("spec", HOOK_SPECS, ids=lambda s: s.name)
    def test_reset_restores_driver_state_and_preserves_hook(self, spec: VirtualHookSpec):
        hook = lambda *a, **k: spec.valid_return
        inst = spec.driver_class(**{spec.primary_kwarg: hook})
        inst.reset()
        # Injected hook is preserved across driver reset
        assert getattr(inst, spec.primary_kwarg) is hook

    @pytest.mark.parametrize("spec", HOOK_SPECS, ids=lambda s: s.name)
    def test_reset_does_not_mutate_setup_state(self, spec: VirtualHookSpec):
        class SetupHook:
            def __init__(self):
                self.time = 100.0
                self.sample_field = 500.0
                self.calls = 0

            def __call__(self, *args, **kwargs):
                self.calls += 1
                assert self.time == 100.0 and self.sample_field == 500.0
                return spec.valid_return

            def reset(self):
                raise AssertionError("Driver reset must not reset its external setup")

        setup = SetupHook()
        inst = spec.driver_class(**{spec.primary_kwarg: setup})
        spec.trigger_op(inst)
        assert setup.calls > 0
        before = vars(setup).copy()
        inst.reset()
        # Reset may notify the hook of changed output/position, but may not
        # reset the setup's clock or material memory along with the driver.
        assert setup.time == before["time"]
        assert setup.sample_field == before["sample_field"]
        assert getattr(inst, spec.primary_kwarg) is setup
        spec.trigger_op(inst)
        assert setup.calls > before["calls"]

    @pytest.mark.parametrize("spec", HOOK_SPECS, ids=lambda s: s.name)
    def test_instance_isolation(self, spec: VirtualHookSpec):
        hook1 = lambda *a, **k: spec.valid_return
        hook2 = lambda *a, **k: spec.valid_return
        inst1 = spec.driver_class(**{spec.primary_kwarg: hook1})
        inst2 = spec.driver_class(**{spec.primary_kwarg: hook2})

        assert getattr(inst1, spec.primary_kwarg) is hook1
        assert getattr(inst2, spec.primary_kwarg) is hook2

        getattr(inst1, spec.setter_name)(None)
        assert getattr(inst1, spec.primary_kwarg) is None
        assert getattr(inst2, spec.primary_kwarg) is hook2


# ============================================================================
# 4. Cross-Family Waveform & Virtual Review Regressions
# ============================================================================

class TestCrossFamilyWaveformRegressions:
    """Waveform regressions between VirtualAwg and VirtualScope."""

    def test_awg_scope_roundtrip_offset_polarity_and_pretrigger_axis(self):
        captured = {}

        def transmit(v, t):
            captured.update(voltage=v.copy(), time=t - t[-1] / 2)

        awg = VirtualAwg(waveform_hook=transmit, simulation_points=3)
        awg.create_arb_waveform(1, "test", [-1, 0, 1])
        awg.set_arb_waveform(1, "test")
        awg.set_amplitude(1, 2)
        awg.set_offset(1, 3)
        awg.set_polarity(1, "INV")
        awg.output_trigger()

        scope = VirtualScope(waveform_hook=lambda: captured)
        result = scope.get_data()
        np.testing.assert_allclose(result.Voltage, [5, 3, 1])
        assert result.Time.iloc[0] < 0 < result.Time.iloc[-1]

    def test_scope_routes_selected_channel_and_rejects_ambiguous_labels(self):
        scope = VirtualScope(waveform_hook=lambda: {"time": [0, 1], "ch1": [1, 2], "ch2": [3, 4]})
        assert scope.get_data(2).Voltage.tolist() == [3, 4]
        scope.waveform_hook = lambda: {"a": [0, 1], "b": [2, 3]}
        with pytest.raises(ValueError):
            scope.get_data()

    @pytest.mark.parametrize("times", [[1, 0], [0, 0], [0, float("inf")]])
    def test_scope_rejects_invalid_time_axis(self, times):
        with pytest.raises(ValueError):
            VirtualScope(waveform_hook=lambda: ([1, 2], times)).get_data()

    @pytest.mark.parametrize("channel", [1.5, float("nan"), float("inf")])
    def test_scope_rejects_invalid_channel_before_notifying(self, channel):
        calls = []
        scope = VirtualScope(waveform_hook=lambda: calls.append(1))
        before = scope.get_state()
        with pytest.raises(ValueError):
            scope.get_data(channel)
        with pytest.raises(ValueError):
            scope.set_vertical_scale(channel, vdiv=1)
        assert scope.get_state() == before
        assert calls == []

    @pytest.mark.parametrize("data", [[0, float("nan")], [0, float("inf")], [[0, 1], [2, 3]], 1])
    def test_awg_rejects_invalid_arb_before_mutating(self, data):
        awg = VirtualAwg()
        awg.create_arb_waveform(1, "valid", [0, 1])
        before = awg.get_state()["arb_waveform"][1].copy()
        with pytest.raises((ValueError, TypeError)):
            awg.create_arb_waveform(1, "invalid", data)
        np.testing.assert_array_equal(awg.get_state()["arb_waveform"][1], before)

    def test_awg_state_snapshot_does_not_expose_live_arb_storage(self):
        awg = VirtualAwg()
        awg.create_arb_waveform(1, "data", [0, 1])
        snapshot = awg.get_state()
        snapshot["arb_waveform"][1][0] = 99
        assert awg.get_state()["arb_waveform"][1][0] == 0

    def test_awg_scpi_queries_use_explicit_channel(self):
        awg = VirtualAwg()
        awg.write(":OUTP2 ON")
        assert awg.query(":OUTP2?") == "1"
        assert awg.query(":OUTP1?") == "0"
        awg.set_frequency(1, 100)
        awg.set_frequency(2, 200)
        assert float(awg.query(":SOUR2:FREQ?")) == 200
        assert float(awg.query(":SOUR1:FREQ?")) == 100
        before = awg.get_state()
        with pytest.raises(ValueError):
            awg.write(":OUTP3 ON")
        assert awg.get_state() == before

    def test_awg_noise_is_isolated_and_reset_replays(self):
        a, b = VirtualAwg(seed=42), VirtualAwg(seed=42)
        a.set_waveform(1, "NOIS")
        b.set_waveform(1, "NOIS")
        first = a.get_waveform(1)
        a.get_waveform(1)
        np.testing.assert_array_equal(first, b.get_waveform(1))
        a.reset()
        a.set_waveform(1, "NOIS")
        np.testing.assert_array_equal(first, a.get_waveform(1))

    @pytest.mark.parametrize("method,settings", [
        ("configure_horizontal", {"tdiv": 0.01, "x_position": float("nan")}),
        ("configure_trigger", {"trigger_source": 2, "trigger_level": float("nan")}),
        ("configure_acquisition", {"channel": 2, "acquisition_points": -1}),
    ])
    def test_scope_invalid_bundled_configuration_is_atomic(self, method, settings):
        scope = VirtualScope()
        before = scope.get_state()
        with pytest.raises(ValueError):
            getattr(scope, method)(**settings)
        assert scope.get_state() == before
