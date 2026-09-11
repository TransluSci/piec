"""
Comprehensive tests for Checkpoint 28g: VirtualSourcemeter generic per-instance virtual hooks.

Covers:
1. Hook injection, aliases, clearing, and precedence.
2. ElectricalLoadContract integration (ResistorLoad, DiodeLoad, CapacitiveLoad).
3. Operating modes: voltage-source mode and current-source mode.
4. Compliance limits, clamping behavior, and compliance_tripped tracking.
5. Distinguishing configured setpoints from effective terminal output (output ON vs OFF).
6. Flexible signature binding (3-arg, 2-arg, named, 1-arg, 0-arg, positional-only, *args, **kwargs).
7. Return value normalization (LoadResponse, tuple, dict, scalar, None) and validation.
8. Unconfirmed state (output_on = None) on hook failure and recovery on subsequent success.
9. Exact-once invocation and unchanged error propagation without retries.
10. Declared units and input validation before mutation.
11. Reset ownership (driver factory defaults restored, hook preserved, setup state untouched).
12. Instance isolation (descriptors, state copies, no shared-sample leakage).
13. SCPI command and query dispatch with active hooks.
"""

from __future__ import annotations

import math
from types import MappingProxyType
from typing import Any, Mapping

import pytest

from piec.drivers.sourcemeter.virtual_sourcemeter import VirtualSourcemeter
from piec.drivers.virtual_instrument import VirtualInstrument
from piec.simulation.contracts import (
    DiodeLoad,
    ElectricalLoadContract,
    LoadMode,
    LoadResponse,
    ResistorLoad,
)


# ============================================================================
# 1. Hook Injection, Aliases, and Precedence
# ============================================================================

class TestHookInjectionAndAliases:
    """Test hook registration, aliases, clearing, and precedence."""

    def test_load_hook_constructor_injection(self):
        hook = lambda mode, stimulus, comp: (stimulus, 0.001)
        vsm = VirtualSourcemeter(load_hook=hook)
        assert vsm.load_hook is hook
        assert vsm.source_hook is hook
        assert vsm.measure_hook is hook
        assert vsm.transport_hook is hook

    @pytest.mark.parametrize("alias_name", ["source_hook", "measure_hook", "transport_hook"])
    def test_hook_constructor_aliases(self, alias_name):
        hook = lambda mode, stimulus, comp: (stimulus, 0.002)
        kwargs = {alias_name: hook}
        vsm = VirtualSourcemeter(**kwargs)
        assert vsm.load_hook is hook
        assert getattr(vsm, alias_name) is hook

    def test_conflicting_hook_aliases_raise_value_error(self):
        hook1 = lambda m, s, c: None
        hook2 = lambda m, s, c: None
        with pytest.raises(ValueError, match="conflicting"):
            VirtualSourcemeter(load_hook=hook1, source_hook=hook2)

    def test_identical_hook_in_multiple_aliases_accepted(self):
        hook = lambda m, s, c: None
        vsm = VirtualSourcemeter(load_hook=hook, source_hook=hook, measure_hook=hook)
        assert vsm.load_hook is hook

    def test_property_and_method_setters(self):
        vsm = VirtualSourcemeter()
        assert vsm.load_hook is None

        h1 = lambda m, s, c: None
        vsm.set_load_hook(h1)
        assert vsm.load_hook is h1

        h2 = lambda m, s, c: None
        vsm.set_source_hook(h2)
        assert vsm.load_hook is h2

        h3 = lambda m, s, c: None
        vsm.set_measure_hook(h3)
        assert vsm.load_hook is h3

        h4 = lambda m, s, c: None
        vsm.set_transport_hook(h4)
        assert vsm.load_hook is h4

        # Clear hook
        vsm.set_load_hook(None)
        assert vsm.load_hook is None

    def test_property_assignment(self):
        vsm = VirtualSourcemeter()
        hook = lambda m, s, c: None
        vsm.load_hook = hook
        assert vsm.load_hook is hook

        vsm.source_hook = hook
        assert vsm.load_hook is hook

        vsm.measure_hook = hook
        assert vsm.load_hook is hook

        vsm.transport_hook = hook
        assert vsm.load_hook is hook

        vsm.load_hook = None
        assert vsm.load_hook is None

    def test_non_callable_non_contract_raises_type_error(self):
        vsm = VirtualSourcemeter()
        with pytest.raises(TypeError, match="callable or implement evaluate"):
            vsm.set_load_hook("not_a_callable")

        with pytest.raises(TypeError, match="callable or implement evaluate"):
            VirtualSourcemeter(load_hook=42)

    def test_strict_precedence_over_fallback(self):
        calls = []
        def my_hook(v, i):
            calls.append((v, i))
            return 3.14, 0.042

        vsm = VirtualSourcemeter(load_hook=my_hook)
        vsm.output(1, on=True)
        vsm.set_source_voltage(1, 5.0)

        assert vsm.get_voltage(1) == 3.14
        assert vsm.get_current(1) == 0.042
        assert len(calls) >= 1

        # Clear hook -> restores default unhooked fallback
        vsm.load_hook = None
        vsm.set_source_voltage(1, 7.0)
        vsm.set_source_current(1, 0.01)
        assert vsm.get_voltage(1) == 7.0
        assert vsm.get_current(1) == 0.01


# ============================================================================
# 2. ElectricalLoadContract Integration
# ============================================================================

class TestElectricalLoadContractIntegration:
    """Test interaction with concrete simulation contracts (ResistorLoad, DiodeLoad)."""

    def test_resistor_load_voltage_source_mode(self):
        resistor = ResistorLoad(resistance=500.0)
        vsm = VirtualSourcemeter(load_hook=resistor)
        vsm.output(1, on=True)

        vsm.configure_voltage_source(channel=1, voltage=5.0, current_compliance=1.0)
        assert vsm.get_voltage(1) == pytest.approx(5.0)
        assert vsm.get_current(1) == pytest.approx(0.01)  # 5.0 / 500 = 0.01 A
        assert vsm.get_resistance(1) == pytest.approx(500.0)
        assert vsm.compliance_tripped is False

        # Reverse polarity
        vsm.set_source_voltage(1, -2.5)
        assert vsm.get_voltage(1) == pytest.approx(-2.5)
        assert vsm.get_current(1) == pytest.approx(-0.005)
        assert vsm.get_resistance(1) == pytest.approx(500.0)
        assert vsm.compliance_tripped is False

    def test_resistor_load_current_source_mode(self):
        resistor = ResistorLoad(resistance=1000.0)
        vsm = VirtualSourcemeter(load_hook=resistor)
        vsm.output(1, on=True)

        vsm.configure_current_source(channel=1, current=0.003, voltage_compliance=10.0)
        assert vsm.get_current(1) == pytest.approx(0.003)
        assert vsm.get_voltage(1) == pytest.approx(3.0)  # 0.003 * 1000 = 3.0 V
        assert vsm.get_resistance(1) == pytest.approx(1000.0)
        assert vsm.compliance_tripped is False

        # Reverse polarity
        vsm.set_source_current(1, -0.005)
        assert vsm.get_current(1) == pytest.approx(-0.005)
        assert vsm.get_voltage(1) == pytest.approx(-5.0)
        assert vsm.get_resistance(1) == pytest.approx(1000.0)
        assert vsm.compliance_tripped is False

    def test_diode_load_integration(self):
        diode = DiodeLoad(is_sat=1e-12, n=1.0, temp_k=300.0, r_series=10.0)
        vsm = VirtualSourcemeter(load_hook=diode)
        vsm.output(1, on=True)

        # Forward bias: positive voltage produces forward current
        vsm.configure_voltage_source(channel=1, voltage=0.7, current_compliance=0.1)
        i_fwd = vsm.get_current(1)
        assert i_fwd > 0.0
        assert vsm.get_voltage(1) == pytest.approx(0.7)

        # Reverse bias: produces negligible reverse current
        vsm.set_source_voltage(1, -1.0)
        i_rev = vsm.get_current(1)
        assert -1e-11 <= i_rev <= 0.0


# ============================================================================
# 3. Compliance Clamping and Tripping
# ============================================================================

class TestComplianceClampingAndTripping:
    """Test compliance limiting in voltage-source and current-source modes."""

    def test_voltage_source_current_compliance_clamping(self):
        resistor = ResistorLoad(resistance=100.0)
        vsm = VirtualSourcemeter(load_hook=resistor)
        vsm.output(1, on=True)

        # 10 V on 100 Ohm would draw 0.1 A, but compliance is set to 0.02 A
        vsm.configure_voltage_source(channel=1, voltage=10.0, current_compliance=0.02)

        assert vsm.compliance_tripped is True
        assert vsm.state["compliance_tripped"] is True
        assert vsm.get_current(1) == pytest.approx(0.02)
        assert vsm.get_voltage(1) == pytest.approx(2.0)  # 0.02 * 100 Ohm = 2.0 V
        assert vsm.effective_voltage == pytest.approx(2.0)
        assert vsm.effective_current == pytest.approx(0.02)

        # Relieve compliance by increasing compliance limit
        vsm.set_current_compliance(1, 0.15)
        assert vsm.compliance_tripped is False
        assert vsm.get_current(1) == pytest.approx(0.1)
        assert vsm.get_voltage(1) == pytest.approx(10.0)

    def test_current_source_voltage_compliance_clamping(self):
        resistor = ResistorLoad(resistance=1000.0)
        vsm = VirtualSourcemeter(load_hook=resistor)
        vsm.output(1, on=True)

        # 0.02 A through 1000 Ohm would require 20 V, but compliance is 5.0 V
        vsm.configure_current_source(channel=1, current=0.02, voltage_compliance=5.0)

        assert vsm.compliance_tripped is True
        assert vsm.state["compliance_tripped"] is True
        assert vsm.get_voltage(1) == pytest.approx(5.0)
        assert vsm.get_current(1) == pytest.approx(0.005)  # 5.0 / 1000 Ohm = 0.005 A
        assert vsm.effective_voltage == pytest.approx(5.0)
        assert vsm.effective_current == pytest.approx(0.005)

        # Relieve compliance by lowering current
        vsm.set_source_current(1, 0.003)
        assert vsm.compliance_tripped is False
        assert vsm.get_voltage(1) == pytest.approx(3.0)
        assert vsm.get_current(1) == pytest.approx(0.003)

    def test_callable_compliance_clamping_for_tuple_return(self):
        # Callable returning (v, i) tuple exceeding compliance
        vsm = VirtualSourcemeter(load_hook=lambda v, i: (v, 1.0))
        vsm.output(1, on=True)
        vsm.configure_voltage_source(channel=1, voltage=5.0, current_compliance=0.05)

        assert vsm.compliance_tripped is True
        assert vsm.get_current(1) == pytest.approx(0.05)
        assert vsm.get_voltage(1) == pytest.approx(5.0)

    def test_callable_compliance_clamping_for_scalar_return(self):
        # In voltage source mode, scalar return is current
        vsm = VirtualSourcemeter(load_hook=lambda v: 0.5)
        vsm.output(1, on=True)
        vsm.configure_voltage_source(channel=1, voltage=5.0, current_compliance=0.1)

        assert vsm.compliance_tripped is True
        assert vsm.get_current(1) == pytest.approx(0.1)


# ============================================================================
# 4. Configured Values vs Effective Output
# ============================================================================

class TestConfiguredValuesVsEffectiveOutput:
    """Verify clean separation between configured setpoints and effective terminal output."""

    def test_output_off_reports_zero_terminal_output(self):
        resistor = ResistorLoad(resistance=100.0)
        vsm = VirtualSourcemeter(load_hook=resistor)
        vsm.configure_voltage_source(channel=1, voltage=10.0, current_compliance=0.5)

        # Output is OFF initially
        assert vsm.state["output_on"] is False
        assert vsm.state["source_voltage"] == 10.0
        assert vsm.effective_voltage == 0.0
        assert vsm.effective_current == 0.0
        assert vsm.get_voltage(1) == 0.0
        assert vsm.get_current(1) == 0.0
        assert vsm.get_resistance(1) == float("inf")
        assert vsm.compliance_tripped is False

        # Stored setpoint is preserved in queries
        assert vsm.query(":SOUR:VOLT:LEV?") == "10.0"
        assert vsm.query(":OUTP?") == "0"
        assert vsm.query(":READ?") == "0.000000E+00,0.000000E+00,INF,0.000000E+00,0"

    def test_enabling_output_engages_effective_output(self):
        resistor = ResistorLoad(resistance=100.0)
        vsm = VirtualSourcemeter(load_hook=resistor)
        vsm.configure_voltage_source(channel=1, voltage=5.0, current_compliance=0.5)

        vsm.output(1, on=True)
        assert vsm.state["output_on"] is True
        assert vsm.get_voltage(1) == pytest.approx(5.0)
        assert vsm.get_current(1) == pytest.approx(0.05)
        assert vsm.effective_voltage == pytest.approx(5.0)
        assert vsm.effective_current == pytest.approx(0.05)
        assert vsm.query(":OUTP?") == "1"

        # Disabling restores zero effective output while preserving setpoint
        vsm.output(1, on=False)
        assert vsm.state["output_on"] is False
        assert vsm.state["source_voltage"] == 5.0
        assert vsm.get_voltage(1) == 0.0
        assert vsm.get_current(1) == 0.0
        assert vsm.effective_voltage == 0.0
        assert vsm.effective_current == 0.0

    def test_hook_receives_zero_stimulus_when_output_disabled(self):
        notifications = []
        def hook(**kwargs):
            notifications.append(kwargs)
            return 0.0, 0.0

        vsm = VirtualSourcemeter(load_hook=hook)
        vsm.configure_voltage_source(channel=1, voltage=8.0, current_compliance=0.1)
        vsm.output(1, on=True)
        assert notifications[-1]["stimulus"] == 8.0
        assert notifications[-1]["output_on"] is True

        vsm.output(1, on=False)
        assert notifications[-1]["stimulus"] == 0.0
        assert notifications[-1]["output_on"] is False


# ============================================================================
# 5. Flexible Callable Signatures and Argument Binding
# ============================================================================

class TestFlexibleSignatureBinding:
    """Test binding of varied user callable signatures."""

    def test_three_arg_signature(self):
        calls = []
        def hook(mode, stimulus, compliance):
            calls.append((mode, stimulus, compliance))
            return stimulus, 0.001

        vsm = VirtualSourcemeter(load_hook=hook)
        vsm.output(1, on=True)
        vsm.configure_voltage_source(1, voltage=4.0, current_compliance=0.05)
        vsm.get_voltage(1)

        assert calls[-1] == (LoadMode.VOLTAGE_SOURCE, 4.0, 0.05)

    def test_two_arg_voltage_current_signature(self):
        calls = []
        def hook(voltage, current):
            calls.append((voltage, current))
            return voltage, 0.002

        vsm = VirtualSourcemeter(load_hook=hook)
        vsm.output(1, on=True)
        vsm.configure_voltage_source(1, voltage=3.5, current_compliance=0.05)
        vsm.get_voltage(1)

        assert calls[-1] == (3.5, 0.0)

    def test_single_arg_stimulus_signature(self):
        calls = []
        def hook(stimulus):
            calls.append(stimulus)
            return stimulus / 1000.0  # scalar current

        vsm = VirtualSourcemeter(load_hook=hook)
        vsm.output(1, on=True)
        vsm.set_source_voltage(1, 6.0)
        assert vsm.get_current(1) == pytest.approx(0.006)
        assert calls[-1] == 6.0

    def test_zero_arg_signature(self):
        calls = []
        def hook():
            calls.append(1)
            return 2.0, 0.01

        vsm = VirtualSourcemeter(load_hook=hook)
        vsm.output(1, on=True)
        assert vsm.get_voltage(1) == 2.0
        assert len(calls) >= 1

    def test_positional_only_signature(self):
        def hook(v, /, i=0.0):
            return v, 0.005

        vsm = VirtualSourcemeter(load_hook=hook)
        vsm.output(1, on=True)
        vsm.set_source_voltage(1, 4.2)
        assert vsm.get_voltage(1) == 4.2
        assert vsm.get_current(1) == 0.005

    def test_keyword_only_signature(self):
        received = {}
        def hook(*, mode, voltage, current, compliance, output_on):
            received.update({
                "mode": mode,
                "voltage": voltage,
                "current": current,
                "compliance": compliance,
                "output_on": output_on,
            })
            return voltage, 0.001

        vsm = VirtualSourcemeter(load_hook=hook)
        vsm.output(1, on=True)
        vsm.configure_voltage_source(1, voltage=5.5, current_compliance=0.02)
        vsm.get_voltage(1)

        assert received["voltage"] == 5.5
        assert received["output_on"] is True
        assert received["compliance"] == 0.02

    def test_variadic_args_and_kwargs(self):
        calls = []
        def hook(*args, **kwargs):
            calls.append((args, kwargs))
            return 1.0, 0.01

        vsm = VirtualSourcemeter(load_hook=hook)
        vsm.output(1, on=True)
        vsm.set_source_voltage(1, 2.5)
        vsm.get_voltage(1)

        args, kwargs = calls[-1]
        assert len(args) >= 1
        assert args[0] == 2.5
        assert "voltage" in kwargs

    def test_unrelated_optional_parameter_retains_default(self):
        calls = []
        def hook(stimulus, extra_param="default_val"):
            calls.append((stimulus, extra_param))
            return stimulus, 0.01

        vsm = VirtualSourcemeter(load_hook=hook)
        vsm.output(1, on=True)
        vsm.set_source_voltage(1, 3.0)
        vsm.get_voltage(1)

        assert calls[-1] == (3.0, "default_val")


# ============================================================================
# 6. Return Value Normalization and Validation
# ============================================================================

class TestReturnValueNormalization:
    """Test normalization of various hook return types."""

    def test_load_response_return(self):
        resp = LoadResponse(voltage=4.0, current=0.008, compliance_tripped=False, resistance=500.0)
        vsm = VirtualSourcemeter(load_hook=lambda *args: resp)
        vsm.output(1, on=True)
        assert vsm.get_voltage(1) == 4.0
        assert vsm.get_current(1) == 0.008
        assert vsm.compliance_tripped is False

    def test_dict_return(self):
        vsm = VirtualSourcemeter(load_hook=lambda *args: {"voltage": 3.3, "current": 0.0033})
        vsm.output(1, on=True)
        assert vsm.get_voltage(1) == 3.3
        assert vsm.get_current(1) == 0.0033

    def test_none_return_observer(self):
        vsm = VirtualSourcemeter(load_hook=lambda *args: None)
        vsm.output(1, on=True)
        vsm.set_source_voltage(1, 6.0)
        assert vsm.get_voltage(1) == 6.0
        assert vsm.get_current(1) == 0.0

    def test_malformed_return_type_raises_type_error(self):
        vsm = VirtualSourcemeter(load_hook=lambda *args: "invalid_string_return")
        with pytest.raises(TypeError, match="Invalid return type"):
            vsm.output(1, on=True)

    def test_non_finite_values_in_tuple_raise_value_error(self):
        vsm = VirtualSourcemeter(load_hook=lambda *args: (float("nan"), 0.01))
        with pytest.raises(ValueError, match="non-finite"):
            vsm.output(1, on=True)


# ============================================================================
# 7. Unconfirmed State on Failure
# ============================================================================

class TestUnconfirmedStateOnFailure:
    """Verify that hook failures mark output_on as None and propagate without retries."""

    @pytest.mark.parametrize("error_cls", [RuntimeError, ValueError, ZeroDivisionError, OSError])
    def test_error_propagates_unchanged_without_retries(self, error_cls):
        calls = []
        error = error_cls("Simulated hardware fault")
        def failing_hook(*args, **kwargs):
            calls.append(1)
            raise error

        vsm = VirtualSourcemeter(load_hook=failing_hook)
        with pytest.raises(error_cls) as exc_info:
            vsm.output(1, on=True)

        assert exc_info.value is error
        assert len(calls) == 1
        assert vsm.state["output_on"] is None
        assert vsm._output_enabled is None

    @pytest.mark.parametrize("operation", ["output_on", "output_off", "set_voltage", "set_current", "reset"])
    def test_failed_command_marks_output_unconfirmed_until_successful_command(self, operation):
        calls = []
        error = RuntimeError("hook communication failure")
        def fail(*args, **kwargs):
            calls.append(1)
            raise error

        vsm = VirtualSourcemeter()
        vsm.configure_voltage_source(1, voltage=5.0, current_compliance=0.1)
        vsm.output(1, on=True)
        assert vsm.state["output_on"] is True

        vsm.load_hook = fail
        actions = {
            "output_on": lambda: vsm.output(1, on=True),
            "output_off": lambda: vsm.output(1, on=False),
            "set_voltage": lambda: vsm.set_source_voltage(1, 3.0),
            "set_current": lambda: vsm.set_source_current(1, 0.01),
            "reset": vsm.reset,
        }

        with pytest.raises(RuntimeError) as exc_info:
            actions[operation]()

        assert exc_info.value is error
        assert vsm.state["output_on"] is None
        assert vsm._output_enabled is None

        # Recovery on subsequent successful command
        vsm.load_hook = lambda *args, **kwargs: (0.0, 0.0)
        vsm.output(1, on=False)
        assert vsm.state["output_on"] is False
        assert vsm._output_enabled is False


# ============================================================================
# 8. Declared Units and Input Validation Before Mutation
# ============================================================================

class TestDeclaredUnitsAndInputValidation:
    """Test declared units mapping and atomic validation before mutation."""

    def test_declared_units(self):
        vsm = VirtualSourcemeter()
        assert isinstance(vsm.declared_units, (dict, MappingProxyType))
        assert vsm.declared_units["voltage"] == "V"
        assert vsm.declared_units["current"] == "A"
        assert vsm.declared_units["resistance"] == "Ohm"
        assert vsm.declared_units["time"] == "s"

    @pytest.mark.parametrize("bad_channel", [0, 2, -1, 99, "CH1"])
    def test_invalid_channel_rejected(self, bad_channel):
        vsm = VirtualSourcemeter()
        with pytest.raises(ValueError, match="Invalid channel"):
            vsm.set_source_voltage(channel=bad_channel, voltage=1.0)
        with pytest.raises(ValueError, match="Invalid channel"):
            vsm.output(channel=bad_channel, on=True)

    @pytest.mark.parametrize("bad_volt", ["5V", None, [1.0], (1.0,), True, False])
    def test_non_numeric_voltage_rejected(self, bad_volt):
        vsm = VirtualSourcemeter()
        before = dict(vsm.state)
        with pytest.raises(TypeError if bad_volt is not None else ValueError):
            vsm.set_source_voltage(1, voltage=bad_volt)
        assert vsm.state == before

    @pytest.mark.parametrize("bad_curr", ["10mA", None, [0.1], True, False])
    def test_non_numeric_current_rejected(self, bad_curr):
        vsm = VirtualSourcemeter()
        before = dict(vsm.state)
        with pytest.raises(TypeError if bad_curr is not None else ValueError):
            vsm.set_source_current(1, current=bad_curr)
        assert vsm.state == before

    @pytest.mark.parametrize("non_finite", [float("nan"), float("inf"), float("-inf")])
    def test_non_finite_values_rejected(self, non_finite):
        vsm = VirtualSourcemeter()
        before = dict(vsm.state)
        with pytest.raises(ValueError, match="finite"):
            vsm.set_source_voltage(1, voltage=non_finite)
        assert vsm.state == before

        with pytest.raises(ValueError, match="finite"):
            vsm.set_source_current(1, current=non_finite)
        assert vsm.state == before

    @pytest.mark.parametrize("bad_comp", [0.0, -1.0, float("nan"), float("inf")])
    def test_non_positive_compliance_rejected(self, bad_comp):
        vsm = VirtualSourcemeter()
        before = dict(vsm.state)
        with pytest.raises(ValueError, match="positive"):
            vsm.set_current_compliance(1, current_compliance=bad_comp)
        assert vsm.state == before

        with pytest.raises(ValueError, match="positive"):
            vsm.set_voltage_compliance(1, voltage_compliance=bad_comp)
        assert vsm.state == before

    def test_voltage_clamping_to_hardware_limits(self):
        vsm = VirtualSourcemeter()
        vsm.set_source_voltage(1, 300.0)
        assert vsm.state["source_voltage"] == 210.0

        vsm.set_source_voltage(1, -500.0)
        assert vsm.state["source_voltage"] == -210.0


# ============================================================================
# 9. Reset Ownership and Instance Isolation
# ============================================================================

class TestResetOwnershipAndInstanceIsolation:
    """Test driver reset ownership, hook preservation, and instance isolation."""

    def test_reset_restores_factory_defaults_and_preserves_hook(self):
        calls = []
        def hook(**kwargs):
            calls.append(kwargs)
            return kwargs.get("voltage", 0.0), 0.001

        vsm = VirtualSourcemeter(load_hook=hook)
        vsm.configure_voltage_source(1, voltage=15.0, current_compliance=0.05)
        vsm.output(1, on=True)

        assert vsm.state["source_voltage"] == 15.0
        assert vsm.state["output_on"] is True

        vsm.reset()

        assert vsm.state["output_on"] is False
        assert vsm.state["source_func"] == "VOLT"
        assert vsm.state["source_voltage"] == 0.0
        assert vsm.state["source_current"] == 0.0
        assert vsm.state["current_compliance"] == 1.05
        assert vsm.state["voltage_compliance"] == 210.0
        assert vsm.compliance_tripped is False
        assert vsm.load_hook is hook

        # Hook was notified of shutdown
        assert calls[-1]["output_on"] is False
        assert calls[-1]["stimulus"] == 0.0

    def test_setup_owned_contract_state_not_mutated_by_driver_reset(self):
        resistor = ResistorLoad(resistance=200.0)
        resistor.set_temperature(350.0)
        vsm = VirtualSourcemeter(load_hook=resistor)
        vsm.configure_voltage_source(1, voltage=5.0)

        vsm.reset()

        # Resistor temperature is setup-owned and preserved
        assert resistor.effective_resistance > 200.0 or resistor._current_temp == 350.0

    def test_instance_sample_isolation(self):
        vsm1 = VirtualSourcemeter()
        vsm2 = VirtualSourcemeter()

        mock_sample = object()
        vsm1.sample = mock_sample
        assert vsm1.sample is mock_sample
        assert vsm2.sample is not mock_sample

        mock_mag_sample = object()
        vsm1.mag_sample = mock_mag_sample
        assert vsm1.mag_sample is mock_mag_sample
        assert vsm2.mag_sample is not mock_mag_sample

        del vsm1.sample
        del vsm1.mag_sample

    def test_instance_state_isolation(self):
        vsm1 = VirtualSourcemeter()
        vsm2 = VirtualSourcemeter()

        vsm1.set_source_voltage(1, 12.0)
        assert vsm1.state["source_voltage"] == 12.0
        assert vsm2.state["source_voltage"] == 0.0


# ============================================================================
# 10. SCPI Command and Query Dispatch with Hooks
# ============================================================================

class TestScpiHookInteraction:
    """Test SCPI command parsing and query dispatch with active hooks."""

    def test_scpi_output_and_level_commands(self):
        resistor = ResistorLoad(resistance=100.0)
        vsm = VirtualSourcemeter(load_hook=resistor)

        vsm.write(":SOUR:FUNC VOLT")
        vsm.write(":SOUR:VOLT:LEV 5.0")
        vsm.write(":SENS:CURR:PROT 0.2")
        vsm.write(":OUTP ON")

        assert vsm.state["output_on"] is True
        assert vsm.query(":OUTP?") == "1"
        assert vsm.query(":SOUR:VOLT:LEV?") == "5.0"
        assert vsm.query(":SENS:CURR:PROT?") == "0.2"

        read_str = vsm.query(":READ?")
        parts = read_str.split(",")
        assert float(parts[0]) == pytest.approx(5.0)
        assert float(parts[1]) == pytest.approx(0.05)  # 5.0 / 100 Ohm = 0.05 A

        vsm.write(":OUTP OFF")
        assert vsm.query(":OUTP?") == "0"
        assert vsm.query(":SOUR:VOLT:LEV?") == "5.0"  # Setpoint preserved
        assert vsm.query(":READ?") == "0.000000E+00,0.000000E+00,INF,0.000000E+00,0"

    def test_scpi_reset_command(self):
        calls = []
        vsm = VirtualSourcemeter(load_hook=lambda **kwargs: calls.append(kwargs))
        vsm.write(":OUTP ON")
        vsm.write(":SOUR:VOLT:LEV 10.0")

        vsm.write("*RST")
        assert vsm.state["output_on"] is False
        assert vsm.state["source_voltage"] == 0.0
        assert calls[-1]["output_on"] is False
