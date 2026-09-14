"""Headless GUI contract harness; no measurement-specific assertions or fixtures."""
import ast
import importlib.util
import inspect
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pandas as pd
import pytest
import tkinter as tk
from tkinter import ttk, messagebox

from piec.measurement import BaseMeasurement, SafetyReport, SafetyStatus
from piec.measurement.gui_utils import MeasurementApp

ROOT = Path(__file__).resolve().parents[2]


def discover_guis():
    """Import GUI application modules and select classes by base-class inheritance."""
    found = []
    for path in sorted((ROOT / 'Measurements').rglob('*.py')):
        tree = ast.parse(path.read_text(encoding='utf-8-sig'), filename=str(path))
        # Ordinary measurement scripts may perform I/O at module scope. Only
        # inspect application modules; unrelated scripts are never executed.
        if not any(isinstance(node, ast.ClassDef) for node in tree.body):
            continue
        if 'gui' not in path.stem.lower():
            continue
        name = '_gui_contract_' + '_'.join(path.relative_to(ROOT).with_suffix('').parts).replace(' ', '_')
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
        except Exception as error:
            raise AssertionError(f'GUI import failed: {path}') from error
        for cls in vars(module).values():
            if (inspect.isclass(cls) and cls.__module__ == name
                    and issubclass(cls, MeasurementApp) and cls is not MeasurementApp):
                found.append((module, cls))
    assert found, 'No MeasurementApp subclasses discovered'
    return found


class Widget(MagicMock):
    """Stateful widget double: values and button states are real, drawing is mocked."""
    def __init__(self, *args, **kwargs):
        super().__init__()
        self.options = dict(kwargs)
        self.value = kwargs.get('value', '')
        self.get.side_effect = lambda: self.value
        self.set.side_effect = lambda value: setattr(self, 'value', value)
        self.insert.side_effect = lambda index, value: setattr(self, 'value', str(value))
        self.delete.side_effect = lambda *args: setattr(self, 'value', '')
        self.current.side_effect = lambda index=0: setattr(self, 'value', self.options['values'][index])
        self.config.side_effect = lambda **options: self.options.update(options)
        self.configure.side_effect = self.config.side_effect
        self.cget.side_effect = lambda name: self.options.get(name, '')
        self.__getitem__.side_effect = lambda name: self.options.get(name, '')
        self.__setitem__.side_effect = lambda name, value: self.options.update({name: value})
        self.winfo_children.return_value = []

    def _get_child_mock(self, **kwargs):
        return MagicMock(**kwargs)


@pytest.fixture
def gui(request, monkeypatch):
    module, cls = request.param
    gate, entered = threading.Event(), threading.Event()
    scenario = SimpleNamespace(failure=None, unsafe=False)
    expected = pd.DataFrame({'sample': [0., 1.], 'response': [2., 3.]})

    class ContractMeasurement(BaseMeasurement):
        def __init__(self, *args, **kwargs):
            super().__init__()

        def _capture_data(self, request, on_update):
            self.publish_snapshot({'raw': expected, 'raw_window': expected, 'data': expected})
            entered.set()
            if not gate.wait(5):
                raise TimeoutError('GUI test did not release acquisition')
            if scenario.failure:
                raise RuntimeError(scenario.failure)
            return expected.copy()

        def _safe_shutdown(self):
            return SafetyReport(status=SafetyStatus.UNSAFE if scenario.unsafe else SafetyStatus.SAFE)

    # Substitute only the experiment dependency, retaining real GUI run handlers
    # and the real MeasurementRunner, queues, threads, and lifecycle engine.
    for name, value in list(vars(module).items()):
        if inspect.isclass(value) and issubclass(value, BaseMeasurement) and value is not BaseMeasurement:
            monkeypatch.setattr(module, name, ContractMeasurement)
    for namespace in (tk, ttk):
        for name, value in list(vars(namespace).items()):
            if inspect.isclass(value) and issubclass(value, (tk.Widget, tk.Variable)):
                monkeypatch.setattr(namespace, name, Widget)
    monkeypatch.setattr(MeasurementApp, 'setup_styles', lambda self: None)
    monkeypatch.setattr(MeasurementApp, 'setup_log_console', lambda self, parent: setattr(self, 'log_text', Widget()))
    def setup_plot(self, parent):
        self.ax, self.canvas, self.fig = Mock(), Mock(), Mock()
    monkeypatch.setattr(MeasurementApp, 'setup_plot', setup_plot)
    monkeypatch.setattr(MeasurementApp, 'get_visa_resources', lambda self: [])
    monkeypatch.setattr(cls, 'save_settings', lambda self: None)
    monkeypatch.setattr(cls, 'load_settings', lambda self: None)
    errors = Mock()
    monkeypatch.setattr(messagebox, 'showerror', errors)
    monkeypatch.setattr(messagebox, 'showwarning', Mock())
    root = Widget()
    root.winfo_exists.return_value = True
    stdout, stderr = sys.stdout, sys.stderr
    try:
        app = cls(root)
    finally:
        sys.stdout, sys.stderr = stdout, stderr
    for name, widget in vars(app).items():
        if name.endswith('address_entry'):
            widget.set('VIRTUAL')
    app.save_dir_entry.delete(0, 'end')
    # GUIs with an explicit experiment factory need no measurement settings.
    if hasattr(app, '_create_experiment'):
        def create():
            app.experiment = ContractMeasurement()
            app._save_this_run = False
        monkeypatch.setattr(app, '_create_experiment', create)
    selector = getattr(app, 'measurement_type', None)
    if selector is not None and not selector.get():
        selector.current(0)
    # Observe delivery at the rendering boundary, independent of scientific axes.
    rendered = Mock()
    for name in ('_plot_dataframe', '_plot_snapshot', '_show_snapshot', '_render_plot'):
        if hasattr(app, name):
            monkeypatch.setattr(app, name, rendered)
    polls = [getattr(app, name) for name in ('_poll_runner', '_poll_events') if hasattr(app, name)]
    assert len(polls) == 1, f'{cls.__name__} needs one runner event consumer'
    harness = SimpleNamespace(app=app, poll=polls[0], rendered=rendered, errors=errors,
                              gate=gate, entered=entered, scenario=scenario, expected=expected)
    try:
        yield harness
    finally:
        gate.set()
        if app.runner is not None:
            app.runner.request_stop()
            assert app.runner.join(timeout=5), 'GUI left a worker running'
        app._close_instruments()
        if hasattr(app, 'console'):
            app.console.close()
