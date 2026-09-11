"""
Tests for VirtualScope generic per-instance virtual hooks (Checkpoint 28e).

Validates:
- Generic per-instance hook injection (waveform_hook, channel_hook, and data_hook aliases);
- Explicit injection precedence over deprecated global sample fallback;
- Fallback property is not accessed when explicit hook is present;
- Material-specific logic kept strictly outside generic driver;
- Command validation (finite numeric, positive divisions, channel bounds, state preservation on failure);
- Declared physical units ({"voltage": "V", "time": "s"});
- Unchanged error propagation without retries (RuntimeError, TypeError, ValueError, ZeroDivisionError);
- Exact-once invocation and signature binding (1-arg, positional-only, keywords, *args, **kwargs, zero-arg);
- Waveform response normalization and validation ((voltages, times), dict, DataFrame);
- Instance isolation protecting VirtualInstrument._shared_fe_sample;
- Reset ownership: driver-owned state restored, hook preserved, setup-owned state untouched.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd
import pytest

from piec.drivers.oscilloscope.virtual_oscilloscope import VirtualScope
from piec.drivers.virtual_instrument import VirtualInstrument


# ============================================================================
# 1. Hook Injection and Aliases
# ============================================================================

class TestVirtualScopeHookInjection:
    """Validation of hook injection, aliases, and properties."""

    def test_constructor_accepts_waveform_hook(self):
        hook = lambda ch: ([1.0], [0.0])
        scope = VirtualScope(waveform_hook=hook)
        assert scope.waveform_hook is hook
        assert scope.channel_hook is hook
        assert scope.data_hook is hook

    def test_constructor_accepts_channel_hook_alias(self):
        hook = lambda ch: ([1.0], [0.0])
        scope = VirtualScope(channel_hook=hook)
        assert scope.waveform_hook is hook
        assert scope.channel_hook is hook
        assert scope.data_hook is hook

    def test_constructor_accepts_data_hook_alias(self):
        hook = lambda ch: ([1.0], [0.0])
        scope = VirtualScope(data_hook=hook)
        assert scope.waveform_hook is hook
        assert scope.channel_hook is hook
        assert scope.data_hook is hook

    def test_constructor_identical_hooks_accepted(self):
        hook = lambda ch: ([1.0], [0.0])
        scope = VirtualScope(waveform_hook=hook, channel_hook=hook, data_hook=hook)
        assert scope.waveform_hook is hook

    def test_constructor_conflicting_hooks_rejected(self):
        hook1 = lambda ch: ([1.0], [0.0])
        hook2 = lambda ch: ([2.0], [0.0])
        with pytest.raises(ValueError, match="Cannot specify multiple conflicting hook callables"):
            VirtualScope(waveform_hook=hook1, channel_hook=hook2)

    def test_constructor_rejects_non_callable_hook(self):
        with pytest.raises(TypeError, match="waveform_hook must be callable or None"):
            VirtualScope(waveform_hook="not_a_callable")

    def test_method_and_property_injection(self):
        scope = VirtualScope()
        assert scope.waveform_hook is None
        assert scope.channel_hook is None
        assert scope.data_hook is None

        hook1 = lambda ch: ([1.0], [0.0])
        scope.set_waveform_hook(hook1)
        assert scope.waveform_hook is hook1

        hook2 = lambda ch: ([2.0], [0.0])
        scope.set_channel_hook(hook2)
        assert scope.waveform_hook is hook2
        assert scope.channel_hook is hook2

        hook3 = lambda ch: ([3.0], [0.0])
        scope.set_data_hook(hook3)
        assert scope.data_hook is hook3

        hook4 = lambda ch: ([4.0], [0.0])
        scope.waveform_hook = hook4
        assert scope.waveform_hook is hook4

        hook5 = lambda ch: ([5.0], [0.0])
        scope.channel_hook = hook5
        assert scope.channel_hook is hook5

        hook6 = lambda ch: ([6.0], [0.0])
        scope.data_hook = hook6
        assert scope.data_hook is hook6

        scope.set_waveform_hook(None)
        assert scope.waveform_hook is None
        assert scope.channel_hook is None
        assert scope.data_hook is None

    def test_injection_rejects_non_callable(self):
        scope = VirtualScope()
        with pytest.raises(TypeError, match="waveform_hook must be callable or None"):
            scope.set_waveform_hook(12345)
        with pytest.raises(TypeError, match="waveform_hook must be callable or None"):
            scope.waveform_hook = [1, 2]
        with pytest.raises(TypeError, match="waveform_hook must be callable or None"):
            scope.channel_hook = "invalid"
        with pytest.raises(TypeError, match="waveform_hook must be callable or None"):
            scope.data_hook = {"v": 1.0}


# ============================================================================
# 2. Precedence, Fallback, and Material Decoupling
# ============================================================================

class TestPrecedenceAndDecoupling:
    """Precedence of explicit injection over global fallback and material decoupling."""

    def test_explicit_injection_takes_precedence_over_sample(self):
        class MockSample:
            def get_voltage_response(self):
                return np.array([10.0, 20.0]), np.array([0.0, 1e-3])

        scope = VirtualScope()
        scope.sample = MockSample()

        # Without hook: fallback returns MockSample data
        df_fb = scope.get_data()
        assert np.allclose(df_fb["Voltage"], [10.0, 20.0])
        assert np.allclose(df_fb["Time"], [0.0, 1e-3])

        # Injected hook overrides fallback
        hook_resp = (np.array([1.5, 2.5]), np.array([0.0, 0.5e-3]))
        scope.set_waveform_hook(lambda ch: hook_resp)

        df_hook = scope.get_data()
        assert np.allclose(df_hook["Voltage"], [1.5, 2.5])
        assert np.allclose(df_hook["Time"], [0.0, 0.5e-3])

        # Clear hook: fallback is restored
        scope.set_waveform_hook(None)
        df_restored = scope.get_data()
        assert np.allclose(df_restored["Voltage"], [10.0, 20.0])

    def test_hook_precedence_does_not_access_fallback_property(self):
        """When an explicit hook is set, sample must not even be accessed."""
        class HookOnlyScope(VirtualScope):
            @property
            def sample(self):
                raise AssertionError("sample fallback must not be accessed when hook is present")

        hook = lambda ch: (np.array([3.3, 3.3]), np.array([0.0, 1e-6]))
        scope = HookOnlyScope(waveform_hook=hook)
        df = scope.get_data(channel=1)
        assert np.allclose(df["Voltage"], [3.3, 3.3])

    def test_material_logic_remains_outside_generic_driver(self):
        """VirtualScope has no material formulas; hook evaluates external physics."""
        # External photodiode pulse simulation: V(t) = V_peak * exp(-t / tau)
        tau = 2e-6
        t = np.linspace(0, 10e-6, 100)
        v = 5.0 * np.exp(-t / tau)

        scope = VirtualScope(waveform_hook=lambda ch: (v, t))
        df = scope.get_data()
        assert len(df) == 100
        assert df["Voltage"].iloc[0] == pytest.approx(5.0)
        assert df["Voltage"].iloc[-1] == pytest.approx(5.0 * np.exp(-5.0))


# ============================================================================
# 3. Declared Units, State, and Input Validation
# ============================================================================

class TestDeclaredUnitsAndInputValidation:
    """Validation of units, state copies, and command input checking."""

    def test_declared_units(self):
        scope = VirtualScope()
        assert scope.declared_units["voltage"] == "V"
        assert scope.declared_units["time"] == "s"
        assert len(scope.declared_units) == 2
        with pytest.raises((TypeError, AttributeError)):
            scope.declared_units["voltage"] = "mV"  # type: ignore

    def test_initial_state_and_get_state_copy(self):
        scope = VirtualScope()
        state = scope.get_state()
        assert state["channels_on"][1] is True
        assert state["vdiv"][1] == 1.0
        assert state["y_range"][1] == 8.0
        assert state["tdiv"] == 1e-3
        assert state["x_range"] == 8e-3
        assert state["running"] is False
        assert state["armed"] is False

        # State copy is detached
        state["vdiv"][1] = 999.0
        assert scope.state["vdiv"][1] == 1.0

    def test_toggle_channel_validation(self):
        scope = VirtualScope()
        scope.toggle_channel(2, on=False)
        assert scope.state["channels_on"][2] is False

        before = scope.get_state()
        for bad_ch in [0, 5, -1, "1", None, True, False]:
            with pytest.raises((ValueError, TypeError)):
                scope.toggle_channel(bad_ch)
        assert scope.get_state() == before

        for bad_on in ["True", "False", None, [1], 2]:
            with pytest.raises(TypeError):
                scope.toggle_channel(1, on=bad_on)
        assert scope.get_state() == before

    def test_set_vertical_scale_and_consistency(self):
        scope = VirtualScope()
        # Given vdiv only -> y_range updated consistently to 8 * vdiv
        scope.set_vertical_scale(1, vdiv=0.5)
        assert scope.state["vdiv"][1] == 0.5
        assert scope.state["y_range"][1] == 4.0

        # Given y_range only -> vdiv updated consistently to y_range / 8
        scope.set_vertical_scale(1, y_range=16.0)
        assert scope.state["y_range"][1] == 16.0
        assert scope.state["vdiv"][1] == 2.0

        # Given both
        scope.set_vertical_scale(1, vdiv=0.1, y_range=1.0)
        assert scope.state["vdiv"][1] == 0.1
        assert scope.state["y_range"][1] == 1.0

        before = scope.get_state()
        # Validation
        for bad_vdiv in [0, -1.0, float("nan"), float("inf"), "1.0", None]:
            if bad_vdiv is None:
                continue
            with pytest.raises((ValueError, TypeError)):
                scope.set_vertical_scale(1, vdiv=bad_vdiv)
        assert scope.get_state() == before

        with pytest.raises(ValueError, match="Either vdiv or y_range"):
            scope.set_vertical_scale(1)
        assert scope.get_state() == before

    def test_set_vertical_position_validation(self):
        scope = VirtualScope()
        scope.set_vertical_position(1, 10.5)
        assert scope.state["y_position"][1] == 10.5

        before = scope.get_state()
        for bad_pos in [-50.0, 50.0, float("nan"), float("inf"), "10", None, True, False]:
            with pytest.raises((ValueError, TypeError)):
                scope.set_vertical_position(1, bad_pos)
        assert scope.get_state() == before

    def test_set_horizontal_scale_and_consistency(self):
        scope = VirtualScope()
        # Given tdiv only -> x_range = tdiv * 8
        scope.set_horizontal_scale(tdiv=2e-3)
        assert scope.state["tdiv"] == 2e-3
        assert scope.state["x_range"] == 16e-3

        # Given x_range only -> tdiv = x_range / 8
        scope.set_horizontal_scale(x_range=40e-3)
        assert scope.state["x_range"] == 40e-3
        assert scope.state["tdiv"] == 5e-3

        before = scope.get_state()
        for bad_tdiv in [0, -1e-3, float("nan"), float("inf"), "2e-3", True, False]:
            with pytest.raises((ValueError, TypeError)):
                scope.set_horizontal_scale(tdiv=bad_tdiv)
        assert scope.get_state() == before

        with pytest.raises(ValueError, match="Either tdiv or x_range"):
            scope.set_horizontal_scale()
        assert scope.get_state() == before

    def test_set_input_coupling_validation(self):
        scope = VirtualScope()
        scope.set_input_coupling(1, "ac")
        assert scope.state["input_coupling"][1] == "AC"
        scope.set_input_coupling(1, "DC")
        assert scope.state["input_coupling"][1] == "DC"

        before = scope.get_state()
        for bad_c in ["GND", "INVALID", "", None, 1]:
            with pytest.raises((ValueError, TypeError)):
                scope.set_input_coupling(1, bad_c)
        assert scope.get_state() == before

    def test_set_probe_attenuation_validation(self):
        scope = VirtualScope()
        scope.set_probe_attenuation(1, 10.0)
        assert scope.state["probe_attenuation"][1] == 10.0

        before = scope.get_state()
        for bad_att in [0, -1.0, 20000.0, 0.0001, float("nan"), "10", True, False]:
            with pytest.raises((ValueError, TypeError)):
                scope.set_probe_attenuation(1, bad_att)
        assert scope.get_state() == before

    def test_set_trigger_validation(self):
        scope = VirtualScope()
        scope.set_trigger_source(2)
        assert scope.state["trigger_source"] == "CHAN2"
        scope.set_trigger_source("EXT")
        assert scope.state["trigger_source"] == "EXT"

        before = scope.get_state()
        for bad_src in [0, 5, "UNKNOWN", None]:
            with pytest.raises((ValueError, TypeError)):
                scope.set_trigger_source(bad_src)
        assert scope.get_state() == before

        scope.set_trigger_level(1.5)
        assert scope.state["trigger_level"] == 1.5
        for bad_lvl in [10.0, -10.0, float("nan"), "1.5", True, False]:
            with pytest.raises((ValueError, TypeError)):
                scope.set_trigger_level(bad_lvl)
        assert scope.get_state()["trigger_level"] == 1.5

        scope.set_trigger_slope("neg")
        assert scope.state["trigger_slope"] == "NEG"
        with pytest.raises(ValueError):
            scope.set_trigger_slope("INVALID")

        scope.set_trigger_sweep("norm")
        assert scope.state["trigger_sweep"] == "NORM"
        with pytest.raises(ValueError):
            scope.set_trigger_sweep("INVALID")

    def test_configure_helpers_validate_before_mutation(self):
        scope = VirtualScope()
        before = scope.get_state()
        with pytest.raises(ValueError):
            scope.configure_horizontal(tdiv=-1.0)
        assert scope.get_state() == before

        with pytest.raises(ValueError):
            scope.configure_trigger(trigger_source=99)
        assert scope.get_state() == before

        with pytest.raises(ValueError):
            scope.configure_acquisition(channel=99)
        assert scope.get_state() == before


# ============================================================================
# 4. Signature Binding, Error Propagation, and Exact-Once Invocation
# ============================================================================

class TestSignatureBindingAndErrorPropagation:
    """Exact-once invocation, signature binding, and error preservation."""

    def test_single_positional_argument_hook(self):
        calls = []
        def hook(ch):
            calls.append(ch)
            return np.array([1.0, 2.0]), np.array([0.0, 1.0])

        scope = VirtualScope(waveform_hook=hook)
        df = scope.get_data(channel=2)
        assert calls == [2]
        assert len(df) == 2

    def test_positional_only_argument_hook(self):
        calls = []
        def hook(ch, /):
            calls.append(ch)
            return np.array([1.0]), np.array([0.0])

        scope = VirtualScope(waveform_hook=hook)
        scope.get_data(channel=3)
        assert calls == [3]

    def test_multi_argument_signature_binding(self):
        calls = []
        def hook(channel, tdiv, vdiv):
            calls.append((channel, tdiv, vdiv))
            return np.array([1.0]), np.array([0.0])

        scope = VirtualScope(waveform_hook=hook)
        scope.set_horizontal_scale(tdiv=5e-3)
        scope.set_vertical_scale(1, vdiv=0.2)
        scope.get_data(channel=1)
        assert calls == [(1, 5e-3, 0.2)]

    def test_hook_with_keyword_arguments(self):
        received = []
        def hook(*, channel, points):
            received.append((channel, points))
            return np.array([1.0]), np.array([0.0])

        scope = VirtualScope(waveform_hook=hook, simulation_points=256)
        scope.get_data(channel=4)
        assert received == [(4, 256)]

    def test_hook_with_kwargs(self):
        received = []
        def hook(**kwargs):
            received.append(kwargs)
            return np.array([1.0]), np.array([0.0])

        scope = VirtualScope(waveform_hook=hook)
        scope.get_data(channel=1)
        assert len(received) == 1
        assert received[0]["channel"] == 1
        assert received[0]["ch"] == 1
        assert "tdiv" in received[0]
        assert "vdiv" in received[0]

    def test_zero_argument_hook(self):
        calls = []
        def hook():
            calls.append(1)
            return np.array([1.0]), np.array([0.0])

        scope = VirtualScope(waveform_hook=hook)
        scope.get_data()
        assert len(calls) == 1

    def test_unrelated_optional_hook_argument_keeps_default(self):
        calls = []
        def hook(channel, gain=9):
            calls.append((channel, gain))
            return np.array([1.0]), np.array([0.0])

        scope = VirtualScope(waveform_hook=hook)
        scope.get_data(channel=2)
        assert calls == [(2, 9)]

    def test_incompatible_hook_signature_raises_type_error(self):
        def bad_sig(a, b, c, d, e):
            pass

        scope = VirtualScope(waveform_hook=bad_sig)
        with pytest.raises(TypeError, match="waveform_hook has incompatible signature"):
            scope.get_data(channel=1)

    @pytest.mark.parametrize("error_cls", [RuntimeError, TypeError, ValueError, ZeroDivisionError])
    def test_hook_exception_propagates_unchanged_without_retries(self, error_cls):
        calls = []
        error = error_cls("Simulated digitizer PCIe buffer overrun")

        def failing_hook(*args, **kwargs):
            calls.append((args, kwargs))
            raise error

        scope = VirtualScope(waveform_hook=failing_hook)
        with pytest.raises(error_cls) as exc_info:
            scope.get_data(channel=1)

        assert exc_info.value is error
        assert len(calls) == 1


# ============================================================================
# 5. Output Normalization and Validation
# ============================================================================

class TestOutputNormalizationAndValidation:
    """Normalization of diverse hook return types into standard DataFrames."""

    def test_tuple_voltages_times(self):
        v = np.array([0.0, 1.0, 2.0])
        t = np.array([0.0, 1e-3, 2e-3])
        scope = VirtualScope(waveform_hook=lambda ch: (v, t))
        df = scope.get_data()
        assert np.allclose(df["Voltage"], v)
        assert np.allclose(df["Time"], t)

    def test_tuple_with_negative_voltages_and_positive_times(self):
        v = np.array([-5.0, 3.0, -1.0])  # Negative and positive voltages
        t = np.array([0.0, 1e-3, 2e-3])  # Strictly monotonic non-negative time
        scope = VirtualScope(waveform_hook=lambda ch: (v, t))
        df = scope.get_data()
        assert np.allclose(df["Voltage"], v)
        assert np.allclose(df["Time"], t)

    def test_dataframe_return(self):
        raw_df = pd.DataFrame({"Time": [0.0, 1e-3], "Voltage": [2.5, 3.5]})
        scope = VirtualScope(waveform_hook=lambda ch: raw_df)
        df = scope.get_data()
        assert np.allclose(df["Voltage"], [2.5, 3.5])
        assert np.allclose(df["Time"], [0.0, 1e-3])

    def test_dict_return(self):
        raw_dict = {"time": [0.0, 1e-3, 2e-3], "voltage": [10.0, 20.0, 30.0]}
        scope = VirtualScope(waveform_hook=lambda ch: raw_dict)
        df = scope.get_data()
        assert np.allclose(df["Voltage"], [10.0, 20.0, 30.0])
        assert np.allclose(df["Time"], [0.0, 1e-3, 2e-3])

    def test_mismatched_lengths_rejected(self):
        scope = VirtualScope(waveform_hook=lambda ch: ([1.0, 2.0], [0.0]))
        with pytest.raises(ValueError, match="matching length"):
            scope.get_data()

    def test_empty_arrays_rejected(self):
        scope = VirtualScope(waveform_hook=lambda ch: ([], []))
        with pytest.raises(ValueError, match="must not be empty"):
            scope.get_data()

    def test_negative_or_non_finite_time_rejected(self):
        scope = VirtualScope(waveform_hook=lambda ch: ([1.0, 2.0], [-1.0, 1.0]))
        with pytest.raises(ValueError, match="finite and non-negative"):
            scope.get_data()

        scope2 = VirtualScope(waveform_hook=lambda ch: ([1.0, 2.0], [0.0, float("nan")]))
        with pytest.raises(ValueError, match="finite and non-negative"):
            scope2.get_data()

    def test_unsupported_return_type_rejected(self):
        scope = VirtualScope(waveform_hook=lambda ch: "not_a_waveform")
        with pytest.raises(TypeError, match="waveform_hook must return"):
            scope.get_data()


# ============================================================================
# 6. Deterministic Reset and Instance Isolation
# ============================================================================

class TestDeterministicResetAndInstanceIsolation:
    """Reset ownership and isolation of state across instances."""

    def test_reset_restores_defaults_and_preserves_hook(self):
        hook = lambda ch: (np.array([1.0]), np.array([0.0]))
        scope = VirtualScope(waveform_hook=hook)

        # Mutate configuration
        scope.set_vertical_scale(1, vdiv=0.2)
        scope.set_horizontal_scale(tdiv=5e-3)
        scope.toggle_channel(1, on=False)
        assert scope.state["vdiv"][1] == 0.2
        assert scope.state["tdiv"] == 5e-3
        assert scope.state["channels_on"][1] is False

        # Reset
        scope.reset()
        assert scope.state["vdiv"][1] == 1.0
        assert scope.state["tdiv"] == 1e-3
        assert scope.state["channels_on"][1] is True

        # Hook is preserved
        assert scope.waveform_hook is hook
        df = scope.get_data()
        assert len(df) == 1

    def test_reset_does_not_mutate_setup_owned_closure_state(self):
        """Driver reset does NOT reset setup-owned state (external material/timebase/RNG)."""
        external_state = {"acquisitions_count": 0}

        def counting_hook(ch):
            external_state["acquisitions_count"] += 1
            return np.array([1.0]), np.array([0.0])

        scope = VirtualScope(waveform_hook=counting_hook)
        scope.get_data()
        assert external_state["acquisitions_count"] == 1

        # Reset driver
        scope.reset()
        # Setup-owned state is untouched
        assert external_state["acquisitions_count"] == 1

    def test_instance_sample_assignment_isolated_from_shared_and_other_instances(self, monkeypatch):
        """Mutating sample on one instance does not mutate VirtualInstrument._shared_fe_sample."""
        class MockShared:
            def get_voltage_response(self):
                return np.array([1.0]), np.array([0.0])

        shared = MockShared()
        monkeypatch.setattr(VirtualInstrument, "_shared_fe_sample", shared)

        scope1 = VirtualScope()
        scope2 = VirtualScope()

        assert scope1.sample is shared
        assert scope2.sample is shared

        # Mutate instance 1
        scope1.sample = None
        hook_resp = (np.array([5.0]), np.array([0.0]))
        scope1.waveform_hook = lambda ch: hook_resp

        df1 = scope1.get_data()
        assert np.allclose(df1["Voltage"], [5.0])
        # scope2 uses shared sample fallback
        df2 = scope2.get_data()
        assert np.allclose(df2["Voltage"], [1.0])

        # Global shared sample reflects shared, completely isolated from scope1
        assert VirtualInstrument._shared_fe_sample is shared

        # Deleting instance override restores access to shared sample
        del scope1.sample
        scope1.waveform_hook = None
        assert scope1.sample is shared
        df1_restored = scope1.get_data()
        assert np.allclose(df1_restored["Voltage"], [1.0])

    def test_scpi_commands_and_clear(self):
        scope = VirtualScope()
        assert scope.clear() is None
        assert scope.idn() == "Virtual Oscilloscope"
        assert scope.query("*IDN?") == "Virtual Oscilloscope"
        assert scope.query("*ESR?") == "0"
        assert scope.query("*OPC?") == "1"

        scope.set_vertical_scale(1, vdiv=0.5)
        scope.write("*RST")
        assert scope.state["vdiv"][1] == 1.0

    def test_autoscale_and_initialize(self):
        scope = VirtualScope()
        scope.set_vertical_scale(1, vdiv=0.5)
        scope.autoscale()
        assert scope.state["vdiv"][1] == 1.0

        scope.set_vertical_scale(1, vdiv=0.5)
        scope.initialize()
        assert scope.state["vdiv"][1] == 1.0
