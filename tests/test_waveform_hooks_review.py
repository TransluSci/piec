"""Cross-family waveform regressions for checkpoints 28e and 28f."""
import numpy as np
import pytest
from piec.drivers.awg.virtual_awg import VirtualAwg
from piec.drivers.oscilloscope.virtual_oscilloscope import VirtualScope


def test_awg_scope_roundtrip_offset_polarity_and_pretrigger_axis():
    captured = {}
    def transmit(v, t):
        captured.update(voltage=v.copy(), time=t - t[-1] / 2)
    awg = VirtualAwg(waveform_hook=transmit, simulation_points=3)
    awg.create_arb_waveform(1, "test", [-1, 0, 1])
    awg.set_arb_waveform(1, "test")
    awg.set_amplitude(1, 2)
    awg.set_offset(1, 3)
    awg.set_polarity(1, "INV")
    awg.output_trigger()
    scope = VirtualScope(waveform_hook=lambda: captured)
    result = scope.get_data()
    np.testing.assert_allclose(result.Voltage, [5, 3, 1])
    assert result.Time.iloc[0] < 0 < result.Time.iloc[-1]


def test_scope_routes_selected_channel_and_rejects_ambiguous_labels():
    scope = VirtualScope(waveform_hook=lambda: {"time": [0, 1], "ch1": [1, 2], "ch2": [3, 4]})
    assert scope.get_data(2).Voltage.tolist() == [3, 4]
    scope.waveform_hook = lambda: {"a": [0, 1], "b": [2, 3]}
    with pytest.raises(ValueError):
        scope.get_data()


@pytest.mark.parametrize("times", [[1, 0], [0, 0], [0, float("inf")]])
def test_scope_rejects_invalid_time_axis(times):
    with pytest.raises(ValueError):
        VirtualScope(waveform_hook=lambda: ([1, 2], times)).get_data()


@pytest.mark.parametrize("channel", [1.5, float("nan"), float("inf")])
def test_scope_rejects_invalid_channel_before_notifying(channel):
    calls = []
    scope = VirtualScope(waveform_hook=lambda: calls.append(1))
    before = scope.get_state()
    with pytest.raises(ValueError):
        scope.get_data(channel)
    with pytest.raises(ValueError):
        scope.set_vertical_scale(channel, vdiv=1)
    assert scope.get_state() == before
    assert calls == []


@pytest.mark.parametrize("data", [[0, float("nan")], [0, float("inf")], [[0, 1], [2, 3]], 1])
def test_awg_rejects_invalid_arb_before_mutating(data):
    awg = VirtualAwg()
    awg.create_arb_waveform(1, "valid", [0, 1])
    before = awg.get_state()["arb_waveform"][1].copy()
    with pytest.raises((ValueError, TypeError)):
        awg.create_arb_waveform(1, "invalid", data)
    np.testing.assert_array_equal(awg.get_state()["arb_waveform"][1], before)


def test_awg_state_snapshot_does_not_expose_live_arb_storage():
    awg = VirtualAwg()
    awg.create_arb_waveform(1, "data", [0, 1])
    snapshot = awg.get_state()
    snapshot["arb_waveform"][1][0] = 99
    assert awg.get_state()["arb_waveform"][1][0] == 0


def test_awg_scpi_queries_use_explicit_channel():
    awg = VirtualAwg()
    awg.write(":OUTP2 ON")
    assert awg.query(":OUTP2?") == "1"
    assert awg.query(":OUTP1?") == "0"
    awg.set_frequency(1, 100)
    awg.set_frequency(2, 200)
    assert float(awg.query(":SOUR2:FREQ?")) == 200
    assert float(awg.query(":SOUR1:FREQ?")) == 100
    before = awg.get_state()
    with pytest.raises(ValueError):
        awg.write(":OUTP3 ON")
    assert awg.get_state() == before


def test_awg_noise_is_isolated_and_reset_replays():
    a, b = VirtualAwg(seed=42), VirtualAwg(seed=42)
    a.set_waveform(1, "NOIS")
    b.set_waveform(1, "NOIS")
    first = a.get_waveform(1)
    a.get_waveform(1)
    np.testing.assert_array_equal(first, b.get_waveform(1))
    a.reset()
    a.set_waveform(1, "NOIS")
    np.testing.assert_array_equal(first, a.get_waveform(1))


@pytest.mark.parametrize("method,settings", [
    ("configure_horizontal", {"tdiv": 0.01, "x_position": float("nan")}),
    ("configure_trigger", {"trigger_source": 2, "trigger_level": float("nan")}),
    ("configure_acquisition", {"channel": 2, "acquisition_points": -1}),
])
def test_scope_invalid_bundled_configuration_is_atomic(method, settings):
    scope = VirtualScope()
    before = scope.get_state()
    with pytest.raises(ValueError):
        getattr(scope, method)(**settings)
    assert scope.get_state() == before
