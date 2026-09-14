"""
Consolidated DAQ Category Tests.

Covers:
- Base class, channel and range declarations, autodetect IDs
- Automatic discovery of all DAQ drivers
- VirtualDaq operations, AI/AO/DIO configuration, waveform generation, and trigger pulses
- Physical driver configuration (USB231, USB1208HS capability scaling and range normalization)
- Generic notebook smoke and method conformance
- Trigger pulse dispatch, timing modes (software vs hardware timer), cancellation, and cleanup
- Emulator trigger pulse integration (DaqAsAwg)
"""

import json
import inspect
from pathlib import Path
import threading
from types import SimpleNamespace
from unittest.mock import Mock, call
import pytest
from piec.drivers.daq.daq import Daq
from piec.drivers.daq.virtual_daq import VirtualDaq
from piec.drivers.daq.usb231 import USB231
from piec.drivers.daq.usb1208hs import USB1208HS
from piec.drivers.emulators.daq_to_awg import DaqAsAwg
import importlib
from tests.support.transports import create_test_driver
from tests.support.driver_contracts import DriverCase, physical, virtual, case_for, assert_driver_contract
from tests.support.discovery import discover_driver_classes, discover_instrument_categories
from tests.support.discovery import assert_all_drivers_registered

def analog_input(cls):
    def make(monkeypatch):
        if cls is VirtualDaq:
            instrument = cls()
            instrument.state['ai_values'][0] = 1.25
        else:
            # Replace only the vendor boundary. Channel/range validation and
            # the concrete driver's read_AI implementation still execute.
            module = importlib.import_module(cls.__module__)
            monkeypatch.setattr(module, 'ULRange', SimpleNamespace(BIP10VOLTS=10))
            instrument = create_test_driver(cls, board_num=7,
                                            ul=SimpleNamespace(v_in=Mock(return_value=1.25)),
                                            _ai_mode='se', _ai_ranges={})
        return instrument
    return make

# Independent device responses and expectations; discovery supplies the test inventory.
CASES = [DriverCase(cls, analog_input(cls), lambda inst: inst.read_AI(0), 1.25)
            for cls in (VirtualDaq, USB231, USB1208HS)]



ROOT = Path(__file__).resolve().parents[2]

ALL_DAQ_DRIVERS = discover_driver_classes()["daq"]

NOTEBOOK_DRIVER_METHODS = [
    "idn",
    "reset",
    "clear",
    "error",
    "wait",
    "self_test",
    "operation_complete",
    "initialize",
    "set_AI_channel",
    "set_AI_range",
    "set_AI_sample_rate",
    "configure_AI_channel",
    "read_AI",
    "read_AI_scan",
    "quick_read",
    "read_data",
    "set_AO_channel",
    "set_AO_range",
    "set_AO_sample_rate",
    "configure_AO_channel",
    "write_AO",
    "write_waveform_scan",
    "stop_output",
    "set_DIO_channel",
    "set_DIO_mode",
    "configure_DO_channel",
    "configure_DI_channel",
    "write_DO",
    "read_DI",
    "set_input_mode",
    "close",
]


class DigitalDaq(Daq):
    dio_channel = [0, 1]
    ao_channel = [0]
    ao_sample_rate = (1, 1000)

    def __init__(self):
        self.check_params = False
        self.events = []

    def set_DIO_mode(self, channel, mode):
        self.events.append(('mode', channel, mode))

    def write_DO(self, channel, data):
        self.events.append(('write', channel, data))


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr('piec.drivers.daq.daq.time.sleep', lambda duration: None)


# ============================================================================
# 1. Base Class & Driver Inventory Conformance
# ============================================================================

class TestDaqDiscovery:
    """Verify that all advertised and discovered DAQ drivers conform to standards."""

    def test_discovery_and_registration(self):
        assert_all_drivers_registered('daq', [case.cls for case in CASES])

    @pytest.mark.parametrize("driver_cls", ALL_DAQ_DRIVERS)
    def test_inherits_from_daq(self, driver_cls):
        assert issubclass(driver_cls, Daq)

    def test_base_daq_ranges_use_the_standard_list_of_tuples_shape(self):
        assert Daq.ai_range == [(None, None)]
        assert Daq.ao_range == [(None, None)]

    def test_usb1208hs_one_driver_registers_all_three_models(self):
        assert USB1208HS.AUTODETECT_ID == [
            "USB-1208HS",
            "USB-1208HS-2AO",
            "USB-1208HS-4AO",
        ]

    def test_usb231_declares_autodetect_id(self):
        assert hasattr(USB231, "AUTODETECT_ID")
        assert USB231.AUTODETECT_ID == "USB-231"


# ============================================================================
# 2. VirtualDaq Contract Tests
# ============================================================================

class TestVirtualDaqContract:
    """Verify VirtualDaq state transitions, configuration, IO, and pulse dispatch."""

    @pytest.fixture
    def vdaq(self):
        return VirtualDaq()

    def test_initial_state(self, vdaq):
        assert hasattr(vdaq, "ai_channel")
        assert hasattr(vdaq, "ao_channel")
        assert hasattr(vdaq, "dio_channel")

    def test_analog_io(self, vdaq):
        vdaq.configure_AO_channel(0, range=(-10.0, 10.0), sample_rate=1000)
        vdaq.write_AO(0, 3.3)
        assert vdaq.state["ao_values"][0] == pytest.approx(3.3)

        vdaq.configure_AI_channel(0, range=(-10.0, 10.0), sample_rate=1000)
        val = vdaq.read_AI(0)
        assert isinstance(val, (int, float))

    def test_digital_io(self, vdaq):
        vdaq.set_DIO_mode(0, "o")
        vdaq.write_DO(0, 1)
        assert vdaq.state["dio_values"][0] == 1
        vdaq.write_DO(0, 0)
        assert vdaq.state["dio_values"][0] == 0

    def test_trigger_pulse_simulation(self, vdaq):
        result = vdaq.send_trigger_pulse(0, 0.001, active_high=True)
        assert result["timing"] == "simulated"
        assert len(vdaq.state["trigger_pulses"]) > 0


# ============================================================================
# 3. Physical DAQ Driver Capabilities & Notebook Conformance
# ============================================================================

class TestPhysicalDaqDrivers:
    """Verify USB231 and USB1208HS offline capability configuration and notebook contract."""

    def test_usb1208hs_configures_ao_channels_from_idn(self):
        expected_channels = {
            "Measurement_Computing,USB-1208HS,s/n_unknown,ver_UL": [],
            "Measurement_Computing,USB-1208HS-2AO,s/n_unknown,ver_UL": [0, 1],
            "Measurement_Computing,USB-1208HS-4AO,s/n_unknown,ver_UL": [0, 1, 2, 3],
        }

        for identity, channels in expected_channels.items():
            daq = object.__new__(USB1208HS)
            daq._configure_model_capabilities(identity)
            assert daq.ao_channel == channels
            assert daq.ao_range == ([(-10.0, 10.0)] if channels else [])

    @pytest.mark.parametrize("driver_class", [USB231, USB1208HS])
    def test_daq_notebook_methods_are_implemented_by_both_drivers(self, driver_class):
        base_methods = {
            inspect.unwrap(getattr(Daq, method))
            for method in NOTEBOOK_DRIVER_METHODS
            if hasattr(Daq, method)
        }

        for method in NOTEBOOK_DRIVER_METHODS:
            implementation = inspect.unwrap(getattr(driver_class, method))
            assert implementation not in base_methods, (
                f"{driver_class.__name__}.{method} still resolves to a Daq stub"
            )

    @pytest.mark.parametrize("driver_class", [USB231, USB1208HS])
    def test_daq_range_normalization_uses_minimum_maximum_pairs(self, driver_class):
        assert driver_class._normalize_range((-10, 10)) == (-10.0, 10.0)
        with pytest.raises(ValueError, match=r"two-value \(minimum, maximum\) pair"):
            driver_class._normalize_range(10)

    @pytest.mark.parametrize(
        ("driver_class", "identity"),
        [
            (USB231, None),
            (USB1208HS, "Measurement_Computing,USB-1208HS,s/n_unknown,ver_UL"),
            (USB1208HS, "Measurement_Computing,USB-1208HS-2AO,s/n_unknown,ver_UL"),
            (USB1208HS, "Measurement_Computing,USB-1208HS-4AO,s/n_unknown,ver_UL"),
        ],
    )
    def test_notebook_range_configuration_is_shared_by_both_drivers(
        self, driver_class, identity
    ):
        daq = object.__new__(driver_class)
        daq._ai_sample_rates = {}
        daq._ao_sample_rates = {}

        if driver_class is USB1208HS:
            daq._configure_model_capabilities(identity)
            daq._ai_mode = "se"
            daq.ai_channel = list(range(8))
            daq.ai_range = list(daq._AI_RANGES_BY_MODE["se"])
            daq._ai_ranges = {}

        ai_channel = daq.ai_channel[0] if daq.ai_channel else None
        if ai_channel is not None:
            ai_range = daq.ai_range[0]
            daq.configure_AI_channel(ai_channel, range=ai_range, sample_rate=1000)

        ao_channel = daq.ao_channel[0] if daq.ao_channel else None
        if ao_channel is not None:
            ao_range = daq.ao_range[0]
            daq.configure_AO_channel(ao_channel, range=ao_range, sample_rate=1000)

    def test_generic_daq_notebook_is_model_independent_and_output_safe(self):
        notebook_path = ROOT / "src" / "piec" / "drivers" / "daq" / "daq_test.ipynb"
        notebook = json.loads(notebook_path.read_text(encoding="utf-8"))
        source = "\n".join("".join(cell.get("source", [])) for cell in notebook["cells"])

        assert "autodetect(verbose=True)" in source
        assert "USB231" not in source
        assert "daq.set_AI_channel(AI_CHANNEL)" in source
        assert "daq.configure_AI_channel(" in source
        assert "daq.read_AI_scan(" in source


# ============================================================================
# 4. Trigger Pulse Dispatch, Hardware Sequencing, and Cleanup
# ============================================================================

class TestDaqTriggerPulses:
    """Verify trigger pulse dispatching, timing boundaries, cancellation, and recovery."""

    @pytest.fixture
    def timer(self, monkeypatch):
        monkeypatch.setattr(
            "piec.drivers.daq.usb1208hs.TimerIdleState",
            SimpleNamespace(LOW=0, HIGH=1),
        )
        daq = object.__new__(USB1208HS)
        daq.check_params = False
        daq.board_num = 3
        daq.ul = Mock()
        daq.ul.pulse_out_start.return_value = (400.0, 0.5, 0.0001)
        daq._wait_trigger_pulse = Mock()
        return daq

    @pytest.mark.parametrize("active_high,levels", [(True, [0, 1, 0]), (False, [1, 0, 1])])
    def test_software_sequence(self, active_high, levels):
        daq = DigitalDaq()
        result = daq.send_trigger_pulse(1, 0.001, active_high)
        assert daq.events == [("mode", 1, "o")] + [("write", 1, level) for level in levels]
        assert result["timing"] == "software"
        assert result["programmed_pulse_width"] is None

    @pytest.mark.parametrize(
        "changes,error",
        [
            ({"channel": 9}, ValueError),
            ({"channel": True}, ValueError),
            ({"pulse_width": 0}, ValueError),
            ({"pulse_width": -1}, ValueError),
            ({"pulse_width": float("nan")}, ValueError),
            ({"pulse_width": float("inf")}, ValueError),
            ({"pulse_width": True}, ValueError),
            ({"pulse_width": 61}, ValueError),
            ({"active_high": 1}, ValueError),
            ({"resource": "timer"}, NotImplementedError),
            ({"require_hardware_timing": True}, NotImplementedError),
        ],
    )
    def test_invalid_request_never_touches_outputs(self, changes, error):
        daq = DigitalDaq()
        kwargs = dict(channel=0, pulse_width=0.001)
        kwargs.update(changes)
        with pytest.raises(error):
            daq.send_trigger_pulse(**kwargs)
        assert daq.events == []

    def test_base_stubs_do_not_advertise_pulses(self):
        daq = object.__new__(Daq)
        daq.check_params = False
        daq.dio_channel = [0]
        with pytest.raises(NotImplementedError):
            daq.send_trigger_pulse(0, 0.001)

    def test_failed_active_write_still_restores_idle(self):
        daq = DigitalDaq()
        daq.write_DO = Mock(side_effect=[None, OSError("USB failed"), None])
        with pytest.raises(OSError, match="USB failed"):
            daq.send_trigger_pulse(0, 0.001)
        assert daq.write_DO.call_args_list == [call(0, 0), call(0, 1), call(0, 0)]

    def test_cancelled_before_start_produces_no_edges(self):
        daq = DigitalDaq()
        cancel = threading.Event()
        cancel.set()
        with pytest.raises(InterruptedError):
            daq.send_trigger_pulse(0, 0.001, cancel_event=cancel)
        assert daq.events == []

    def test_cancelled_active_pulse_restores_idle(self):
        daq = DigitalDaq()
        cancel = Mock()
        cancel.wait.side_effect = [False, True]
        with pytest.raises(InterruptedError):
            daq.send_trigger_pulse(0, 0.001, cancel_event=cancel)
        assert daq.events[-1] == ("write", 0, 0)

    @pytest.mark.parametrize("active_high,idle", [(True, 0), (False, 1)])
    def test_timer_single_pulse_and_actual_period(self, timer, active_high, idle):
        result = timer.send_trigger_pulse(
            0,
            0.001,
            active_high,
            resource="timer",
            require_hardware_timing=True,
        )
        timer.ul.pulse_out_start.assert_called_once_with(
            3, 0, 500.0, 0.5, pulse_count=1, initial_delay=0, idle_state=idle
        )
        assert timer._wait_trigger_pulse.call_args.args[0] == pytest.approx(0.0026)
        timer.ul.pulse_out_stop.assert_called_once_with(3, 0)
        timer.ul.d_bit_out.assert_not_called()
        assert result["timing"] == "hardware"
        assert result["programmed_pulse_width"] == pytest.approx(0.00125)

    @pytest.mark.parametrize("failure", ["start", "wait", "bad_return"])
    def test_timer_failure_stops_without_software_retry(self, timer, failure):
        if failure == "start":
            timer.ul.pulse_out_start.side_effect = OSError("start")
        elif failure == "wait":
            timer._wait_trigger_pulse.side_effect = [None, InterruptedError("cancel")]
        else:
            timer.ul.pulse_out_start.return_value = (0, 0.5, 0)
        with pytest.raises((OSError, ValueError)):
            timer.send_trigger_pulse(0, 0.001, resource="timer")
        timer.ul.pulse_out_stop.assert_called_once_with(3, 0)
        timer.ul.d_bit_out.assert_not_called()

    def test_usb231_uses_digital_fallback(self, monkeypatch):
        monkeypatch.setattr("piec.drivers.daq.usb231.DigitalPortType", SimpleNamespace(AUXPORT=7))
        monkeypatch.setattr("piec.drivers.daq.usb231.DigitalIODirection", SimpleNamespace(OUT=1, IN=0))
        daq = object.__new__(USB231)
        daq.check_params = False
        daq.board_num = 2
        daq.ul = Mock()
        result = daq.send_trigger_pulse(0, 0.001)
        assert result["timing"] == "software"
        assert daq.ul.d_bit_out.call_args_list == [call(2, 7, 0, x) for x in (0, 1, 0)]
        daq.ul.pulse_out_start.assert_not_called()

    def test_emulator_generic_dispatch_and_virtual_history(self):
        daq = VirtualDaq()
        awg = DaqAsAwg(daq)
        awg.configure_trigger_output(1, 0.001)
        assert "trigger_pulses" not in daq.state
        original_ao = dict(daq.state["ao_values"])
        result = awg.output_trigger()
        assert result["timing"] == "simulated"
        assert daq.state["trigger_pulses"] == [result]
        assert daq.state["dio_values"][1] == 0
        assert daq.state["ao_values"] == original_ao
        with pytest.raises(NotImplementedError):
            awg.configure_trigger_output(1, 0.001, require_hardware_timing=True)

    def test_emulator_timer_dispatch(self, timer):
        awg = DaqAsAwg(timer, check_params=True)
        awg.configure_trigger_output(0, 0.001, resource="timer", require_hardware_timing=True)
        timer.ul.pulse_out_start.assert_not_called()
        assert awg.output_trigger()["timing"] == "hardware"
        timer.ul.pulse_out_start.assert_called_once()


@pytest.mark.parametrize("driver_cls", discover_driver_classes()["daq"], ids=lambda cls: cls.__name__)
def test_driver_contract(driver_cls):
    assert_driver_contract(driver_cls, discover_instrument_categories()["daq"])


@pytest.mark.parametrize("driver_cls", discover_driver_classes()["daq"], ids=lambda cls: cls.__name__)
def test_driver_behavior(driver_cls, monkeypatch):
    case_for(driver_cls, CASES).check(monkeypatch, discover_instrument_categories()["daq"])
