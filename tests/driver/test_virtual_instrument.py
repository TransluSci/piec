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


class TestVirtualInstrumentBase:
    """Test shared base properties, simulation point coercion, and policy warnings."""

    def test_shared_sample_starts_unassigned_and_shares(self, monkeypatch):
        monkeypatch.setattr(VirtualInstrument, "sample", None)
        vi = VirtualInstrument()
        other = VirtualInstrument()
        assert vi.sample is None
        assert other.sample is None

        custom_sample = MagicMock()
        vi.sample = custom_sample
        assert other.sample is custom_sample
        assert VirtualInstrument.sample is custom_sample

    def test_class_sample_updates_existing_and_new_instances(self, monkeypatch):
        monkeypatch.setattr(VirtualInstrument, "sample", None)
        vi = VirtualInstrument()
        new_sample = MagicMock()
        VirtualInstrument.sample = new_sample
        assert VirtualInstrument.sample is new_sample
        assert vi.sample is new_sample
        assert VirtualInstrument().sample is new_sample

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
