"""Tests for the runnable MOKE GUI helpers and notebook."""

import importlib.util
import json
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd

from piec.analysis.field_calibration import FieldCalibration
from piec.drivers.dmm.virtual_dmm import VirtualDMM
from piec.drivers.sourcemeter.virtual_sourcemeter import VirtualSourcemeter
from piec.measurement.contracts import RunState, SafetyStatus
from piec.measurement.moke import MokeMeasurement, MokeSnapshot


ROOT = Path(__file__).resolve().parents[1]
GUI_PATH = ROOT / "Measurements" / "MOKE" / "MOKE_GUI.py"
NOTEBOOK_PATH = ROOT / "Measurements" / "MOKE" / "MOKE_testing.ipynb"


def _load_gui_module():
    spec = importlib.util.spec_from_file_location("piec_moke_gui", GUI_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_moke_gui_imports_without_starting_tk_mainloop():
    module = _load_gui_module()
    assert module.MokeMeasurementApp.__name__ == "MokeMeasurementApp"


def test_moke_gui_output_cycle_is_closed_and_has_requested_size():
    cycle = _load_gui_module().make_output_cycle(-2, 3, 21)
    assert len(cycle) == 21
    assert cycle[0] == cycle[-1] == -2
    assert cycle.max() == 3


def test_gui_virtual_setup_runs_the_normal_measurement_and_generates_a_loop():
    module = _load_gui_module()
    calibration = FieldCalibration([(-5, -500), (0, 0), (5, 500)])
    source = VirtualSourcemeter("VIRTUAL")
    detector = VirtualDMM("VIRTUAL")
    module.connect_virtual_detector(
        source, detector, calibration, noise=0.0, seed=0
    )
    outputs = module.make_output_cycle(-5, 5, 41)
    measurement = MokeMeasurement(
        sourcemeter=source,
        dmm=detector,
        calibration=calibration,
        output_values=outputs,
        compliance=0.01,
        max_output_step=1.0,
        dwell_time=0.0,
        ramp_delay=0.0,
        n_cycles=2,
        average_cycles=2,
    )

    data = measurement.run_experiment(save=False)

    assert measurement.completed_cycles == 2
    assert len(data) == 2 * len(outputs)
    assert np.ptp(data["detector_voltage"]) > 0.03
    assert source.state["output_on"] is False


def test_moke_gui_plot_snapshot_labels_combine_plain_name_and_unit():
    module = _load_gui_module()
    mock_app = Mock()
    mock_app.show_raw.get.return_value = True
    mock_app.show_last.get.return_value = True
    mock_app.show_average.get.return_value = True
    mock_app.geometry_entry.get.return_value = "in-plane"
    mock_app.ax.lines = []

    calibration = FieldCalibration([(-5, -500), (0, 0), (5, 500)], field_unit="Oe")
    source = VirtualSourcemeter("VIRTUAL")
    detector = VirtualDMM("VIRTUAL")
    meas = MokeMeasurement(
        sourcemeter=source, dmm=detector, calibration=calibration,
        output_values=[-5, 0, 5, 0, -5], compliance=0.01, max_output_step=5.0,
        dwell_time=0.0, ramp_delay=0.0,
    )
    mock_app.experiment = meas

    # 1. Calibrated field mode
    snap_cal = MokeSnapshot(
        raw=pd.DataFrame({"field_calibrated": [0.0], "detector_voltage": [0.5]}),
        last_cycle=pd.DataFrame(),
        cycle_average=pd.DataFrame(),
        completed_cycles=0,
        field_column="field_calibrated",
    )
    module.MokeMeasurementApp._plot_snapshot(mock_app, snap_cal)
    mock_app.ax.set_xlabel.assert_called_once_with("field_calibrated (Oe)")
    mock_app.ax.set_ylabel.assert_called_once_with("detector_voltage (V)")

    # 2. Measured field mode
    meas.field_reader = lambda: 50.0
    meas.field_reader_unit = "Oe"
    snap_meas = MokeSnapshot(
        raw=pd.DataFrame({"field_measured": [50.0], "detector_voltage": [0.5]}),
        last_cycle=pd.DataFrame(),
        cycle_average=pd.DataFrame(),
        completed_cycles=0,
        field_column="field_measured",
    )
    mock_app.ax.reset_mock()
    module.MokeMeasurementApp._plot_snapshot(mock_app, snap_meas)
    mock_app.ax.set_xlabel.assert_called_once_with("field_measured (Oe)")
    mock_app.ax.set_ylabel.assert_called_once_with("detector_voltage (V)")


def test_moke_notebook_code_cells_compile():
    notebook = json.loads(NOTEBOOK_PATH.read_text(encoding="utf-8"))
    for index, cell in enumerate(notebook["cells"]):
        if cell.get("cell_type") == "code":
            compile(
                "".join(cell.get("source", [])),
                f"{NOTEBOOK_PATH}:cell-{index}",
                "exec",
            )


def make_headless_moke_gui(tmp_path=None):
    """Construct a fully populated headless MokeMeasurementApp for interaction testing."""
    module = _load_gui_module()
    app = module.MokeMeasurementApp.__new__(module.MokeMeasurementApp)
    app.root = Mock()
    app.root.winfo_exists.return_value = True
    app.experiment = None
    app.runner = None
    app._terminal_event = None
    app.is_measuring = False
    app._close_when_safe = False
    app._instruments = []
    app._poll_events_id = None

    app.run_button = Mock()
    app.stop_button = Mock()
    app.status_label = Mock()
    app.source_address_entry = Mock(get=Mock(return_value="VIRTUAL"))
    app.detector_address_entry = Mock(get=Mock(return_value="VIRTUAL"))
    app.field_reader_address_entry = Mock(get=Mock(return_value="NONE"))
    app.geometry_entry = Mock(get=Mock(return_value="in-plane"))
    cal_path = Path(__file__).resolve().parents[1] / "Measurements" / "MOKE" / "example_calibration.csv"
    app.calibration_entry = Mock(get=Mock(return_value=str(cal_path)))
    app.source_channel_entry = Mock(get=Mock(return_value=""))
    app.field_per_volt_entry = Mock(get=Mock(return_value="1.0"))
    app.field_offset_entry = Mock(get=Mock(return_value="0.0"))
    app.save_dir_entry = Mock(get=Mock(return_value=str(tmp_path or Path.cwd())))

    app.dynamic_inputs = {
        "output_min": Mock(get=Mock(return_value="-2.0")),
        "output_max": Mock(get=Mock(return_value="2.0")),
        "points_per_cycle": Mock(get=Mock(return_value="5")),
        "n_cycles": Mock(get=Mock(return_value="1")),
        "average_cycles": Mock(get=Mock(return_value="1")),
        "compliance": Mock(get=Mock(return_value="0.01")),
        "max_output_step": Mock(get=Mock(return_value="2.0")),
        "dwell_time": Mock(get=Mock(return_value="0.0")),
        "ramp_delay": Mock(get=Mock(return_value="0.0")),
        "raw_window_points": Mock(get=Mock(return_value="100")),
    }
    app.show_raw = Mock(get=Mock(return_value=True))
    app.show_last = Mock(get=Mock(return_value=True))
    app.show_average = Mock(get=Mock(return_value=True))
    app.save_data = Mock(get=Mock(return_value=False))

    app.ax = Mock()
    app.ax.lines = []
    app.canvas = Mock()
    return app, module


def test_moke_gui_controls_before_first_run_are_safe():
    """Verify trace checkbuttons, geometry entry, STOP, and redraw are harmless no-ops before run."""
    app, module = make_headless_moke_gui()
    assert app.experiment is None

    app._redraw_current()
    app.stop_measurement()
    app.geometry_entry.set = Mock()
    app.geometry_entry.set("out-of-plane")
    app._redraw_current()

    app.ax.plot.assert_not_called()
    app.canvas.draw_idle.assert_not_called()


def test_moke_gui_single_hardware_writer_rule():
    """Verify callbacks reject hardware actions when is_measuring is True."""
    app, module = make_headless_moke_gui()
    app.is_measuring = True

    with patch.object(app, "get_visa_resources") as mock_visa:
        app.refresh_instruments()
        assert not mock_visa.called

    with patch.object(module.filedialog, "askopenfilename") as mock_dialog:
        app.browse_calibration()
        assert not mock_dialog.called

    with patch.object(app, "_create_experiment") as mock_create:
        app.run_measurement()
        assert not mock_create.called


def test_moke_gui_stop_before_start():
    """Verify Stop-before-start zero-I/O abort and clean instrument cleanup."""
    app, module = make_headless_moke_gui()
    from piec.measurement.runner import MeasurementRunner
    original_start = MeasurementRunner.start

    def stopping_start(runner_self, *args, **kwargs):
        token = original_start(runner_self, *args, **kwargs)
        app.stop_measurement()
        return token

    with patch.object(MeasurementRunner, "start", stopping_start):
        app.run_measurement()

    assert app.runner.join(timeout=5)
    app._poll_events()

    assert app.runner.run_state == RunState.ABORTED
    assert app.runner.safety_status in (SafetyStatus.NOT_NEEDED, SafetyStatus.SAFE)
    assert not app.is_measuring
    assert app.runner.can_close()
    assert len(app._instruments) == 0


def test_moke_gui_active_close_requests_stop_and_defers_close():
    """Verify active close requests cooperative stop and defers destruction until worker exit."""
    app, module = make_headless_moke_gui()
    app.dynamic_inputs["dwell_time"].get.return_value = "0.5"
    app.dynamic_inputs["points_per_cycle"].get.return_value = "11"

    app.run_measurement()
    assert app.runner.is_worker_alive

    finish_mock = Mock()
    app._finish_close = finish_mock

    app.on_closing()
    assert app.runner.is_closing is True
    assert app._close_when_safe is True
    assert not finish_mock.called

    assert app.runner.join(timeout=5)
    assert app.runner.can_close()

    app._poll_events()
    assert finish_mock.called
    assert len(app._instruments) == 0


def test_moke_gui_deferred_close_releases_connections_after_safety_retry(monkeypatch):
    """Verify deferred close retains connections while unsafe and releases them after retry."""
    app, module = make_headless_moke_gui()
    monkeypatch.setattr(module.messagebox, "showerror", Mock())

    def failing_shutdown(recorder):
        raise RuntimeError("failing hardware shutdown")

    monkeypatch.setattr(MokeMeasurement, "_safe_shutdown", failing_shutdown)

    app.run_measurement()
    assert app.runner.join(timeout=5)
    assert app.runner.safety_status == SafetyStatus.UNSAFE
    app._poll_events()

    instruments_before = list(app._instruments)
    assert len(instruments_before) >= 2

    finish_mock = Mock()
    app._finish_close = finish_mock

    # Close is requested and deferred because safety is UNSAFE
    app.on_closing()
    assert not finish_mock.called
    assert len(app._instruments) >= 2

    # Now retry safing with successful shutdown
    monkeypatch.undo()
    app.experiment.safe_shutdown()
    assert app.runner.can_close()

    app._poll_events()
    assert finish_mock.called
    assert len(app._instruments) == 0


def test_moke_gui_reports_recovery_paths_from_failed_save_record(monkeypatch, tmp_path, capsys):
    """Verify failed save publication reports recoverable staging paths from RunRecord metadata."""
    from piec.measurement import persistence
    app, module = make_headless_moke_gui(tmp_path=tmp_path)
    app.save_data.get.return_value = True
    monkeypatch.setattr(module.messagebox, "showerror", Mock())
    monkeypatch.setattr(
        persistence, "atomic_publish_no_replace",
        Mock(side_effect=OSError("filesystem publication failed")),
    )
    app.run_measurement()
    assert app.runner.join(timeout=5)

    record = app.experiment.last_run_record
    paths = record.metadata["recoverable_staging_paths"]
    assert record.state == RunState.FAILED
    assert paths and all(Path(p).is_file() for p in paths)

    app._poll_events()
    output = capsys.readouterr().out
    assert "Recoverable data staging paths:" in output
    assert all(p in output for p in paths) or str(paths) in output


def test_moke_gui_geometry_change_updates_title():
    """Verify geometry changes update plot title dynamically."""
    app, module = make_headless_moke_gui()
    snap = MokeSnapshot(
        raw=pd.DataFrame({"field_calibrated": [0.0, 1.0], "detector_voltage": [0.1, 0.2]}),
        last_cycle=pd.DataFrame(),
        cycle_average=pd.DataFrame(),
        completed_cycles=1,
        field_column="field_calibrated",
    )
    app._plot_snapshot(snap)
    app.ax.set_title.assert_called_with("MOKE loop: in-plane")

    app.geometry_entry.get.return_value = "out-of-plane"
    app._redraw_current()
    app.ax.set_title.assert_called_with("MOKE loop: out-of-plane")


def test_moke_gui_setup_validation_errors(monkeypatch):
    """Verify invalid setup inputs show error dialog and clean up before starting runner."""
    app, module = make_headless_moke_gui()
    mock_showerror = Mock()
    monkeypatch.setattr(module.messagebox, "showerror", mock_showerror)

    # Inverted output min/max
    app.dynamic_inputs["output_min"].get.return_value = "5.0"
    app.dynamic_inputs["output_max"].get.return_value = "-5.0"

    app.run_measurement()
    assert mock_showerror.called
    assert app.runner is None
    assert len(app._instruments) == 0

