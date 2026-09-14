"""
Consolidated Oscilloscope Category Tests.

Covers:
- Base class, channel declaration, class attributes, autodetect IDs
- Automatic discovery of all Oscilloscope drivers and adapters
- VirtualScope configuration, waveform_hook injection, validation, and data extraction
- Physical driver SCPI commands (Tektronix TDS2000, Rigol DS1000Z, Keysight DSOX3024a,
  Agilent DSOX5000, LeCroy SDA6020, Tektronix TDS6604)
- DaqAsOscilloscope adapter wrapping VirtualDaq
"""

import math
from unittest.mock import Mock
import numpy as np
import pandas as pd
import pytest
from piec.drivers.oscilloscope.oscilloscope import Oscilloscope
from piec.drivers.oscilloscope.virtual_oscilloscope import VirtualScope
from piec.drivers.oscilloscope.tektronix_tds2000 import TektronixTDS2000
from piec.drivers.oscilloscope.rigol_ds1000z import RigolDS1000Z
from piec.drivers.oscilloscope.k_dsox3024a import KeysightDSOX3024a
from piec.drivers.oscilloscope.agilent_dsox5000 import AgilentDSOX5000
from piec.drivers.oscilloscope.lecroy_sda6020 import LeCroySDA6020
from piec.drivers.oscilloscope.tektronix_tds6604 import TDS6604
from piec.drivers.emulators.daq_to_oscilloscope import DaqAsOscilloscope
from piec.drivers.daq.virtual_daq import VirtualDaq
from tests.support.discovery import assert_all_drivers_registered
from tests.support.transports import ScriptedTransport, create_test_driver
from dataclasses import dataclass
import struct
from tests.support.driver_contracts import case_for, assert_driver_contract
from tests.support.discovery import discover_driver_classes

@dataclass(frozen=True)
class ScopeCase:
    cls: type
    responses: dict
    columns: tuple = ("Time", "Voltage")
    time: tuple = (-.25, 0., .25)
    voltage: tuple = (1., 2., 4.)

    def make(self):
        if self.cls is VirtualScope:
            return self.cls(waveform_hook=lambda: {"time": self.time, "voltage": self.voltage})
        if self.cls is DaqAsOscilloscope:
            daq = VirtualDaq()
            daq.read_AI_scan = Mock(return_value=list(self.voltage))
            scope = self.cls(daq)
            scope.set_acquisition_points(3)
            scope.set_horizontal_scale(tdiv=.075)
            return scope
        return create_test_driver(self.cls, responses=self.responses, strict=True)


# Independent example: ADC [0, 2, 6], gain .5 V/count, origin 1 V;
# three samples .25 s apart starting at -.25 s. Nonzero origins catch
# parsers that omit offsets; non-unit gain catches unscaled ADC returns.
TEK_RESPONSES = {"WFMPRE:YMULT?": .5, "WFMPRE:YOFF?": 0,
                 "WFMPRE:YZERO?": 1., "WFMPRE:XINCR?": .25,
                 "WFMPRE:XZERO?": -.25, "CURVe?": [0, 2, 6]}
PREAMBLE = "0,0,3,1,0.25,-0.25,0,0.5,1,0"
descriptor = bytearray(346)
struct.pack_into("<f", descriptor, 156, .5)
struct.pack_into("<f", descriptor, 160, -1.)
struct.pack_into("<f", descriptor, 176, .25)
struct.pack_into("<d", descriptor, 180, -.25)

SCOPE_CASES = [
    ScopeCase(VirtualScope, {}),
    ScopeCase(TektronixTDS2000, TEK_RESPONSES),
    ScopeCase(RigolDS1000Z, {":WAVeform:PREamble?": PREAMBLE, ":WAVeform:DATA?": [0, 2, 6]}),
    ScopeCase(KeysightDSOX3024a, {":WAVeform:PREamble?": PREAMBLE, "WAVeform:DATA?": [0, 2, 6]}),
    ScopeCase(AgilentDSOX5000, {":WAVeform:PREamble?": PREAMBLE, "WAVeform:DATA?": [0, 2, 6]}),
    ScopeCase(LeCroySDA6020, {"C1:WF? DESC": bytes(descriptor), "C1:WF? DAT1": [0, 2, 6]}),
    ScopeCase(TDS6604, dict(TEK_RESPONSES, **{"HORizontal:RECOrdlength?": 3}), ("Time", "Voltage_CH1")),
    ScopeCase(DaqAsOscilloscope, {}, ("Time", "Channel 1"), (0., .25, .5)),
]



ALL_SCOPE_DRIVERS = discover_driver_classes()["oscilloscope"]


@pytest.mark.parametrize("driver_cls", ALL_SCOPE_DRIVERS, ids=lambda cls: cls.__name__)
def test_scope_waveform_contract(driver_cls):
    case = case_for(driver_cls, SCOPE_CASES)
    scope = case.make()
    assert_driver_contract(scope, Oscilloscope)
    data = scope.get_data()
    assert isinstance(data, pd.DataFrame)
    assert tuple(data.columns) == case.columns
    assert len(data) == len(case.time)
    np.testing.assert_allclose(data.iloc[:, 0], case.time, rtol=1e-10, atol=1e-15)
    np.testing.assert_allclose(data.iloc[:, 1], case.voltage, rtol=1e-10, atol=1e-15)

PHYSICAL_SCOPE_DRIVERS = [
    TektronixTDS2000,
    RigolDS1000Z,
    KeysightDSOX3024a,
    AgilentDSOX5000,
    LeCroySDA6020,
    TDS6604,
]


# ============================================================================
# 1. Base Class & Driver Inventory Conformance
# ============================================================================

class TestOscilloscopeDiscovery:
    """Verify that all advertised and discovered scope drivers conform to standards."""

    def test_discovery_and_registration(self):
        """All discovered Oscilloscope subclasses must be registered and covered."""
        assert_all_drivers_registered('oscilloscope', [case.cls for case in SCOPE_CASES])

    @pytest.mark.parametrize("driver_cls", ALL_SCOPE_DRIVERS)
    def test_inherits_from_oscilloscope(self, driver_cls):
        """Every scope driver must inherit from Oscilloscope."""
        assert issubclass(driver_cls, Oscilloscope)

    @pytest.mark.parametrize("driver_cls", ALL_SCOPE_DRIVERS)
    def test_declares_channel_attribute(self, driver_cls):
        """Every scope driver must define channel attribute."""
        assert hasattr(driver_cls, "channel")
        assert len(driver_cls.channel) >= 1

    @pytest.mark.parametrize("driver_cls", PHYSICAL_SCOPE_DRIVERS)
    def test_hardware_drivers_declare_autodetect_id(self, driver_cls):
        """Hardware drivers must declare an AUTODETECT_ID string."""
        assert hasattr(driver_cls, "AUTODETECT_ID")
        autoid = driver_cls.AUTODETECT_ID
        assert isinstance(autoid, (str, list))


# ============================================================================
# 2. VirtualScope Contract Tests
# ============================================================================

class TestVirtualScopeContract:
    """Verify VirtualScope state transitions, hook injection, and data retrieval."""

    @pytest.fixture
    def v_scope(self):
        return VirtualScope()

    def test_initial_state(self, v_scope):
        state = v_scope.get_state()
        assert 1 in state["channels_on"]
        assert state["channels_on"][1] is True
        assert state["acquisition_channel"] == 1
        assert state["tdiv"] == 1e-3
        assert state["running"] is False
        assert state["armed"] is False

    def test_channel_configuration(self, v_scope):
        v_scope.toggle_channel(1, False)
        assert v_scope.state["channels_on"][1] is False
        v_scope.toggle_channel(1, True)
        assert v_scope.state["channels_on"][1] is True

        v_scope.set_vertical_scale(1, vdiv=0.5, y_range=4.0)
        assert v_scope.state["vdiv"][1] == 0.5
        assert v_scope.state["y_range"][1] == 4.0

        v_scope.set_vertical_position(1, y_position=1.5)
        assert v_scope.state["y_position"][1] == 1.5

        v_scope.set_input_coupling(1, "AC")
        assert v_scope.state["input_coupling"][1] == "AC"

        v_scope.set_probe_attenuation(1, 10.0)
        assert v_scope.state["probe_attenuation"][1] == 10.0

    def test_horizontal_and_trigger_configuration(self, v_scope):
        v_scope.configure_horizontal(tdiv=2e-3, x_range=16e-3, x_position=1e-3)
        assert v_scope.state["tdiv"] == 2e-3
        assert v_scope.state["x_range"] == 16e-3
        assert v_scope.state["x_position"] == 1e-3

        v_scope.configure_trigger(
            trigger_source=2,
            trigger_level=1.2,
            trigger_slope="NEG",
            trigger_mode="EDGE",
        )
        assert v_scope.state["trigger_source"] == "CHAN2"
        assert v_scope.state["trigger_level"] == 1.2
        assert v_scope.state["trigger_slope"] == "NEG"
        assert v_scope.state["trigger_mode"] == "EDGE"

        v_scope.set_trigger_sweep("NORM")
        assert v_scope.state["trigger_sweep"] == "NORM"

    def test_acquisition_controls(self, v_scope):
        v_scope.configure_acquisition(channel=2, acquisition_mode="PEAK", acquisition_points=500)
        assert v_scope.state["acquisition_channel"] == 2
        assert v_scope.state["acquisition_mode"] == "PEAK"
        assert v_scope._requested_acquisition_points == 500

        v_scope.toggle_acquisition(run=True)
        assert v_scope.state["running"] is True
        v_scope.toggle_acquisition(run=False)
        assert v_scope.state["running"] is False

    def test_quick_read(self, v_scope):
        data = v_scope.quick_read()
        assert isinstance(data, np.ndarray)
        assert data.dtype == np.uint8
        assert len(data) > 0

    def test_get_data_with_waveform_hook_tuple(self, v_scope):
        times = np.linspace(0, 1e-3, 100)
        voltages = np.sin(2 * np.pi * 1000 * times)
        v_scope.set_waveform_hook(lambda ch: (voltages, times))

        df = v_scope.get_data(channel=1)
        assert isinstance(df, pd.DataFrame)
        assert "Time" in df.columns
        assert "Voltage" in df.columns
        assert len(df) == 100
        assert np.allclose(df["Voltage"], voltages)

    def test_get_data_with_waveform_hook_dict(self, v_scope):
        times = [0.0, 0.5, 1.0]
        voltages = [1.0, 2.0, 3.0]
        v_scope.set_waveform_hook(lambda ch: {"Time": times, "Voltage": voltages})

        df = v_scope.get_data()
        assert len(df) == 3
        assert list(df["Voltage"]) == [1.0, 2.0, 3.0]

    def test_get_data_with_waveform_hook_dataframe(self, v_scope):
        raw_df = pd.DataFrame({"Time": [0.0, 1.0], "Voltage": [5.0, 6.0]})
        v_scope.set_waveform_hook(lambda ch: raw_df)

        df = v_scope.get_data()
        assert len(df) == 2
        assert list(df["Voltage"]) == [5.0, 6.0]

    def test_get_data_without_hook_or_sample_raises(self, v_scope):
        v_scope.sample = None
        with pytest.raises(RuntimeError, match="no injected waveform_hook and no shared sample fallback"):
            v_scope.get_data()

    def test_invalid_channel_raises(self, v_scope):
        with pytest.raises((ValueError, TypeError)):
            v_scope.get_data(channel=99)
        with pytest.raises(TypeError):
            v_scope.get_data(channel="invalid")

    def test_declared_units(self, v_scope):
        assert v_scope.declared_units == {"voltage": "V", "time": "s"}


# ============================================================================
# 3. Physical Oscilloscope Drivers SCPI / Protocol Tests
# ============================================================================

class TestPhysicalOscilloscopes:
    """Verify SCPI command generation across physical oscilloscope drivers."""

    def test_tektronix_tds2000_commands(self):
        scope = create_test_driver(TektronixTDS2000)
        scope.autoscale()
        assert "AUTOSet EXECute" in scope.instrument.writes

        scope.toggle_channel(1, True)
        assert "SELect:CH1 ON" in scope.instrument.writes

        scope.set_vertical_scale(1, vdiv=0.5)
        assert "CH1:SCAle 0.5" in scope.instrument.writes

        scope.set_vertical_scale(1, y_range=4.0)
        assert "CH1:SCAle 0.5" in scope.instrument.writes

        scope.set_input_coupling(1, "dc")
        assert "CH1:COUPling dc" in scope.instrument.writes

        scope.set_channel_impedance(1, "1M")
        with pytest.raises(ValueError):
            scope.set_channel_impedance(1, "50")

        scope.set_horizontal_scale(tdiv=1e-3)
        assert "HORizontal:MAIn:SCAle 0.001" in scope.instrument.writes

        scope.set_horizontal_scale(x_range=0.01)
        assert "HORizontal:MAIn:SCAle 0.001" in scope.instrument.writes

        scope.set_trigger_source(1)
        assert "TRIGger:MAIn:EDGE:SOURce CH1" in scope.instrument.writes

        scope.set_trigger_level(1.5)
        assert "TRIGger:MAIn:LEVel 1.5" in scope.instrument.writes

        scope.set_trigger_slope("POS")
        assert "TRIGger:MAIn:EDGE:SLOpe RISE" in scope.instrument.writes

        scope.set_trigger_slope("NEG")
        assert "TRIGger:MAIn:EDGE:SLOpe FALL" in scope.instrument.writes

        with pytest.raises(ValueError):
            scope.set_trigger_slope("INVALID")

        scope.set_acquisition_mode("NORM")
        assert "ACQuire:MODe SAMPLE" in scope.instrument.writes

        scope.toggle_acquisition(run=True)
        assert "ACQuire:STATE ON" in scope.instrument.writes

    def test_rigol_ds1000z_commands(self):
        scope = create_test_driver(RigolDS1000Z)
        scope.autoscale()
        assert ":AUToscale" in scope.instrument.writes

        scope.toggle_channel(1, True)
        assert ":CHANnel1:DISPlay 1" in scope.instrument.writes

        scope.set_vertical_scale(1, vdiv=0.2)
        assert ":CHANnel1:SCALe 0.2" in scope.instrument.writes

        scope.set_vertical_scale(1, y_range=1.6)
        assert ":CHANnel1:RANGe 1.6" in scope.instrument.writes

        # With 10x probe attenuation, settings up to 800V are valid; check_params must not reject y_range=160
        checked_scope = create_test_driver(RigolDS1000Z, check_params=True)
        checked_scope.set_vertical_scale(1, y_range=160)
        assert ":CHANnel1:RANGe 160" in checked_scope.instrument.writes

        scope.set_channel_impedance(1, "1M")
        with pytest.raises(ValueError):
            scope.set_channel_impedance(1, "50")

        scope.set_horizontal_scale(tdiv=5e-3)
        assert ":TIMebase:SCALe 0.005" in scope.instrument.writes

        scope.set_horizontal_scale(x_range=0.06)
        assert ":TIMebase:SCALe 0.005" in scope.instrument.writes

        scope.set_trigger_source(1)
        assert ":TRIGger:EDGE:SOURce CHAN1" in scope.instrument.writes

        scope.set_trigger_mode("EDGE")
        assert ":TRIGger:MODE EDGE" in scope.instrument.writes

        with pytest.raises(ValueError):
            scope.set_trigger_mode("INVALID")

        scope.set_trigger_sweep("AUTO")
        assert ":TRIGger:SWEep AUTO" in scope.instrument.writes

        scope.set_acquisition_mode("NORM")
        assert ":ACQuire:TYPE NORM" in scope.instrument.writes

        scope.toggle_acquisition(run=True)
        assert ":RUN" in scope.instrument.writes

    def test_keysight_dsox3024a_commands(self):
        scope = create_test_driver(KeysightDSOX3024a)
        scope.autoscale()
        assert ":AUToscale" in scope.instrument.writes

        scope.toggle_channel(1, True)
        assert ":CHANnel1:DISPlay 1" in scope.instrument.writes

        scope.set_vertical_scale(1, vdiv=1.0)
        assert ":CHANnel1:SCALe 1.0" in scope.instrument.writes

        scope.set_horizontal_scale(tdiv=2e-3)
        assert ":TIMebase:SCALe 0.002" in scope.instrument.writes

    def test_agilent_dsox5000_commands(self):
        scope = create_test_driver(AgilentDSOX5000)
        scope.autoscale()
        assert ":AUToscale" in scope.instrument.writes

        scope.toggle_channel(2, True)
        assert ":CHANnel2:DISPlay 1" in scope.instrument.writes

        scope.set_vertical_scale(2, vdiv=0.1)
        assert ":CHANnel2:SCALe 0.1" in scope.instrument.writes

    def test_lecroy_sda6020_commands(self):
        scope = create_test_driver(LeCroySDA6020)
        scope.toggle_channel(1, True)
        assert "C1:TRACE ON" in scope.instrument.writes

        scope.set_vertical_scale(1, vdiv=0.5)
        assert "C1:VDIV 0.5" in scope.instrument.writes

        scope.set_input_coupling(1, "DC")
        assert "C1:COUPLING D50" in scope.instrument.writes

        scope.set_input_coupling(1, "GND")
        assert "C1:COUPLING GND" in scope.instrument.writes

        with pytest.raises(ValueError):
            scope.set_input_coupling(1, "AC")

        scope.set_channel_impedance(1, "50")
        assert "C1:COUPLING D50" in scope.instrument.writes

        with pytest.raises(ValueError):
            scope.set_channel_impedance(1, "1M")

        scope.set_horizontal_scale(tdiv=1e-3)
        assert "TIME_DIV 0.001" in scope.instrument.writes

        scope.set_trigger_slope("POS")
        assert "C1:TRIG_SLOPE POS" in scope.instrument.writes

        with pytest.raises(ValueError):
            scope.set_trigger_slope("INVALID")

    @pytest.mark.parametrize("check_params", [False, True])
    def test_tds6604_impedance_requires_adapter_on_target_channel(self, check_params):
        scope = create_test_driver(TDS6604, check_params=check_params,
                                   responses={"CH1:PRObe:ID:TYPe?": "NONE",
                                              "CH2:PRObe:ID:TYPe?": "NONE"}, strict=True)
        with pytest.raises(ValueError, match="requires an external TCA-1MEG"):
            scope.set_channel_impedance(1, "1M")
        assert scope.instrument.writes == []

        scope.attach_adapter(1, "TCA-1MEG")
        scope.set_channel_impedance(1, "1M")
        assert scope.instrument.writes == ["CH1:IMPedance ONEMEG"]
        scope.instrument.writes.clear()
        with pytest.raises(ValueError, match="requires an external TCA-1MEG"):
            scope.set_channel_impedance(2, "1M")
        with pytest.raises(ValueError, match="not supported"):
            scope.set_channel_impedance(1, "INVALID")
        scope.detach_adapter(1)
        with pytest.raises(ValueError, match="requires an external TCA-1MEG"):
            scope.set_channel_impedance(1, "1M")
        assert scope.instrument.writes == []

        # Hardware-detected adapters must work without a manual registration too.
        scope.instrument.responses["CH1:PRObe:ID:TYPe?"] = "TCA-1MEG"
        scope.set_channel_impedance(1, "ONEMEG")
        scope.set_channel_impedance(2, "50")
        assert scope.instrument.writes == ["CH1:IMPedance ONEMEG", "CH2:IMPedance FIFTY"]

    def test_tektronix_tds6604_commands(self):
        scope = create_test_driver(TDS6604)
        scope.toggle_channel(1, True)
        assert "SELect:CH1 ON" in scope.instrument.writes

        scope.set_vertical_scale(1, vdiv=0.25)
        assert "CH1:SCAle 0.25" in scope.instrument.writes

        # Native input is 50 Ohm only; 1M without external adapter must raise ValueError
        scope.set_channel_impedance(1, "50")
        assert "CH1:IMPedance FIFTY" in scope.instrument.writes

        with pytest.raises(ValueError, match="native 50 Ohm input only.*TCA-1MEG"):
            scope.set_channel_impedance(1, "1M")

        # When external TCA-1MEG adapter is attached, 1M impedance switching succeeds
        scope.attach_adapter(1, "TCA-1MEG")
        scope.set_channel_impedance(1, "1M")
        assert "CH1:IMPedance ONEMEG" in scope.instrument.writes

        with pytest.raises(ValueError):
            scope.set_channel_impedance(1, "INVALID")

        scope.set_horizontal_scale(tdiv=5e-6)
        assert "HORizontal:MAIN:SCAle 5e-06" in scope.instrument.writes

        scope.set_acquisition_mode("NORM")
        assert "ACQuire:MODe SAMPLE" in scope.instrument.writes

        scope.set_trigger_slope("POS")
        assert "TRIGger:A:EDGE:SLOpe RISE" in scope.instrument.writes

        with pytest.raises(ValueError):
            scope.set_trigger_slope("INVALID")

        scope.set_trigger_mode("EDGE")
        assert "TRIGger:A:TYPe EDGE" in scope.instrument.writes

        scope.set_trigger_sweep("AUTO")
        assert "TRIGger:A:MODe AUTO" in scope.instrument.writes


# ============================================================================
# 4. DaqAsOscilloscope Adapter Tests
# ============================================================================

class TestDaqAsOscilloscopeAdapter:
    """Verify DaqAsOscilloscope adapter wrapping a VirtualDaq."""

    @pytest.fixture
    def daq_scope(self):
        vdaq = VirtualDaq()
        return DaqAsOscilloscope(daq_instance=vdaq)

    def test_initial_state_and_channels(self, daq_scope):
        assert hasattr(daq_scope, "channel")
        assert 1 in daq_scope.channel
        assert daq_scope._scope_state["acq_channel"] == 1

    def test_horizontal_configuration(self, daq_scope):
        daq_scope.set_horizontal_scale(tdiv=5e-3)
        assert daq_scope._scope_state["tdiv"] == 5e-3

        daq_scope.set_horizontal_position(1e-3)
        assert daq_scope._scope_state["x_pos"] == 1e-3

    def test_vertical_configuration(self, daq_scope):
        daq_scope.set_vertical_scale(1, vdiv=2.0)
        assert daq_scope._scope_state["channels"][1]["vdiv"] == 2.0

        daq_scope.set_input_coupling(1, "DC")
        assert daq_scope._scope_state["channels"][1]["coupling"] == "DC"

    def test_acquisition_configuration(self, daq_scope):
        daq_scope.set_acquisition_points(500)
        assert daq_scope._scope_state["points"] == 500

        daq_scope.set_acquisition_channel(1)
        assert daq_scope._scope_state["acq_channel"] == 1

    def test_get_data(self, daq_scope):
        df = daq_scope.get_data()
        assert isinstance(df, pd.DataFrame)
        assert "Time" in df.columns
        assert "Channel 1" in df.columns
        assert len(df) > 0


@pytest.mark.parametrize("driver_cls", ALL_SCOPE_DRIVERS, ids=lambda cls: cls.__name__)
def test_driver_contract(driver_cls):
    assert_driver_contract(driver_cls, Oscilloscope)
