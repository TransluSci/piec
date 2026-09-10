"""Regression checks for checkpoint 13 review findings."""
from unittest.mock import Mock

import pytest

from piec.drivers.sourcemeter.virtual_sourcemeter import VirtualSourcemeter
from piec.measurement import IVSweep, RunState


def sweep(source, **kwargs):
    return IVSweep(source, dwell_time=0, ramp_delay=0, **kwargs)


@pytest.mark.parametrize("endpoint", ["v_start", "v_stop"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_invalid_endpoints_rejected_without_io(endpoint, value):
    source = Mock()
    with pytest.raises(ValueError, match="finite"):
        sweep(source, **{endpoint: value})
    assert not source.mock_calls


def test_disable_precedes_configuration_of_energized_source(monkeypatch):
    source = VirtualSourcemeter()
    source.output(channel=1, on=True)
    events = []
    for name in ("output", "idn", "configure_voltage_source", "set_sense_mode"):
        original = getattr(source, name)
        def record(*args, _name=name, _original=original, **kwargs):
            events.append((_name, kwargs))
            return _original(*args, **kwargs)
        monkeypatch.setattr(source, name, record)
    sweep(source, num_steps=2).run_experiment(save=False)
    assert events[0] == ("output", {"channel": 1, "on": False})


def test_session_uses_frozen_options_for_both_hooks(monkeypatch):
    source = VirtualSourcemeter()
    measurement = sweep(source, num_steps=2)
    options = {"compliance_current": .001}
    seen = []
    original = measurement._capture_data
    def capture(request, on_update=None):
        seen.append(request.options["compliance_current"])
        return original(request, on_update)
    monkeypatch.setattr(measurement, "_capture_data", capture)
    with measurement.session(save=False, options=options) as session:
        options["compliance_current"] = .5
        session.configure_instruments()
        assert source.state["current_compliance"] == .001
        options["compliance_current"] = .75
        session.capture_data()
    assert seen == [.001]


@pytest.mark.parametrize("start,stop", [(0, 1), (1, -1)])
def test_all_voltage_transitions_respect_ramp_step(monkeypatch, start, stop):
    source = VirtualSourcemeter()
    voltages = []
    original = source.set_source_voltage
    def record(channel=1, voltage=None):
        voltages.append(voltage)
        return original(channel=channel, voltage=voltage)
    monkeypatch.setattr(source, "set_source_voltage", record)
    data = sweep(source, v_start=start, v_stop=stop, num_steps=2, ramp_step=.1).run_experiment(save=False)
    assert all(abs(b-a) <= .100000001 for a,b in zip(voltages, voltages[1:]))
    assert data.voltage.tolist() == [start, stop]


def test_stop_during_sweep_transition_skips_read_and_preserves_first_point(monkeypatch):
    source = VirtualSourcemeter()
    measurement = sweep(source, num_steps=2, ramp_step=.1)
    original = source.set_source_voltage
    def stop(channel=1, voltage=None):
        result = original(channel=channel, voltage=voltage)
        if voltage == pytest.approx(.3) and measurement.run_state == RunState.RUNNING:
            measurement.request_stop()
        return result
    monkeypatch.setattr(source, "set_source_voltage", stop)
    data = measurement.run_experiment(save=False)
    assert measurement.run_state == RunState.ABORTED
    assert data.voltage.tolist() == [0]
    assert source.state["source_voltage"] == 0


def test_live_and_terminal_raw_windows_bounded_while_full_data_retained():
    measurement = sweep(VirtualSourcemeter(), num_steps=205)
    sizes = []
    data = measurement.run_experiment(save=False, on_update=lambda snap: sizes.append(len(snap.get_view("raw"))))
    assert max(sizes) == 100
    assert len(measurement.raw_data) == len(data) == 205
    assert len(measurement.snapshot().get_view("raw")) <= 100


def test_gui_terminal_plot_uses_full_result():
    from Measurements.DCIV.IV_sweep_GUI import IVSweepApp
    from piec.measurement import MeasurementRunner
    measurement = sweep(VirtualSourcemeter(), num_steps=205)
    runner = MeasurementRunner(measurement)
    runner.start(save=False)
    assert runner.join(timeout=10)
    app = IVSweepApp.__new__(IVSweepApp)
    app.runner = runner
    app.experiment = measurement
    app.run_button = Mock()
    app.root = Mock()
    app._plot_dataframe = Mock()
    app._poll_runner()
    assert len(app._plot_dataframe.call_args.args[0]) == 205
