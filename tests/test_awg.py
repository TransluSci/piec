"""
Consolidated Arbitrary Waveform Generator (AWG) Category Tests.

Covers physical drivers (via ScriptedTransport), virtual driver (VirtualAwg),
and DAQ emulator adapter (DaqAsAwg) across configuration, waveform, channel,
triggering, and safing operations.
"""

from __future__ import annotations

import inspect
from unittest.mock import Mock, patch

import numpy as np
import pytest

from piec.drivers.awg.agilent_33220a import Agilent33220A
from piec.drivers.awg.agilent_33500 import Agilent33500
from piec.drivers.awg.awg import Awg
from piec.drivers.awg.k_81150a import Keysight81150a
from piec.drivers.awg.rigol_dg1000 import RigolDG1000
from piec.drivers.awg.rigol_dg4000 import RigolDG4000
from piec.drivers.awg.sdg2000 import SDG2000X
from piec.drivers.awg.virtual_awg import VirtualAwg
from piec.drivers.emulators.daq_to_awg import DaqAsAwg
from tests.support.driver_cases import DRIVER_CASES
from tests.support.discovery import assert_all_drivers_registered
from tests.support.transports import ScriptedTransport, create_test_driver

# All discovered concrete implementations of Awg
REGISTERED_AWG_CLASSES = [case.cls for case in DRIVER_CASES['awg']]

PHYSICAL_AWG_CLASSES = [
    Agilent33220A,
    Agilent33500,
    Keysight81150a,
    RigolDG1000,
    RigolDG4000,
    SDG2000X,
]

PROFILES = [
    (Agilent33220A, None, 1, "TRIG", "BURS", "IMM", "BUS"),
    (Agilent33500, None, 2, "TRIG2", "SOUR2:BURS", "IMM", "BUS"),
    (RigolDG1000, "dg1000", 1, "TRIG", "BURS", "IMM", "BUS"),
    (RigolDG1000, "dg1000z", 2, "TRIG2", "SOUR2:BURS", "INT", "BUS"),
    (RigolDG4000, None, 2, "SOUR2:BURS:TRIG", "SOUR2:BURS", "INT", "MAN"),
]


# ============================================================================
# 1. Driver Discovery & Registration
# ============================================================================

def test_awg_driver_discovery_and_registration():
    """Ensure every discovered subclass of Awg is covered by registered cases."""
    assert_all_drivers_registered("awg", REGISTERED_AWG_CLASSES)


# ============================================================================
# 2. Public Interface & Contract Verification
# ============================================================================

class TestAwgCommonInterface:
    """Verify common method existence and signature expectations."""

    @pytest.mark.parametrize("cls", list(REGISTERED_AWG_CLASSES))
    def test_all_awg_classes_expose_required_methods(self, cls):
        for method_name in ("output_trigger", "configure_trigger", "output"):
            assert hasattr(cls, method_name), f"{cls.__name__} missing {method_name}"
            assert callable(getattr(cls, method_name)), f"{cls.__name__}.{method_name} must be callable"

    def test_output_trigger_is_public_member(self):
        assert hasattr(Awg, "output_trigger")
        assert callable(getattr(Awg, "output_trigger"))
        sig = inspect.signature(Awg.output_trigger)
        assert "self" in sig.parameters

    def test_configure_trigger_handles_optional_trigger_source(self):
        """configure_trigger applies trigger_source when provided and skips when None."""
        awg = create_test_driver(Keysight81150a)
        awg.configure_trigger(channel=1, trigger_source="EXT")
        assert awg.instrument.writes[-1] == ":ARM:SOUR1 EXT"

        awg.instrument.writes.clear()
        awg.configure_trigger(channel=1, trigger_source=None, trigger_level=0.5)
        assert ":ARM:SOUR1" not in awg.instrument.writes
        assert ":ARM:LEV 0.5" in awg.instrument.writes


# ============================================================================
# 3. Output Trigger Behavior Across Implementations
# ============================================================================

class TestAwgTriggerExecution:
    """Verify output_trigger dispatches correctly across physical, virtual, and adapter drivers."""

    def test_keysight_81150a_output_trigger(self):
        awg = create_test_driver(Keysight81150a)
        awg.output_trigger()
        assert awg.instrument.writes == [":TRIG"]

    def test_sdg2000x_output_trigger(self):
        awg = create_test_driver(SDG2000X)
        awg.output_trigger()
        assert awg.instrument.writes == ["C1:BTWV MTRIG"]

    @pytest.mark.parametrize(
        ("cls", "protocol"),
        [
            (Agilent33220A, None),
            (Agilent33500, None),
            (RigolDG1000, "dg1000z"),
            (RigolDG4000, None),
        ],
    )
    def test_software_trigger_is_single_bus_command(self, cls, protocol):
        awg = create_test_driver(cls, protocol=protocol)
        awg.output_trigger()
        assert awg.instrument.writes == ["*TRG"]

    def test_virtual_awg_output_trigger(self):
        vawg = VirtualAwg(simulation_points=50)
        vawg.sample.output_voltage = None
        vawg.sample.t = None
        vawg.sample.prep_points = None

        with patch.object(vawg, "write", wraps=vawg.write) as spy_write:
            vawg.output_trigger()
            spy_write.assert_called_once_with(":TRIG")

        assert vawg.sample.prep_points == 20
        assert isinstance(vawg.sample.t, np.ndarray)
        assert len(vawg.sample.t) == 70
        assert isinstance(vawg.sample.output_voltage, np.ndarray)
        assert len(vawg.sample.output_voltage) == 70
        assert np.any(vawg.sample.output_voltage != 0.0)

    def test_daq_as_awg_unconfigured_trigger_raises(self):
        mock_daq = Mock()
        mock_daq.ao_channel = [0, 1]
        mock_daq.ao_sample_rate = 10000
        adapter = DaqAsAwg(mock_daq)

        with pytest.raises(RuntimeError, match="configure_trigger_output"):
            adapter.output_trigger()

        with pytest.raises(NotImplementedError, match="analog playback"):
            adapter.configure_trigger(1, trigger_source="MAN", trigger_level=1.0)


# ============================================================================
# 4. Physical Model Trigger Command Regressions
# ============================================================================

class TestAwgPhysicalTriggerCommands:
    """Verify exact command formatting and parameter checking for SCPI drivers."""

    @pytest.mark.parametrize("check_params", [False, True])
    @pytest.mark.parametrize("cls,protocol,ch,trig,burst,internal,manual", PROFILES)
    def test_trigger_commands_and_omitted_settings(
        self, cls, protocol, ch, trig, burst, internal, manual, check_params
    ):
        awg = create_test_driver(cls, protocol=protocol, check_params=check_params)
        awg.configure_trigger(ch, trigger_source="MaN", trigger_slope="nEg", trigger_mode="EDGE")
        assert awg.instrument.writes == [
            f"{trig}:SOUR {manual}",
            f"{trig}:SLOP NEG",
            f"{burst}:MODE TRIG",
        ]
        awg.instrument.writes.clear()
        awg.configure_trigger(ch)
        assert awg.instrument.writes == []

        for value in ("INT", "IMM"):
            awg.set_trigger_source(ch, value)
            assert awg.instrument.writes[-1] == f"{trig}:SOUR {internal}"

        awg.set_trigger_source(ch, "BUS")
        assert awg.instrument.writes[-1] == f"{trig}:SOUR {manual}"

        awg.set_trigger_source(ch, "EXT")
        assert awg.instrument.writes[-1] == f"{trig}:SOUR EXT"

        awg.set_trigger_mode(ch, "LEV")
        assert awg.instrument.writes[-1] == f"{burst}:MODE GAT"

    @pytest.mark.parametrize("cls,protocol,ch,trig,burst,internal,manual", PROFILES)
    @pytest.mark.parametrize(
        "bad",
        [
            {"trigger_source": "EXT;*RST"},
            {"trigger_slope": "EITH"},
            {"trigger_mode": "nonsense"},
            {"trigger_function": "auto"},
            {"trigger_function": "sweep", "trigger_mode": "LEV"},
        ],
    )
    def test_invalid_configuration_writes_nothing(
        self, cls, protocol, ch, trig, burst, internal, manual, bad
    ):
        awg = create_test_driver(cls, protocol=protocol)
        args = {"trigger_source": "EXT", **bad}
        with pytest.raises(ValueError):
            awg.configure_trigger(ch, **args)
        assert awg.instrument.writes == []

    @pytest.mark.parametrize("cls,protocol,ch,trig,burst,internal,manual", PROFILES)
    @pytest.mark.parametrize("channel", [0, 3, True, "1", 1.5])
    def test_bad_channel_never_writes(
        self, cls, protocol, ch, trig, burst, internal, manual, channel
    ):
        awg = create_test_driver(cls, protocol=protocol)
        with pytest.raises(ValueError):
            awg.configure_trigger(channel, trigger_source="MAN")
        assert awg.instrument.writes == []

    def test_dg4000_sweep_has_its_own_trigger_subsystem(self):
        awg = create_test_driver(RigolDG4000)
        awg.configure_trigger(2, trigger_source="EXT", trigger_slope="POS", trigger_function="sweep")
        assert awg.instrument.writes == [
            "SOUR2:SWE:TRIG:SOUR EXT",
            "SOUR2:SWE:TRIG:SLOP POS",
        ]

    @pytest.mark.parametrize("level", [0.9, 2.0, 3.8])
    def test_33500_programmed_trigger_level(self, level):
        awg = create_test_driver(Agilent33500)
        awg.set_trigger_level(2, level)
        assert awg.instrument.writes == [f"TRIG2:LEV {level}"]

    @pytest.mark.parametrize("level", [0.8, 3.9, float("nan"), float("inf"), True, "2"])
    def test_invalid_trigger_level_prevents_even_source_write(self, level):
        awg = create_test_driver(Agilent33500)
        with pytest.raises(ValueError):
            awg.configure_trigger(2, trigger_source="EXT", trigger_level=level)
        assert awg.instrument.writes == []

    def test_33500_pulse_transition_programming(self):
        awg = create_test_driver(Agilent33500)
        awg.set_pulse_edge_time(2, 1e-7)
        assert awg.instrument.writes == [
            "SOUR2:FUNC:PULS:TRAN:LEAD 1e-07",
            "SOUR2:FUNC:PULS:TRAN:TRA 1e-07",
        ]

    def test_33500_user_waveform_maps_to_arb(self):
        awg = create_test_driver(Agilent33500)
        awg.set_waveform(2, "USER")
        assert awg.instrument.writes == ["SOUR2:FUNC ARB"]

    def test_keysight_81150a_detailed_trigger_methods(self):
        awg = create_test_driver(Keysight81150a)
        awg.set_trigger_source(1, "MAN")
        assert awg.instrument.writes[-1] == ":ARM:SOUR1 MAN"

        awg.set_trigger_level(1, 1.5)
        assert awg.instrument.writes[-1] == ":ARM:LEV 1.5"

        awg.set_trigger_slope(1, "POS")
        assert awg.instrument.writes[-1] == ":ARM:SLOP pos"

        awg.set_trigger_mode(1, "EDGE")
        assert awg.instrument.writes[-1] == ":ARM:SENS1 edge"

    def test_sdg2000x_detailed_trigger_methods(self):
        awg = create_test_driver(SDG2000X)
        awg.set_trigger_source(1, "MAN")
        assert awg.instrument.writes[-1] == "C1:BTWV TRSR,MAN"

        awg.set_trigger_slope(1, "POS")
        assert awg.instrument.writes[-1] == "C1:BTWV EDGE,RISE"

        awg.set_trigger_mode(1, "EDGE")
        assert awg.instrument.writes[-1] == "C1:BTWV GATE_NCYC,NCYC"

        # set_trigger_level is unsupported: inherits empty stub from Awg, writes 0 commands
        awg.instrument.writes.clear()
        awg.set_trigger_level(1, 1.5)
        assert awg.instrument.writes == []


# ============================================================================
# 5. VirtualAwg Category Behavior & Safing
# ============================================================================

class TestVirtualAwgCategory:
    """Verify VirtualAwg driver-owned configuration, queries, and safing."""

    def test_virtual_awg_all_channel_safing(self):
        vawg = VirtualAwg()
        for ch in vawg.channel:
            vawg.output(ch, on=True)
            assert vawg.state["output"][ch] is True

        for ch in vawg.channel:
            vawg.output(ch, on=False)
            assert vawg.state["output"][ch] is False

    def test_virtual_awg_configure_waveform_atomic(self):
        vawg = VirtualAwg()
        vawg.configure_waveform(1, "SIN", frequency=1000.0, amplitude=2.5, offset=0.1)
        assert vawg.state["frequency"][1] == 1000.0
        assert vawg.state["amplitude"][1] == 2.5
        assert vawg.state["offset"][1] == 0.1

        # Invalid amplitude rejected, state preserved
        with pytest.raises(ValueError):
            vawg.configure_waveform(1, "SIN", amplitude=float("inf"))
        assert vawg.state["amplitude"][1] == 2.5

    def test_virtual_awg_state_tracking(self):
        vawg = VirtualAwg()
        vawg.configure_waveform(1, "SIN", frequency=2500.0, amplitude=3.0)
        assert vawg.state["frequency"][1] == 2500.0
        assert vawg.state["amplitude"][1] == 3.0
        assert vawg.state["output"][1] is False
        vawg.output(1, on=True)
        assert vawg.state["output"][1] is True

    def test_unsupported_trigger_capabilities_documented_in_docstring(self):
        doc = inspect.getdoc(DaqAsAwg)
        assert doc is not None
        assert "trigger" in doc.lower()
        assert "unsupported" in doc.lower()


@pytest.mark.parametrize("case", DRIVER_CASES['awg'], ids=lambda case: case.cls.__name__)
def test_registered_driver_behavior(case, monkeypatch):
    """Every runtime registration executes an observable category operation."""
    case.check(monkeypatch)
