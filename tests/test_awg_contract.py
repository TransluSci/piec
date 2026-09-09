"""
Contract tests for the Arbitrary Waveform Generator (AWG) base driver and implementations.

Stage 0 Checkpoint 3: AWG output_trigger indentation repair and contract verification.
Stage 0 Checkpoint 4: AWG trigger_source conditional repair and affected-driver audit.
Stage 0 Checkpoint 4 follow-up: Comprehensive concrete AWG and adapter trigger audit and verification.
"""

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


# Inventory of all concrete AWG drivers and adapters in the codebase
CONCRETE_AWG_DRIVERS = [
    VirtualAwg,
    Keysight81150a,
    SDG2000X,
    Agilent33220A,
    Agilent33500,
    RigolDG1000,
    RigolDG4000,
]

AWG_ADAPTERS = [
    DaqAsAwg,
]

ALL_AWG_IMPLEMENTATIONS = CONCRETE_AWG_DRIVERS + AWG_ADAPTERS

SUPPORTED_TRIGGER_DRIVERS = [
    VirtualAwg,
    Keysight81150a,
    SDG2000X,
]

UNSUPPORTED_TRIGGER_CLASSES = [
    Agilent33220A,
    Agilent33500,
    RigolDG1000,
    RigolDG4000,
    DaqAsAwg,
]


class _MinimalAwg(Awg):
    """Minimal subclass of Awg for contract verification without hardware dependencies."""

    def __init__(self):
        # Bypass VISA initialization
        self.instrument = Mock()


class TestAwgOutputTriggerContract:
    """Verify that Awg.output_trigger is a valid class method adhering to driver contracts."""

    def test_output_trigger_is_class_method_of_awg(self):
        """Awg must declare output_trigger as a member method, not a nested function."""
        assert hasattr(Awg, "output_trigger"), "Awg must have output_trigger method"
        assert callable(getattr(Awg, "output_trigger")), "Awg.output_trigger must be callable"

        # Unwrap AutoCheckMeta decorator to inspect the underlying function
        unwrapped = inspect.unwrap(Awg.output_trigger)
        assert unwrapped.__name__ == "output_trigger"

        sig = inspect.signature(Awg.output_trigger)
        params = list(sig.parameters.values())
        assert len(params) == 1, f"Expected exactly 1 parameter (self), got {params}"
        assert params[0].name == "self"

    def test_configure_trigger_does_not_contain_nested_output_trigger(self):
        """configure_trigger must not contain an indented inner function named output_trigger."""
        # Unwrap AutoCheckMeta decorator to inspect the underlying configure_trigger method bytecode
        unwrapped = inspect.unwrap(Awg.configure_trigger)
        assert unwrapped.__name__ == "configure_trigger"

        consts = unwrapped.__code__.co_consts
        nested_code_objects = [c for c in consts if inspect.iscode(c)]
        nested_names = [c.co_name for c in nested_code_objects]
        assert "output_trigger" not in nested_names, (
            "output_trigger must not be an inner function of configure_trigger"
        )

    def test_minimal_awg_subclass_inherits_output_trigger(self):
        """A minimal Awg subclass inherits output_trigger without raising AttributeError."""
        awg = _MinimalAwg()
        assert hasattr(awg, "output_trigger")
        # Calling inherited output_trigger must not raise
        result = awg.output_trigger()
        assert result is None

    def test_virtual_awg_implements_output_trigger(self):
        """VirtualAwg output_trigger executes :TRIG and applies waveform to virtual sample."""
        vawg = VirtualAwg(simulation_points=100)
        assert hasattr(vawg, "output_trigger")
        assert callable(vawg.output_trigger)

        # Clear prior sample simulation state to isolate and observe trigger effect
        vawg.sample.output_voltage = None
        vawg.sample.t = None
        vawg.sample.prep_points = None

        with patch.object(vawg, "write", wraps=vawg.write) as spy_write:
            vawg.output_trigger()
            spy_write.assert_called_once_with(":TRIG")

        # Assert physical/simulation effect on virtual sample
        assert vawg.sample.prep_points == 20
        assert isinstance(vawg.sample.t, np.ndarray)
        assert len(vawg.sample.t) == 120  # 100 simulation_points + 20 prep_points
        assert np.all(np.isfinite(vawg.sample.t))
        assert isinstance(vawg.sample.output_voltage, np.ndarray)
        assert len(vawg.sample.output_voltage) == 120
        assert np.all(np.isfinite(vawg.sample.output_voltage))
        assert np.any(vawg.sample.output_voltage != 0.0)

    def test_keysight_81150a_implements_output_trigger(self):
        """Keysight81150a overrides output_trigger to write SCPI :TRIG."""
        mock_inst = Mock()
        k_awg = Keysight81150a.__new__(Keysight81150a)
        k_awg.instrument = mock_inst

        k_awg.output_trigger()
        mock_inst.write.assert_called_once_with(":TRIG")

    def test_sdg2000x_implements_output_trigger(self):
        """SDG2000X overrides output_trigger to send manual trigger command."""
        mock_inst = Mock()
        sdg = SDG2000X.__new__(SDG2000X)
        sdg.instrument = mock_inst

        sdg.output_trigger()
        mock_inst.write.assert_called_once_with("C1:BTWV MTRIG")

    @pytest.mark.parametrize("cls", [Awg, VirtualAwg, Keysight81150a, SDG2000X])
    def test_all_awg_classes_satisfy_output_trigger_interface(self, cls):
        """Every known AWG class must expose output_trigger."""
        assert hasattr(cls, "output_trigger"), f"{cls.__name__} missing output_trigger"
        assert callable(getattr(cls, "output_trigger")), f"{cls.__name__}.output_trigger is not callable"


class TestAwgTriggerSourceContract:
    """Verify configure_trigger conditional behavior and affected driver implementations."""

    def test_base_configure_trigger_applies_trigger_source_when_provided(self):
        """Awg.configure_trigger must call set_trigger_source when trigger_source is not None."""
        awg = _MinimalAwg()
        awg.set_trigger_source = Mock()
        awg.set_trigger_level = Mock()
        awg.set_trigger_slope = Mock()
        awg.set_trigger_mode = Mock()

        awg.configure_trigger(channel=1, trigger_source="MAN")

        awg.set_trigger_source.assert_called_once_with(1, "man")
        awg.set_trigger_level.assert_not_called()
        awg.set_trigger_slope.assert_not_called()
        awg.set_trigger_mode.assert_not_called()

    def test_base_configure_trigger_skips_trigger_source_when_none(self):
        """Awg.configure_trigger must NOT call set_trigger_source when trigger_source is None."""
        awg = _MinimalAwg()
        awg.set_trigger_source = Mock()
        awg.set_trigger_level = Mock()
        awg.set_trigger_slope = Mock()
        awg.set_trigger_mode = Mock()

        awg.configure_trigger(channel=1, trigger_source=None)

        awg.set_trigger_source.assert_not_called()

    def test_base_configure_trigger_applies_all_parameters(self):
        """Awg.configure_trigger calls all setters when all arguments are supplied."""
        awg = _MinimalAwg()
        awg.set_trigger_source = Mock()
        awg.set_trigger_level = Mock()
        awg.set_trigger_slope = Mock()
        awg.set_trigger_mode = Mock()

        awg.configure_trigger(
            channel=1,
            trigger_source="EXT",
            trigger_level=1.2,
            trigger_slope="POS",
            trigger_mode="EDGE",
        )

        awg.set_trigger_source.assert_called_once_with(1, "ext")
        awg.set_trigger_level.assert_called_once_with(1, 1.2)
        awg.set_trigger_slope.assert_called_once_with(1, "pos")
        awg.set_trigger_mode.assert_called_once_with(1, "edge")

    def test_keysight_81150a_configure_trigger_applies_source(self):
        """Keysight81150a.configure_trigger calls set_trigger_source when source is provided."""
        mock_inst = Mock()
        k_awg = Keysight81150a.__new__(Keysight81150a)
        k_awg.instrument = mock_inst

        # When trigger_source is provided, writes :ARM:SOUR
        k_awg.configure_trigger(channel=1, trigger_source="EXT")
        mock_inst.write.assert_called_with(":ARM:SOUR1 EXT")

        mock_inst.reset_mock()
        # When trigger_source is None, does not write :ARM:SOUR
        k_awg.configure_trigger(channel=1, trigger_source=None, trigger_level=0.5)
        mock_inst.write.assert_called_once_with(":ARM:LEV 0.5")

    def test_virtual_awg_configure_trigger_applies_source(self):
        """VirtualAwg.configure_trigger updates trigger_source state when provided."""
        vawg = VirtualAwg()
        vawg.configure_trigger(channel=1, trigger_source="MAN")
        assert vawg.state["trigger_source"][1].upper() == "MAN"

        # Calling with trigger_source=None does not overwrite previous setting
        vawg.configure_trigger(channel=1, trigger_source=None, trigger_level=2.0)
        assert vawg.state["trigger_source"][1].upper() == "MAN"
        assert vawg.state["trigger_level"][1] == 2.0

    def test_sdg2000x_configure_trigger_applies_source(self):
        """SDG2000X inherits configure_trigger and dispatches trigger source command."""
        mock_inst = Mock()
        sdg = SDG2000X.__new__(SDG2000X)
        sdg.instrument = mock_inst

        # Providing a valid source sends the command
        sdg.configure_trigger(channel=1, trigger_source="MAN")
        mock_inst.write.assert_called_with("C1:BTWV TRSR,MAN")

        mock_inst.reset_mock()
        # Passing None does not raise ValueError and does not write command
        sdg.configure_trigger(channel=1, trigger_source=None, trigger_slope="POS")
        mock_inst.write.assert_called_once_with("C1:BTWV EDGE,RISE")


class TestAwgDriverAuditAndSafingContract:
    """
    Audit all concrete AWGs and adapters:
    - Distinguish implemented trigger behavior from inherited empty methods.
    - Verify supported implementations through command and simulation effect assertions.
    - Verify unsupported implementations produce no hardware commands (no invented commands).
    - Explicitly document unsupported trigger capabilities.
    """

    def test_inventory_contains_all_awg_subclasses(self):
        """Every concrete driver and adapter implementing Awg in the codebase must be inventoried."""
        for cls in ALL_AWG_IMPLEMENTATIONS:
            assert issubclass(cls, Awg), f"{cls.__name__} must inherit from Awg"

        # Verify that all 7 concrete drivers and 1 adapter are present
        assert len(CONCRETE_AWG_DRIVERS) == 7
        assert len(AWG_ADAPTERS) == 1
        assert len(ALL_AWG_IMPLEMENTATIONS) == 8

    def test_implemented_vs_inherited_trigger_methods(self):
        """
        Distinguish explicitly overridden trigger methods from inherited empty stubs on Awg.
        
        A method is considered implemented by a driver only if it is defined in that class's
        own __dict__, overriding the empty base stub in Awg.
        """
        # VirtualAwg overrides all trigger methods
        for method in ("output_trigger", "set_trigger_source", "set_trigger_level", "set_trigger_slope", "set_trigger_mode"):
            assert method in VirtualAwg.__dict__, f"VirtualAwg must implement {method}"

        # Keysight81150a overrides all trigger methods
        for method in ("output_trigger", "set_trigger_source", "set_trigger_level", "set_trigger_slope", "set_trigger_mode"):
            assert method in Keysight81150a.__dict__, f"Keysight81150a must implement {method}"

        # SDG2000X overrides source, slope, mode, and output_trigger; but set_trigger_level is unsupported
        assert "output_trigger" in SDG2000X.__dict__
        assert "set_trigger_source" in SDG2000X.__dict__
        assert "set_trigger_slope" in SDG2000X.__dict__
        assert "set_trigger_mode" in SDG2000X.__dict__
        assert "set_trigger_level" not in SDG2000X.__dict__, "SDG2000X does not support set_trigger_level"

        # Unsupported drivers/adapters must NOT define these methods in their own __dict__;
        # they must inherit empty stubs from Awg.
        for cls in UNSUPPORTED_TRIGGER_CLASSES:
            for method in ("output_trigger", "set_trigger_source", "set_trigger_level", "set_trigger_slope", "set_trigger_mode"):
                assert method not in cls.__dict__, (
                    f"{cls.__name__} should not define {method} in __dict__; it is an unsupported inherited stub"
                )

    def test_keysight_81150a_supported_trigger_commands(self):
        """Keysight81150a supported trigger methods write exact SCPI commands."""
        mock_inst = Mock()
        k_awg = Keysight81150a.__new__(Keysight81150a)
        k_awg.instrument = mock_inst

        # output_trigger -> :TRIG
        k_awg.output_trigger()
        mock_inst.write.assert_called_with(":TRIG")

        # set_trigger_source -> :ARM:SOUR{channel} {source}
        k_awg.set_trigger_source(1, "MAN")
        mock_inst.write.assert_called_with(":ARM:SOUR1 MAN")

        # set_trigger_level -> :ARM:LEV {level}
        k_awg.set_trigger_level(1, 1.5)
        mock_inst.write.assert_called_with(":ARM:LEV 1.5")

        # set_trigger_slope -> :ARM:SLOP {slope}
        k_awg.set_trigger_slope(1, "POS")
        mock_inst.write.assert_called_with(":ARM:SLOP pos")

        # set_trigger_mode -> :ARM:SENS{channel} {mode}
        k_awg.set_trigger_mode(1, "EDGE")
        mock_inst.write.assert_called_with(":ARM:SENS1 edge")

        # configure_trigger dispatches to all setters
        mock_inst.reset_mock()
        k_awg.configure_trigger(1, trigger_source="EXT", trigger_level=2.0, trigger_slope="NEG", trigger_mode="LEV")
        mock_inst.write.assert_any_call(":ARM:SOUR1 EXT")
        mock_inst.write.assert_any_call(":ARM:LEV 2.0")
        mock_inst.write.assert_any_call(":ARM:SLOP neg")
        mock_inst.write.assert_any_call(":ARM:SENS1 lev")
        assert mock_inst.write.call_count == 4

    def test_sdg2000x_supported_and_unsupported_trigger_commands(self):
        """SDG2000X writes SCPI commands for supported features and no-ops for unsupported trigger_level."""
        mock_inst = Mock()
        sdg = SDG2000X.__new__(SDG2000X)
        sdg.instrument = mock_inst

        # output_trigger -> C1:BTWV MTRIG
        sdg.output_trigger()
        mock_inst.write.assert_called_with("C1:BTWV MTRIG")

        # set_trigger_source -> C{channel}:BTWV TRSR,{source}
        sdg.set_trigger_source(1, "MAN")
        mock_inst.write.assert_called_with("C1:BTWV TRSR,MAN")

        # set_trigger_slope -> C{channel}:BTWV EDGE,{slope}
        sdg.set_trigger_slope(1, "POS")
        mock_inst.write.assert_called_with("C1:BTWV EDGE,RISE")

        # set_trigger_mode -> C{channel}:BTWV GATE_NCYC,{mode}
        sdg.set_trigger_mode(1, "EDGE")
        mock_inst.write.assert_called_with("C1:BTWV GATE_NCYC,NCYC")

        # set_trigger_level is unsupported: inherits empty stub from Awg, writes 0 commands
        mock_inst.reset_mock()
        sdg.set_trigger_level(1, 1.5)
        mock_inst.write.assert_not_called()

        # configure_trigger dispatches supported parameters and does not write trigger_level
        mock_inst.reset_mock()
        sdg.configure_trigger(1, trigger_source="EXT", trigger_level=2.0, trigger_slope="NEG", trigger_mode="LEV")
        mock_inst.write.assert_any_call("C1:BTWV TRSR,EXT")
        mock_inst.write.assert_any_call("C1:BTWV EDGE,FALL")
        mock_inst.write.assert_any_call("C1:BTWV GATE_NCYC,GATE")
        assert mock_inst.write.call_count == 3

    def test_virtual_awg_supported_trigger_effects(self):
        """VirtualAwg trigger methods record internal state and output_trigger generates simulated sample data."""
        vawg = VirtualAwg(simulation_points=50)

        # set_trigger_* methods update internal state dictionary
        vawg.set_trigger_source(1, "MAN")
        assert vawg.state["trigger_source"][1].upper() == "MAN"

        vawg.set_trigger_level(1, 1.8)
        assert vawg.state["trigger_level"][1] == 1.8

        vawg.set_trigger_slope(1, "NEG")
        assert vawg.state["trigger_slope"][1].upper() == "NEG"

        vawg.set_trigger_mode(1, "LEV")
        assert vawg.state["trigger_mode"][1].upper() == "LEV"

        # Clear prior sample simulation state
        vawg.sample.output_voltage = None
        vawg.sample.t = None
        vawg.sample.prep_points = None

        with patch.object(vawg, "write", wraps=vawg.write) as spy_write:
            vawg.output_trigger()
            spy_write.assert_called_once_with(":TRIG")

        # Assert physical/simulation effect on virtual sample
        assert vawg.sample.prep_points == 20
        assert isinstance(vawg.sample.t, np.ndarray)
        assert len(vawg.sample.t) == 70  # 50 simulation_points + 20 prep_points
        assert isinstance(vawg.sample.output_voltage, np.ndarray)
        assert len(vawg.sample.output_voltage) == 70
        assert np.any(vawg.sample.output_voltage != 0.0)

    @pytest.mark.parametrize(
        "cls",
        [
            Agilent33220A,
            Agilent33500,
            RigolDG1000,
            RigolDG4000,
        ],
    )
    def test_unsupported_awg_drivers_produce_no_hardware_commands(self, cls):
        """Drivers with unsupported trigger features inherit empty methods that emit zero hardware commands."""
        mock_inst = Mock()
        inst = cls.__new__(cls)
        inst.instrument = mock_inst

        # Calling output_trigger does nothing and writes 0 commands
        result = inst.output_trigger()
        assert result is None
        mock_inst.write.assert_not_called()

        # Calling individual trigger setters does nothing and writes 0 commands
        inst.set_trigger_source(1, "MAN")
        inst.set_trigger_level(1, 1.0)
        inst.set_trigger_slope(1, "POS")
        inst.set_trigger_mode(1, "EDGE")
        mock_inst.write.assert_not_called()

        # configure_trigger gracefully no-ops without error or writes
        inst.configure_trigger(1, trigger_source="MAN", trigger_level=1.0, trigger_slope="POS", trigger_mode="EDGE")
        mock_inst.write.assert_not_called()

    def test_unsupported_daq_adapter_produces_no_hardware_commands(self):
        """DaqAsAwg adapter inherits empty trigger methods and does not call underlying DAQ methods."""
        mock_daq = Mock()
        mock_daq.ao_channel = [0, 1]
        mock_daq.ao_sample_rate = 10000

        adapter = DaqAsAwg(mock_daq)
        mock_daq.reset_mock()

        # Calling output_trigger does nothing
        result = adapter.output_trigger()
        assert result is None
        assert mock_daq.method_calls == []

        # Calling configure_trigger does nothing
        adapter.configure_trigger(1, trigger_source="MAN", trigger_level=1.0)
        assert mock_daq.method_calls == []

    @pytest.mark.parametrize("cls", UNSUPPORTED_TRIGGER_CLASSES)
    def test_unsupported_trigger_capabilities_documented_in_docstring(self, cls):
        """Classes with unsupported trigger capabilities must document this in their docstrings."""
        doc = inspect.getdoc(cls)
        assert doc is not None, f"{cls.__name__} missing docstring"
        doc_lower = doc.lower()
        assert "trigger" in doc_lower, f"{cls.__name__} docstring must mention trigger capabilities"
        assert (
            "unsupported" in doc_lower or "empty stub" in doc_lower
        ), f"{cls.__name__} docstring must explicitly document trigger capabilities as unsupported"

    def test_virtual_awg_all_channel_safing(self):
        """VirtualAwg allows disabling output on every supported channel."""
        vawg = VirtualAwg()
        for ch in vawg.channel:
            vawg.output(ch, on=True)
            assert vawg.state["output"][ch] is True

        # Safe shutdown: disable all channels
        for ch in vawg.channel:
            vawg.output(ch, on=False)
            assert vawg.state["output"][ch] is False
