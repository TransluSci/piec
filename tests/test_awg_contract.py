"""
Contract tests for the Arbitrary Waveform Generator (AWG) base driver and implementations.

Stage 0 Checkpoint 3: AWG output_trigger indentation repair and contract verification.
Stage 0 Checkpoint 4: AWG trigger_source conditional repair and affected-driver audit.
"""

import inspect
from unittest.mock import Mock, patch

import numpy as np
import pytest

from piec.drivers.awg.awg import Awg
from piec.drivers.awg.k_81150a import Keysight81150a
from piec.drivers.awg.sdg2000 import SDG2000X
from piec.drivers.awg.virtual_awg import VirtualAwg


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
    """Audit concrete AWGs for manual trigger support and all-channel output disabling."""

    @pytest.mark.parametrize(
        "cls",
        [
            VirtualAwg,
            Keysight81150a,
            SDG2000X,
            Awg,
        ],
    )
    def test_awg_manual_trigger_audit(self, cls):
        """Audit all known AWG drivers for real manual trigger support."""
        assert hasattr(cls, "output_trigger"), f"{cls.__name__} missing output_trigger"
        assert callable(getattr(cls, "output_trigger")), f"{cls.__name__}.output_trigger is not callable"

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
