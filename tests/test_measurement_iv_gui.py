"""
Tests for IV Sweep GUI integration.

Verifies that the GUI consumer operates against the target BaseMeasurement API:
- Proper imports and no legacy shims;
- Passes output_dir to IVSweep;
- Uses MeasurementRunner and handles queues;
- Uses plain lowercase 'voltage' and 'current' columns and unit metadata.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pandas as pd
import pytest

from piec.measurement.contracts import MeasurementSnapshot, RunState, SafetyReport, SafetyStatus, TerminalEvent


def test_iv_sweep_gui_imports_and_structure():
    """Verify IV Sweep GUI imports target components without legacy shims."""
    import importlib.util
    gui_path = Path("Measurements/DCIV/IV_sweep_GUI.py")
    assert gui_path.is_file()

    with open(gui_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Must import MeasurementRunner and read_measurement_csv
    assert "from piec.measurement.runner import MeasurementRunner" in content
    assert "from piec.measurement.persistence import read_measurement_csv" in content
    assert "standard_csv_to_metadata_and_data" not in content
    # Target columns
    assert '"voltage", "current"' in content
    assert "save_dir=save_dir" not in content


def test_iv_sweep_gui_logic_headless():
    """Verify GUI instantiation and measurement setup in headless mode."""
    # We test the logic without starting a Tk mainloop
    from Measurements.DCIV.IV_sweep_GUI import IVSweepApp, DEFAULTS

    root = MagicMock()
    with patch("Measurements.DCIV.IV_sweep_GUI.MeasurementApp.__init__") as mock_init, \
         patch("Measurements.DCIV.IV_sweep_GUI.MeasurementRunner") as mock_runner_cls, \
         patch("Measurements.DCIV.IV_sweep_GUI.VirtualSourcemeter") as mock_vsm:

        mock_vsm_inst = MagicMock()
        mock_vsm.return_value = mock_vsm_inst

        app = IVSweepApp.__new__(IVSweepApp)
        app.root = root
        app.run_button = MagicMock()
        app.sm_address_entry = MagicMock()
        app.sm_address_entry.get.return_value = "VIRTUAL"
        app.save_dir_entry = MagicMock()
        app.save_dir_entry.get.return_value = ""
        app.sense_mode_entry = MagicMock()
        app.sense_mode_entry.get.return_value = "2W"
        app.dynamic_inputs = {
            "v_start": MagicMock(get=MagicMock(return_value="0.0")),
            "v_stop": MagicMock(get=MagicMock(return_value="1.0")),
            "num_steps": MagicMock(get=MagicMock(return_value="5")),
            "current_compliance": MagicMock(get=MagicMock(return_value="0.1")),
            "dwell_time": MagicMock(get=MagicMock(return_value="0.01")),
        }
        app.x_axis = MagicMock()
        app.x_axis.get.return_value = "voltage"
        app.y_axis = MagicMock()
        app.y_axis.get.return_value = "current"
        app.ax = MagicMock()
        app.canvas = MagicMock()

        # Run measurement
        app.run_measurement()

        assert hasattr(app, "experiment")
        assert app.experiment.v_start == 0.0
        assert app.experiment.v_stop == 1.0
        assert app.experiment.num_steps == 5
        assert app.experiment.output_dir is None
        assert mock_runner_cls.called

        # Test plotting helper with dataframe
        test_df = pd.DataFrame({"voltage": [0.0, 0.5, 1.0], "current": [0.0, 0.005, 0.01]})
        app._plot_dataframe(test_df)
        assert app.ax.plot.called
        assert app.ax.set_xlabel.called
        assert app.ax.set_ylabel.called
        assert app.canvas.draw.called
