"""LeCroy waveform transfer lengths and multi-channel timing alignment."""

import struct

import numpy as np
import pytest

from piec.drivers.oscilloscope.lecroy_sda6020 import LeCroySDA6020
from tests.support.transports import ScriptedTransport, create_test_driver


class WaveformTransport(ScriptedTransport):
    """Model a 10,002-point record whose valid indices survive transfer slicing."""

    def __init__(self, truncate=False):
        super().__init__({"TRIG_MODE?": "NORM"})
        self.samples = np.arange(10002, dtype=np.int16)
        self.point_limit = 0
        self.truncate = truncate

    def write(self, command):
        super().write(command)
        if command.startswith("WAVEFORM_SETUP "):
            fields = command.split(" ", 1)[1].split(",")
            self.point_limit = int(fields[fields.index("NP") + 1])

    def query_binary_values(self, command, **kwargs):
        count = min(self.point_limit or len(self.samples), len(self.samples))
        if command.endswith("WF? DESC"):
            desc = bytearray(346)
            desc[:8] = b"WAVEDESC"
            struct.pack_into("<hh", desc, 32, 1, 1)
            struct.pack_into("<i", desc, 116, count)
            struct.pack_into("<ii", desc, 124, 0, len(self.samples) - 1)
            struct.pack_into("<ff", desc, 156, 0.5, 1.0)
            struct.pack_into("<fd", desc, 176, 0.25, -2.0)
            return list(desc)
        if command.endswith("WF? DAT1"):
            return self.samples[:count - int(self.truncate)].tolist()
        raise AssertionError(f"Unexpected binary query: {command}")


@pytest.mark.parametrize("channel, columns", [
    (1, ["Time", "Voltage"]),
    ([2, 1], ["Time", "CH2", "CH1"]),
])
def test_get_data_transfers_entire_record(channel, columns):
    scope = create_test_driver(LeCroySDA6020)
    scope.instrument = WaveformTransport()
    scope.configure_acquisition(channel=channel, acquisition_points=10000)

    data = scope.get_data()

    assert list(data.columns) == columns
    assert len(data) == 10002
    np.testing.assert_allclose(data["Time"], np.arange(10002) * 0.25 - 2.0)
    for column in columns[1:]:
        np.testing.assert_allclose(data[column], scope.instrument.samples * 0.5 - 1.0)
    assert "MEMORY_SIZE 10000" in scope.instrument.writes
    assert scope.instrument.writes[-1] == "TRIG_MODE NORM"


def test_get_data_still_rejects_incomplete_transfer():
    scope = create_test_driver(LeCroySDA6020)
    scope.instrument = WaveformTransport(truncate=True)
    scope.configure_acquisition(channel=1, acquisition_points=10000)

    with pytest.raises(ValueError, match="incomplete waveform data"):
        scope.get_data()

    assert scope.instrument.writes[-1] == "TRIG_MODE NORM"


class TimingTransport(WaveformTransport):
    """Return independently described channel records from one acquisition."""

    def __init__(self, timings):
        super().__init__()
        self.samples = np.zeros(100002, dtype=np.int16)
        self.timings = timings

    def query(self, command):
        if command.endswith(":TRACE?"):
            return "ON" if int(command[1]) in self.timings else "OFF"
        return super().query(command)

    def query_binary_values(self, command, **kwargs):
        interval, offset, count = self.timings[int(command[1])]
        if command.endswith("WF? DESC"):
            desc = bytearray(super().query_binary_values(command, **kwargs))
            struct.pack_into("<i", desc, 116, count)
            struct.pack_into("<ii", desc, 124, 0, count - 1)
            struct.pack_into("<fd", desc, 176, interval, offset)
            return desc
        return np.full(count, int(command[1]), dtype=np.int16).tolist()


@pytest.mark.parametrize("selection", [None, [1, 2], [2, 1]])
def test_get_data_accepts_observed_subsample_offset(selection):
    timings = {
        1: (1e-10, -5.000066208318635e-6, 100002),
        2: (1e-10, -5.000065371879711e-6, 100002),
    }
    scope = create_test_driver(LeCroySDA6020)
    scope.instrument = TimingTransport(timings)
    scope.configure_acquisition(channel=selection, acquisition_points=100000)

    data = scope.get_data()

    channels = selection or [1, 2]
    assert list(data.columns) == ["Time"] + [f"CH{channel}" for channel in channels]
    interval, offset, count = timings[1]
    expected_times = np.arange(count) * float(np.float32(interval)) + offset
    np.testing.assert_array_equal(data["Time"], expected_times)
    for channel in channels:
        np.testing.assert_array_equal(data[f"CH{channel}"], np.full(count, channel * 0.5 - 1))
    assert scope.instrument.writes[-1] == "TRIG_MODE NORM"


def test_get_data_uses_c1_time_axis_without_comparing_other_timestamps():
    scope = create_test_driver(LeCroySDA6020)
    scope.instrument = TimingTransport({
        1: (1e-10, -5e-6, 100002),
        2: (2e-10, 1.0, 100002),
        3: (3e-10, 2.0, 100002),
    })
    scope.configure_acquisition(channel=[3, 2, 1])

    data = scope.get_data()

    assert list(data.columns) == ["Time", "CH3", "CH2", "CH1"]
    expected_times = np.arange(100002) * float(np.float32(1e-10)) - 5e-6
    np.testing.assert_array_equal(data["Time"], expected_times)
    assert scope.instrument.writes[-1] == "TRIG_MODE NORM"


@pytest.mark.parametrize("selection", [2, [3, 2]])
def test_get_data_uses_selected_channel_time_when_c1_not_selected(selection):
    scope = create_test_driver(LeCroySDA6020)
    scope.instrument = TimingTransport({
        2: (1e-10, -5e-6, 100002),
        3: (2e-10, 1.0, 100002),
    })
    scope.configure_acquisition(channel=selection)

    data = scope.get_data()

    reference = selection[0] if isinstance(selection, list) else selection
    interval, offset, count = scope.instrument.timings[reference]
    expected_times = np.arange(count) * float(np.float32(interval)) + offset
    np.testing.assert_array_equal(data["Time"], expected_times)
    expected_columns = ["Time", "CH3", "CH2"] if isinstance(selection, list) else ["Time", "Voltage"]
    assert list(data.columns) == expected_columns


def test_get_data_rejects_unequal_record_lengths():
    scope = create_test_driver(LeCroySDA6020)
    scope.instrument = TimingTransport({
        1: (1e-10, -5e-6, 100002),
        2: (1e-10, -5e-6, 100001),
    })
    scope.configure_acquisition(channel=[1, 2])

    with pytest.raises(ValueError, match="C2 has a different sample count"):
        scope.get_data()

    assert scope.instrument.writes[-1] == "TRIG_MODE NORM"
