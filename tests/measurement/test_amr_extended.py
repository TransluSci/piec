"""
Comprehensive tests for AMR / MagnetoTransport modernization:
- Dual excitation sources (internal Lock-in vs external Sourcemeter).
- Automated safe shutdown for external current source without manual lambdas.
- Dual readout modes (AC Lock-in vs DC DMM).
- Canonical schema preservation (angle, field, x, y) in both modes.
- Interactive bench tuning & excitation testing (TuningStatus).
- Strict non-overwriting guarantee for manual bench dials / front-panel settings.
- GUI interactive bench tuning actions (test_excitation_action, auto_gain_action, UI toggles).
"""

import inspect
import math
import sys
import tkinter as tk
from tkinter import ttk, messagebox
from unittest.mock import Mock, MagicMock
import pytest
import pandas as pd

from piec.drivers.dc_calibrator.virtual_calibrator import VirtualCalibrator
from piec.drivers.dmm.virtual_dmm import VirtualDMM
from piec.drivers.stepper_motor.virtual_stepper import VirtualStepper
from piec.drivers.lockin.virtual_lockin import VirtualLockin
from piec.drivers.sourcemeter.virtual_sourcemeter import VirtualSourcemeter
from piec.simulation.setups import connect_amr_plant
from piec.measurement.amr import (
    AMR,
    MagnetoTransport,
    TuningStatus,
    SampleExcitation,
    TransportReadout,
    AMRSetupProfile,
)
from piec.measurement.contracts import RunState
from piec.measurement.gui_utils import MeasurementApp
from Measurements.AMR.amr_GUI import AMRApp
from tests.support.gui_contract import Widget


def _make_virtual_amr_bench():
    cal = VirtualCalibrator("VIRTUAL", voltage_callibration=10000.0)
    dmm = VirtualDMM("VIRTUAL")
    stepper = VirtualStepper("VIRTUAL")
    lockin = VirtualLockin("VIRTUAL")
    sm = VirtualSourcemeter("VIRTUAL")
    plant = connect_amr_plant(cal, dmm, stepper, lockin, field_scale=10000.0)
    sm.set_load_hook(lambda mode, stimulus, compliance: plant.get_voltage_response(stimulus))
    return cal, dmm, stepper, lockin, sm, plant


def test_amr_with_external_sourcemeter():
    """Verify external Sourcemeter current source is configured and safely shutdown on completion."""
    cal, dmm, stepper, lockin, sm, plant = _make_virtual_amr_bench()

    exp = AMR(
        dmm=dmm,
        calibrator=cal,
        stepper=stepper,
        lockin=lockin,
        current_source=sm,
        current=2.5e-3,
        compliance=4.0,
        field=50.0,
        angle_step=90.0,
        total_angle=90.0,
    )

    assert exp.sample_excitation is not None
    assert exp.sample_excitation.source_type == "external"
    assert exp.sample_excitation.current == 2.5e-3
    assert exp.sample_excitation.compliance == 4.0

    # Execute full run with save=False
    df = exp.run_experiment(save=False)
    assert exp.last_run_record.state == RunState.COMPLETED
    assert not df.empty
    assert list(exp.ordered_columns) == ["angle", "field", "x", "y"]

    # Sourcemeter output must be turned OFF automatically by safe shutdown
    assert sm.state["output_on"] is False


def test_amr_dc_readout_with_dmm():
    """Verify DC mode with DMM readout maps X=V_dc, Y=0.0 preserving canonical amr schema."""
    cal, dmm, stepper, lockin, sm, plant = _make_virtual_amr_bench()

    # In DC mode, DMM is the readout measuring voltage
    dmm.voltage_reader = lambda: plant.get_voltage_response(sm.state.get("source_current", 0.0))[0]

    exp = AMR(
        dmm=dmm,
        calibrator=cal,
        stepper=stepper,
        readout=dmm,
        current_source=sm,
        current=1e-3,
        compliance=3.0,
        field=20.0,
        angle_step=180.0,
        total_angle=180.0,
    )

    assert exp.transport_readout.signal_mode == "dmm_voltage"
    assert exp.measurement_schema == "amr"

    df = exp.run_experiment(save=False)
    assert exp.last_run_record.state == RunState.COMPLETED
    assert set(df.columns) == {"angle", "field", "x", "y"}

    # Y must be strictly 0.0 in DC mode
    assert (df["y"] == 0.0).all()
    # X contains DC voltage
    assert not df["x"].empty
    # Safe shutdown was executed
    assert sm.state["output_on"] is False


def test_amr_test_excitation():
    """Verify pre-run bench tuning via test_excitation returns TuningStatus and leaves source de-energized."""
    cal, dmm, stepper, lockin, sm, plant = _make_virtual_amr_bench()

    exp = AMR(
        dmm=dmm,
        calibrator=cal,
        stepper=stepper,
        lockin=lockin,
        current_source=sm,
        current=1e-3,
        compliance=2.0,
    )

    status = exp.test_excitation(duration=0.01)
    assert isinstance(status, TuningStatus)
    assert math.isfinite(status.x)
    assert math.isfinite(status.y)
    assert math.isfinite(status.voltage)
    assert status.resistance is not None
    assert status.resistance > 0.0
    assert isinstance(status.overloaded, bool)

    # Post-condition: excitation must be turned off
    assert sm.state["output_on"] is False


def test_amr_strict_non_overwriting_guarantee():
    """Verify that lab operator physical/manual front-panel dials are strictly preserved."""
    cal, dmm, stepper, lockin, sm, plant = _make_virtual_amr_bench()

    # Simulate manual front panel adjustment on the Lock-in
    lockin.set_sensitivity("20uv/pa")
    assert lockin.state["sensitivity"] == "20uv/pa"

    # Operator creates AMR specifying a different sensitivity string (e.g. from a script template)
    exp = AMR(
        dmm=dmm,
        calibrator=cal,
        stepper=stepper,
        lockin=lockin,
        sensitivity="500uv/pa",
        field=0.0,
        angle_step=90.0,
        total_angle=90.0,
    )

    # Run with default preserve policy (configure_lockin=False)
    df = exp.run_experiment(save=False, options={"configure_lockin": False})
    assert exp.last_run_record.state == RunState.COMPLETED

    # The manual sensitivity on the hardware MUST NOT be overwritten
    assert lockin.state["sensitivity"] == "20uv/pa"
    assert exp.measurement_metadata["readout_configuration"] == "preserve"


def test_amr_lockin_pure_readout_in_preserve_mode():
    """Verify that in preserve mode, no configuration commands are sent to the lockin besides readout."""
    cal, dmm, stepper, lockin, sm, plant = _make_virtual_amr_bench()

    # Wrap lockin methods with spies to track calls
    called_methods = []
    orig_configure_reference = getattr(lockin, "configure_reference", None)
    orig_configure_gain_filters = getattr(lockin, "configure_gain_filters", None)
    orig_set_sensitivity = getattr(lockin, "set_sensitivity", None)
    orig_get_X_Y = lockin.get_X_Y

    lockin.configure_reference = lambda *a, **kw: called_methods.append("configure_reference")
    lockin.configure_gain_filters = lambda *a, **kw: called_methods.append("configure_gain_filters")
    lockin.set_sensitivity = lambda *a, **kw: called_methods.append("set_sensitivity")
    
    def tracked_get_X_Y(*a, **kw):
        called_methods.append("get_X_Y")
        return orig_get_X_Y(*a, **kw)
    lockin.get_X_Y = tracked_get_X_Y

    exp = AMR(
        dmm=dmm,
        calibrator=cal,
        stepper=stepper,
        lockin=lockin,
        sensitivity="10uv/pa",
        field=0.0,
        angle_step=90.0,
        total_angle=90.0,
    )

    df = exp.run_experiment(save=False, options={"configure_lockin": False})
    assert exp.last_run_record.state == RunState.COMPLETED
    assert not df.empty

    # Verify NO configuration commands were sent to the lock-in
    assert "configure_gain_filters" not in called_methods
    assert "set_sensitivity" not in called_methods
    # Only readout was performed
    assert "get_X_Y" in called_methods


def test_amr_auto_gain():
    """Verify auto_gain queries lockin and updates metadata."""
    cal, dmm, stepper, lockin, sm, plant = _make_virtual_amr_bench()

    exp = AMR(
        dmm=dmm,
        calibrator=cal,
        stepper=stepper,
        lockin=lockin,
    )

    # Mock auto_gain on VirtualLockin
    lockin.auto_gain = lambda: "100uv/pa"

    result = exp.auto_gain()
    assert result == "100uv/pa"
    assert exp.measurement_metadata["sensitivity"] == "100uv/pa"


def _create_mock_gui_app(monkeypatch):
    """Creates a headless AMRApp instance with mock widgets."""
    orig_widget_classes = (tk.Widget, tk.Variable)
    for namespace in (tk, ttk):
        for name, value in list(vars(namespace).items()):
            if inspect.isclass(value) and issubclass(value, orig_widget_classes):
                monkeypatch.setattr(namespace, name, Widget)
    monkeypatch.setattr(MeasurementApp, "setup_styles", lambda self: None)
    monkeypatch.setattr(MeasurementApp, "setup_log_console", lambda self, parent: setattr(self, "log_text", Widget()))
    monkeypatch.setattr(MeasurementApp, "setup_plot", lambda self, parent: (setattr(self, "ax", Mock()), setattr(self, "canvas", Mock()), setattr(self, "fig", Mock())))
    monkeypatch.setattr(MeasurementApp, "get_visa_resources", lambda self: [])
    monkeypatch.setattr(AMRApp, "save_settings", lambda self: None)
    monkeypatch.setattr(AMRApp, "load_settings", lambda self: None)
    monkeypatch.setattr(messagebox, "showerror", Mock())
    monkeypatch.setattr(messagebox, "showwarning", Mock())
    monkeypatch.setattr(messagebox, "showinfo", Mock())

    root = Widget()
    root.winfo_exists.return_value = True
    app = AMRApp(root)
    return app


def test_amr_gui_readout_mode_and_source_toggles(monkeypatch):
    """Verify AMRApp dynamically enables/disables widgets based on readout mode and current source."""
    app = _create_mock_gui_app(monkeypatch)

    # Default is Lock-in (AC) and Current Source NONE
    assert app.readout_mode_entry.get() == "Lock-in (AC)"
    assert app.current_source_entry.get() == "NONE"

    # Switch to DMM (DC)
    app.readout_mode_entry.set("DMM (DC)")
    app._update_ui_state()
    assert app.dynamic_inputs["amplitude"].options["state"] == "disabled"
    assert app.dynamic_inputs["frequency"].options["state"] == "disabled"
    assert app.dynamic_inputs["sensitivity"].options["state"] == "disabled"
    assert app.lockin_address_entry.options["state"] == "disabled"

    # Switch to Sourcemeter VIRTUAL
    app.current_source_entry.set("VIRTUAL")
    app._update_ui_state()
    assert app.dynamic_inputs["current"].options["state"] == "normal"
    assert app.dynamic_inputs["compliance"].options["state"] == "normal"

    # Switch back to Lock-in (AC)
    app.readout_mode_entry.set("Lock-in (AC)")
    app._update_ui_state()
    assert app.dynamic_inputs["amplitude"].options["state"] == "normal"
    assert app.dynamic_inputs["frequency"].options["state"] == "normal"
    assert app.dynamic_inputs["sensitivity"].options["state"] == "normal"
    assert app.lockin_address_entry.options["state"] == "normal"


def test_amr_gui_bench_tuning_actions(monkeypatch):
    """Verify AMRApp test_excitation_action and auto_gain_action execute safely and update status labels."""
    app = _create_mock_gui_app(monkeypatch)

    # Configure virtual addresses
    app.dmm_address_entry.set("VIRTUAL")
    app.calibrator_address_entry.set("VIRTUAL")
    app.stepper_address_entry.set("VIRTUAL")
    app.lockin_address_entry.set("VIRTUAL")
    app.current_source_entry.set("NONE")

    # Run excitation test action
    app.test_excitation_action()
    assert "Signal: X =" in app.tune_signal_label.options.get("text", "")
    assert not app._instruments  # Connections safely cleaned up

    # Run auto gain action
    app.auto_gain_action()
    assert not app._instruments  # Connections safely cleaned up


def test_amr_gui_scrollable_sidebar(monkeypatch):
    """Verify AMRApp inherits scrollable sidebar canvas, scrollbar, and mousewheel handling."""
    app = _create_mock_gui_app(monkeypatch)

    assert hasattr(app, "left_canvas")
    assert hasattr(app, "left_scrollbar")
    assert hasattr(app, "left_container")
    assert hasattr(app, "left_panel")

    # Simulate mousewheel event over sidebar widget
    event = MagicMock()
    event.widget = app.left_panel
    event.delta = -120
    app._on_sidebar_mousewheel(event)
    app.left_canvas.yview_scroll.assert_called_with(1, "units")
