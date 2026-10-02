"""Shared virtual instrument state and simulation-size policy tests.

Generic per-instance hook and waveform-contract tests are outside this branch.
"""

import warnings
from unittest.mock import MagicMock

import numpy as np
import pytest

from piec.drivers.virtual_instrument import (
    VirtualInstrument,
    coerce_simulation_points,
    warn_for_large_simulation_input,
    warn_for_large_simulation_points,
)
from piec.simulation.fe_material import Ferroelectric
from piec.simulation.magnetic_material import MagneticSample


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
