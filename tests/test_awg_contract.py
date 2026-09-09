"""
Contract tests for the Arbitrary Waveform Generator (AWG) base driver and implementations.

Stage 0 Checkpoint 3: AWG output_trigger indentation repair and contract verification.
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
