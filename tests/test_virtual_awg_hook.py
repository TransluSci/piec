"""
Unit and contract tests for generic per-instance virtual hooks on VirtualAwg.

Fulfills Checkpoint 28f of MEASUREMENT_STANDARDIZATION_PLAN.md:
- Generic per-instance virtual hooks for the AWG family (VirtualAwg).
- Explicit per-instance injection takes strict precedence over deprecated global/shared sample fallback.
- Material-specific logic (e.g. ferroelectric prep points, Landau model) kept strictly outside generic driver.
- Preserves declared units: {"voltage": "V", "frequency": "Hz", "time": "s"}.
- Validates all command inputs before mutation while preserving previous state on validation errors.
- Flexible signature binding: positional, named, positional-only, variadic, optional defaults, zero-arg.
- Exactly-once invocation with unchanged error propagation (no retries, no fallback on hook failure).
- Instance isolation protecting VirtualInstrument._shared_fe_sample.
- Driver reset ownership: reset restores default driver-owned configuration but preserves injected hooks;
  setup-owned state (models, timebase, clocks, RNG) is not reset.
"""

import math
from types import MappingProxyType
from typing import Any
from unittest.mock import MagicMock, Mock, call

import numpy as np
import pytest

from piec.drivers.awg.virtual_awg import VirtualAwg
from piec.drivers.virtual_instrument import VirtualInstrument


# ============================================================================
# 1. Hook Injection, Aliases, and Construction Tests
# ============================================================================

class TestVirtualAwgHookInjection:
    """Test hook registration, aliases, and property accessors."""

    def test_constructor_injection_primary(self):
        hook = Mock()
        awg = VirtualAwg(waveform_hook=hook)
        assert awg.waveform_hook is hook
        assert awg.apply_hook is hook
        assert awg.trigger_hook is hook

    def test_constructor_injection_aliases(self):
        hook1 = Mock()
        awg1 = VirtualAwg(apply_hook=hook1)
        assert awg1.waveform_hook is hook1

        hook2 = Mock()
        awg2 = VirtualAwg(trigger_hook=hook2)
        assert awg2.waveform_hook is hook2

    def test_constructor_identical_aliases_allowed(self):
        hook = Mock()
        awg = VirtualAwg(waveform_hook=hook, apply_hook=hook, trigger_hook=hook)
        assert awg.waveform_hook is hook

    def test_constructor_conflicting_aliases_raise_value_error(self):
        hook1 = Mock()
        hook2 = Mock()
        with pytest.raises(ValueError, match="Conflicting hooks provided"):
            VirtualAwg(waveform_hook=hook1, apply_hook=hook2)

    def test_constructor_non_callable_raises_type_error(self):
        with pytest.raises(TypeError, match="must be callable or None"):
            VirtualAwg(waveform_hook="not_a_callable")

    def test_setters_and_properties(self):
        awg = VirtualAwg()
        assert awg.waveform_hook is None

        hook = Mock()
        awg.set_waveform_hook(hook)
        assert awg.waveform_hook is hook

        # Clear with None
        awg.set_waveform_hook(None)
        assert awg.waveform_hook is None

        # Alias setters
        hook2 = Mock()
        awg.set_apply_hook(hook2)
        assert awg.apply_hook is hook2

        hook3 = Mock()
        awg.set_trigger_hook(hook3)
        assert awg.trigger_hook is hook3

        # Property setters
        hook4 = Mock()
        awg.waveform_hook = hook4
        assert awg.waveform_hook is hook4

        awg.apply_hook = None
        assert awg.waveform_hook is None

    def test_setter_non_callable_raises_type_error(self):
        awg = VirtualAwg()
        with pytest.raises(TypeError, match="must be callable or None"):
            awg.set_waveform_hook(12345)


# ============================================================================
# 2. Precedence Over Deprecated Shared Sample Fallback
# ============================================================================

class TestVirtualAwgHookPrecedence:
    """Verify explicit hook takes strict precedence and bypasses shared sample."""

    def test_fallback_when_no_hook_injected(self):
        awg = VirtualAwg(simulation_points=50)
        mock_sample = Mock()
        awg.sample = mock_sample

        awg.output_trigger()

        assert mock_sample.prep_points == 20
        assert mock_sample.apply_waveform.call_count == 1
        v_arg, t_arg = mock_sample.apply_waveform.call_args[0]
        assert len(v_arg) == 70  # 50 points + 20 prep points
        assert len(t_arg) == 70

    def test_explicit_hook_overrides_sample_completely(self):
        mock_sample = Mock()
        hook_calls = []

        def my_hook(v, t):
            hook_calls.append((v, t))

        awg = VirtualAwg(simulation_points=50, waveform_hook=my_hook)
        awg.sample = mock_sample

        awg.output_trigger()

        # Hook was called
        assert len(hook_calls) == 1
        v, t = hook_calls[0]
        assert len(v) == 50
        assert len(t) == 50

        # Sample was NEVER accessed or mutated
        assert mock_sample.apply_waveform.call_count == 0
        assert not hasattr(mock_sample, "prep_points") or mock_sample.prep_points is not 20

    def test_clearing_hook_restores_fallback(self):
        mock_sample = Mock()
        hook = Mock()
        awg = VirtualAwg(simulation_points=50, waveform_hook=hook)
        awg.sample = mock_sample

        # Trigger with hook
        awg.output_trigger()
        assert hook.call_count == 1
        assert mock_sample.apply_waveform.call_count == 0

        # Clear hook
        awg.set_waveform_hook(None)
        awg.output_trigger()
        assert hook.call_count == 1
        assert mock_sample.apply_waveform.call_count == 1


# ============================================================================
# 3. Instance Isolation
# ============================================================================

class TestVirtualAwgInstanceIsolation:
    """Verify instance sample assignments do not mutate shared class state."""

    def test_sample_property_isolation(self):
        shared_orig = VirtualInstrument._shared_fe_sample
        try:
            awg1 = VirtualAwg()
            awg2 = VirtualAwg()

            custom1 = Mock(name="custom_sample_1")
            awg1.sample = custom1

            assert awg1.sample is custom1
            assert awg2.sample is shared_orig
            assert VirtualInstrument._shared_fe_sample is shared_orig

            # Deleting instance sample restores shared fallback
            del awg1.sample
            assert awg1.sample is shared_orig
        finally:
            VirtualInstrument._shared_fe_sample = shared_orig


# ============================================================================
# 4. Declared Units
# ============================================================================

class TestVirtualAwgDeclaredUnits:
    """Verify declared units contract."""

    def test_declared_units(self):
        awg = VirtualAwg()
        units = awg.declared_units
        assert isinstance(units, MappingProxyType)
        assert units["voltage"] == "V"
        assert units["frequency"] == "Hz"
        assert units["time"] == "s"

        with pytest.raises(TypeError):
            units["voltage"] = "mV"


# ============================================================================
# 5. Input Validation Before Mutation
# ============================================================================

class TestVirtualAwgInputValidation:
    """Verify input validation rejects invalid values before mutating state."""

    def test_validate_channel(self):
        awg = VirtualAwg()
        with pytest.raises(ValueError, match="Invalid channel"):
            awg.output(channel=0, on=True)
        with pytest.raises(ValueError, match="Invalid channel"):
            awg.output(channel=3, on=True)
        with pytest.raises(TypeError, match="channel must be an integer"):
            awg.output(channel=True, on=True)
        with pytest.raises(TypeError, match="channel must be an integer"):
            awg.output(channel="1", on=True)

    def test_validate_output_boolean(self):
        awg = VirtualAwg()
        with pytest.raises(TypeError, match="on must be a boolean"):
            awg.output(channel=1, on="bad_bool")
        with pytest.raises(TypeError, match="on must be a boolean"):
            awg.output(channel=1, on=[1])

    def test_validate_frequency_preserves_state(self):
        awg = VirtualAwg()
        orig_freq = awg.state["frequency"][1]

        for bad in (0, -100.0, float("nan"), float("inf"), -float("inf")):
            with pytest.raises(ValueError, match="positive finite"):
                awg.set_frequency(1, bad)
            assert awg.state["frequency"][1] == orig_freq

        for bad in ("1000", True, [1000]):
            with pytest.raises(TypeError, match="numeric value"):
                awg.set_frequency(1, bad)
            assert awg.state["frequency"][1] == orig_freq

        awg.set_frequency(1, 5000.0)
        assert awg.state["frequency"][1] == 5000.0

    def test_validate_amplitude_preserves_state(self):
        awg = VirtualAwg()
        orig_amp = awg.state["amplitude"][1]

        for bad in (-1.0, float("nan"), float("inf")):
            with pytest.raises(ValueError, match="non-negative finite"):
                awg.set_amplitude(1, bad)
            assert awg.state["amplitude"][1] == orig_amp

        for bad in ("2.5", True, None):
            with pytest.raises(TypeError, match="numeric value"):
                awg.set_amplitude(1, bad)
            assert awg.state["amplitude"][1] == orig_amp

        awg.set_amplitude(1, 3.5)
        assert awg.state["amplitude"][1] == 3.5

    def test_validate_offset_preserves_state(self):
        awg = VirtualAwg()
        orig_off = awg.state["offset"][1]

        for bad in (float("nan"), float("inf")):
            with pytest.raises(ValueError, match="finite number"):
                awg.set_offset(1, bad)
            assert awg.state["offset"][1] == orig_off

        for bad in ("0.5", False):
            with pytest.raises(TypeError, match="numeric value"):
                awg.set_offset(1, bad)
            assert awg.state["offset"][1] == orig_off

        awg.set_offset(1, -2.0)
        assert awg.state["offset"][1] == -2.0

    def test_validate_waveform_type(self):
        awg = VirtualAwg()
        with pytest.raises(ValueError, match="Invalid waveform"):
            awg.set_waveform(1, "TRIANGLE")
        with pytest.raises(TypeError, match="waveform must be a string"):
            awg.set_waveform(1, 123)

        awg.set_waveform(1, "squ")
        assert awg.state["waveform"][1] == "SQU"

    def test_validate_polarity(self):
        awg = VirtualAwg()
        with pytest.raises(ValueError, match="Invalid polarity"):
            awg.set_polarity(1, "REVERSE")
        with pytest.raises(TypeError, match="polarity must be a string"):
            awg.set_polarity(1, 1)

        awg.set_polarity(1, "inv")
        assert awg.state["polarity"][1] == "INV"

    def test_validate_duty_cycle_and_symmetry(self):
        awg = VirtualAwg()
        for bad in (-1.0, 101.0, float("nan")):
            with pytest.raises(ValueError, match=r"\[0.0, 100.0\]"):
                awg.set_square_duty_cycle(1, bad)
            with pytest.raises(ValueError, match=r"\[0.0, 100.0\]"):
                awg.set_ramp_symmetry(1, bad)

        awg.set_square_duty_cycle(1, 75.0)
        assert awg.state["duty_cycle"][1] == 75.0
        awg.set_ramp_symmetry(1, 30.0)
        assert awg.state["symmetry"][1] == 30.0

    def test_validate_pulse_width_and_delay(self):
        awg = VirtualAwg()
        with pytest.raises(ValueError, match="positive finite"):
            awg.set_pulse_width(1, 0.0)
        with pytest.raises(ValueError, match="positive finite"):
            awg.set_pulse_width(1, -1e-6)

        with pytest.raises(ValueError, match="non-negative finite"):
            awg.set_pulse_delay(1, -1e-6)

        awg.set_pulse_width(1, 2e-6)
        assert awg.state["pulse_width"][1] == 2e-6
        awg.set_pulse_delay(1, 1e-6)
        assert awg.state["pulse_delay"][1] == 1e-6

    def test_validate_trigger_settings(self):
        awg = VirtualAwg()
        with pytest.raises(ValueError, match="Invalid trigger_source"):
            awg.set_trigger_source(1, "INVALID")
        with pytest.raises(ValueError, match="Invalid trigger_slope"):
            awg.set_trigger_slope(1, "INVALID")
        with pytest.raises(ValueError, match="Invalid trigger_mode"):
            awg.set_trigger_mode(1, "INVALID")
        with pytest.raises(ValueError, match="finite"):
            awg.set_trigger_level(1, float("nan"))

        awg.set_trigger_source(1, "ext")
        assert awg.state["trigger_source"][1] == "EXT"
        awg.set_trigger_slope(1, "neg")
        assert awg.state["trigger_slope"][1] == "NEG"
        awg.set_trigger_mode(1, "lev")
        assert awg.state["trigger_mode"][1] == "LEV"
        awg.set_trigger_level(1, 1.5)
        assert awg.state["trigger_level"][1] == 1.5

    def test_configure_waveform_atomic_validation(self):
        awg = VirtualAwg()
        orig_wf = awg.state["waveform"][1]
        orig_freq = awg.state["frequency"][1]

        # Fails on bad amplitude; waveform should not change
        with pytest.raises(ValueError, match="non-negative finite"):
            awg.configure_waveform(1, waveform="SQU", frequency=2000.0, amplitude=-5.0)

        assert awg.state["waveform"][1] == orig_wf
        assert awg.state["frequency"][1] == orig_freq

        # Valid configuration
        awg.configure_waveform(1, waveform="SQU", frequency=2000.0, amplitude=4.0, offset=1.0)
        assert awg.state["waveform"][1] == "SQU"
        assert awg.state["frequency"][1] == 2000.0
        assert awg.state["amplitude"][1] == 4.0
        assert awg.state["offset"][1] == 1.0


# ============================================================================
# 6. Signature Dispatch & Parameter Binding
# ============================================================================

class TestVirtualAwgSignatureDispatch:
    """Verify hook signature inspection and parameter binding."""

    def test_standard_v_t_signature(self):
        received = {}

        def hook(v, t):
            received["v"] = v
            received["t"] = t

        awg = VirtualAwg(simulation_points=50, waveform_hook=hook)
        awg.set_frequency(1, 1000.0)
        awg.output_trigger()

        assert len(received["v"]) == 50
        assert len(received["t"]) == 50
        assert math.isclose(received["t"][-1], 1.0 / 1000.0, rel_tol=1e-5)

    def test_v_t_channel_signature(self):
        received = {}

        def hook(v, t, channel):
            received["channel"] = channel

        awg = VirtualAwg(simulation_points=50, waveform_hook=hook)
        awg.set_acquisition_channel(2)
        awg.output_trigger()
        assert received["channel"] == 2

    def test_named_keyword_arguments(self):
        received = {}

        def hook(voltages, times, freq, amp):
            received["len_v"] = len(voltages)
            received["len_t"] = len(times)
            received["freq"] = freq
            received["amp"] = amp

        awg = VirtualAwg(simulation_points=50, waveform_hook=hook)
        awg.set_frequency(1, 2500.0)
        awg.set_amplitude(1, 3.0)
        awg.output_trigger()

        assert received["len_v"] == 50
        assert received["len_t"] == 50
        assert received["freq"] == 2500.0
        assert received["amp"] == 3.0

    def test_single_v_argument(self):
        received = {}

        def hook(v):
            received["v"] = v

        awg = VirtualAwg(simulation_points=50, waveform_hook=hook)
        awg.output_trigger()
        assert len(received["v"]) == 50

    def test_zero_argument_notification(self):
        called = []

        def hook():
            called.append(True)

        awg = VirtualAwg(waveform_hook=hook)
        awg.output_trigger()
        assert called == [True]

    def test_positional_only_arguments(self):
        received = {}

        def hook(v, t, /):
            received["v"] = v
            received["t"] = t

        awg = VirtualAwg(simulation_points=50, waveform_hook=hook)
        awg.output_trigger()
        assert len(received["v"]) == 50
        assert len(received["t"]) == 50

    def test_variadic_args_and_kwargs(self):
        received = {}

        def hook(*args, **kwargs):
            received["args"] = args
            received["kwargs"] = kwargs

        awg = VirtualAwg(simulation_points=50, waveform_hook=hook)
        awg.output_trigger()
        assert len(received["args"]) == 2  # (v, t)
        assert "frequency" in received["kwargs"]
        assert "amplitude" in received["kwargs"]
        assert "output" in received["kwargs"]

    def test_optional_parameters_retain_defaults(self):
        received = {}

        def hook(v, t, custom_opt="default_value"):
            received["custom_opt"] = custom_opt

        awg = VirtualAwg(simulation_points=50, waveform_hook=hook)
        awg.output_trigger()
        assert received["custom_opt"] == "default_value"

    def test_incompatible_signature_raises_type_error(self):
        def hook_kw(*, unsupported_required_arg):
            pass

        awg_kw = VirtualAwg(waveform_hook=hook_kw)
        with pytest.raises(TypeError, match="waveform_hook has incompatible signature"):
            awg_kw.output_trigger()

        def hook_pos(a, b, c, d, e):
            pass

        awg_pos = VirtualAwg(waveform_hook=hook_pos)
        with pytest.raises(TypeError, match="waveform_hook has incompatible signature"):
            awg_pos.output_trigger()


# ============================================================================
# 7. Error Propagation Without Retries
# ============================================================================

class TestVirtualAwgErrorPropagation:
    """Verify hook exceptions propagate unchanged with exactly one invocation."""

    def test_hook_exception_propagates_unchanged(self):
        hook = Mock(side_effect=RuntimeError("test hook explosion"))
        awg = VirtualAwg(waveform_hook=hook)

        with pytest.raises(RuntimeError, match="test hook explosion"):
            awg.output_trigger()

        assert hook.call_count == 1

    def test_hook_exception_does_not_call_fallback(self):
        hook = Mock(side_effect=ValueError("hook failure"))
        mock_sample = Mock()
        awg = VirtualAwg(waveform_hook=hook)
        awg.sample = mock_sample

        with pytest.raises(ValueError, match="hook failure"):
            awg.output_trigger()

        assert hook.call_count == 1
        assert mock_sample.apply_waveform.call_count == 0


# ============================================================================
# 8. Reset Ownership
# ============================================================================

class TestVirtualAwgResetOwnership:
    """Verify driver-owned configuration reset vs setup-owned state preservation."""

    def test_reset_restores_defaults_and_preserves_hook(self):
        hook = Mock()
        awg = VirtualAwg(waveform_hook=hook)

        # Mutate configuration
        awg.output(1, True)
        awg.output(2, True)
        awg.set_frequency(1, 50000.0)
        awg.set_amplitude(1, 10.0)
        awg.set_waveform(1, "SQU")
        awg.set_trigger_source(1, "EXT")

        assert awg.state["output"][1] is True
        assert awg.state["frequency"][1] == 50000.0

        # Execute reset
        awg.reset()

        # Injected hook is preserved intact!
        assert awg.waveform_hook is hook

        # Outputs are safely OFF
        assert awg.state["output"][1] is False
        assert awg.state["output"][2] is False

        # Configuration defaults restored
        assert awg.state["waveform"][1] == "SIN"
        assert awg.state["frequency"][1] == 1000.0
        assert awg.state["amplitude"][1] == 1.0
        assert awg.state["offset"][1] == 0.0
        assert awg.state["trigger_source"][1] == "IMM"

    def test_scpi_rst_invokes_reset(self):
        awg = VirtualAwg()
        awg.output(1, True)
        assert awg.state["output"][1] is True

        awg.write("*RST")
        assert awg.state["output"][1] is False

    def test_scpi_cls_passes_cleanly(self):
        awg = VirtualAwg()
        awg.write("*CLS")  # Must not raise


# ============================================================================
# 9. Trigger Methods & SCPI Queries
# ============================================================================

class TestVirtualAwgTriggerAndQueries:
    """Verify all trigger invocations and SCPI queries."""

    def test_all_trigger_entry_points(self):
        hook = Mock()
        awg = VirtualAwg(waveform_hook=hook)

        awg.trigger()
        assert hook.call_count == 1

        awg.output_trigger()
        assert hook.call_count == 2

        awg.send_software_trigger()
        assert hook.call_count == 3

        awg.write("*TRG")
        assert hook.call_count == 4

        awg.write(":TRIG")
        assert hook.call_count == 5

    def test_scpi_queries(self):
        awg = VirtualAwg()
        assert awg.query("*IDN?") == "Virtual AWG"
        assert awg.query("*OPC?") == "1"
        assert awg.query("*ESR?") == "0"

        assert awg.query(":OUTP?") == "0"
        awg.output(1, True)
        assert awg.query(":OUTP?") == "1"

        awg.set_frequency(1, 12345.0)
        assert awg.query(":SOUR:FREQ?") == "12345.0"

        awg.set_amplitude(1, 2.5)
        assert awg.query(":SOUR:VOLT?") == "2.5"


# ============================================================================
# 10. Material & Two-Instrument Integration
# ============================================================================

class TestVirtualAwgMaterialIntegration:
    """Verify integration with WaveformResponsiveMaterialContract and VirtualScope."""

    def test_waveform_contract_integration(self):
        from piec.simulation.contracts import WaveformResponsiveMaterialContract

        class CustomLoad(WaveformResponsiveMaterialContract):
            def __init__(self):
                self.applied_v = None
                self.applied_t = None

            def apply_waveform(self, v, t):
                self.applied_v = np.array(v)
                self.applied_t = np.array(t)

            def get_voltage_response(self):
                return self.applied_v * 0.5, self.applied_t

            def reset(self):
                self.applied_v = None
                self.applied_t = None

        load = CustomLoad()
        awg = VirtualAwg(simulation_points=60, waveform_hook=load.apply_waveform)
        awg.set_frequency(1, 500.0)
        awg.output_trigger()

        assert load.applied_v is not None
        assert len(load.applied_v) == 60
        assert len(load.applied_t) == 60
        assert math.isclose(load.applied_t[-1], 1.0 / 500.0, rel_tol=1e-5)

        v_resp, t_resp = load.get_voltage_response()
        assert len(v_resp) == 60

    def test_paired_awg_scope_hook_integration(self):
        from piec.drivers.oscilloscope.virtual_oscilloscope import VirtualScope

        # Shared simulation state between AWG sink and Scope source
        channel_data = {}

        def awg_sink(v, t, channel):
            channel_data[channel] = (v * 2.0, t)

        def scope_source(channel):
            return channel_data.get(channel, (np.zeros(10), np.linspace(0, 1e-3, 10)))

        awg = VirtualAwg(simulation_points=80, waveform_hook=awg_sink)
        scope = VirtualScope(waveform_hook=scope_source)

        awg.set_acquisition_channel(1)
        awg.set_amplitude(1, 2.0)
        awg.output_trigger()

        df = scope.get_data(channel=1)
        assert len(df) == 80
        assert "Time" in df.columns
        assert "Voltage" in df.columns
        # AWG sink doubled the amplitude
        assert np.max(df["Voltage"]) > 3.0


# ============================================================================
# 11. SCPI Output Parsing, Arb Validation, and State Copy
# ============================================================================

class TestVirtualAwgScpiAndArbDetails:
    """Verify SCPI output parsing, arbitrary waveform validation, and state independence."""

    def test_scpi_outp_commands(self):
        awg = VirtualAwg()
        awg.write(":OUTP1 ON")
        assert awg.state["output"][1] is True
        assert awg.state["output"][2] is False

        awg.write(":OUTP2 ON")
        assert awg.state["output"][2] is True

        awg.write(":OUTP1 OFF")
        assert awg.state["output"][1] is False
        assert awg.state["output"][2] is True

    def test_create_arb_waveform_validation(self):
        awg = VirtualAwg()
        with pytest.raises(ValueError, match="must not be None"):
            awg.create_arb_waveform(1, "bad", None)

        with pytest.raises(ValueError, match="must not be empty"):
            awg.create_arb_waveform(1, "bad", [])

        awg.create_arb_waveform(1, "good", [0.0, 1.0, 0.5, -0.5])
        assert awg.state["arb_waveform"][1] is not None
        assert len(awg.state["arb_waveform"][1]) == 4

        awg.set_arb_waveform(1, "good")
        assert awg.state["waveform"][1] == "USER"

    def test_get_state_returns_detached_copy(self):
        awg = VirtualAwg()
        s1 = awg.get_state()
        s1["output"][1] = True
        # mutating returned dictionary does not mutate internal driver state
        assert awg.state["output"][1] is False

    def test_set_pulse_rise_fall_time_channel_validation(self):
        awg = VirtualAwg()
        with pytest.raises(ValueError, match="Invalid channel"):
            awg.set_pulse_rise_time(3, 1e-9)
        with pytest.raises(ValueError, match="Invalid channel"):
            awg.set_pulse_fall_time(0, 1e-9)
        # Valid channels pass cleanly
        awg.set_pulse_rise_time(1, 1e-9)
        awg.set_pulse_fall_time(2, 1e-9)
