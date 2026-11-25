"""Dynamic architectural contract tests for PIEC's 3-level simulation hierarchy."""
from __future__ import annotations

import ast
import inspect
import textwrap

import numpy as np
import pytest

from pathlib import Path

import piec.drivers as drivers_pkg
from piec.drivers.virtual_instrument import VirtualInstrument
from piec.simulation.sample import Sample
from piec.simulation.simulation_hub import (
    create_sample_from_parameters,
    discover_simulation_catalog,
    get_model_parameters,
)

DRIVERS_PATH = Path(drivers_pkg.__file__).resolve().parent


def _is_not_implemented_stub(fn):
    tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    fn_node = next(n for n in tree.body if isinstance(n, ast.FunctionDef))
    body = fn_node.body
    if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0].value, "value", None), str):
        body = body[1:]
    if not body:
        return True
    if len(body) != 1:
        return False
    stmt = body[0]
    if isinstance(stmt, (ast.Pass, ast.Expr)) and (
        isinstance(stmt, ast.Pass) or getattr(stmt.value, "value", None) is ...
    ):
        return True
    if isinstance(stmt, ast.Raise) and stmt.exc is not None:
        exc_id = getattr(stmt.exc, "id", None) or getattr(getattr(stmt.exc, "func", None), "id", None)
        return exc_id == "NotImplementedError"
    return False


_CATALOG = discover_simulation_catalog()
_CATEGORIES = [entry["category_class"] for entry in _CATALOG.values()]
_MODELS = [
    (entry["category_class"], model_cls)
    for entry in _CATALOG.values()
    for model_cls in entry["models"].values()
]
_ALL_CLASSES = [Sample, *_CATEGORIES, *(m for _, m in _MODELS)]


@pytest.mark.parametrize("cat_cls", _CATEGORIES, ids=lambda c: c.__name__)
def test_category_contracts_are_pure_stubs(cat_cls):
    assert Sample in cat_cls.__bases__
    assert [n for n in cat_cls.__dict__ if n.startswith(("_compute_", "_update_"))] == []
    public_methods = [
        (n, fn) for n, fn in vars(cat_cls).items() if inspect.isfunction(fn) and not n.startswith("_")
    ]
    assert public_methods
    for name, fn in public_methods:
        assert _is_not_implemented_stub(fn), f"{cat_cls.__name__}.{name} must be a stub"


@pytest.mark.parametrize("cat_cls,model_cls", _MODELS, ids=lambda p: p.__name__)
def test_models_inherit_category_and_implement_all_contract_methods(cat_cls, model_cls):
    assert issubclass(model_cls, cat_cls)
    for name, parent_fn in vars(cat_cls).items():
        if name.startswith("_") or not inspect.isfunction(parent_fn):
            continue
        child_fn = getattr(model_cls, name, None)
        assert callable(child_fn) and child_fn is not parent_fn
        assert not _is_not_implemented_stub(child_fn), f"{model_cls.__name__}.{name} is still a stub"

        p_params = [p for n, p in inspect.signature(parent_fn).parameters.items() if n != "self"]
        c_params = [p for n, p in inspect.signature(child_fn).parameters.items() if n != "self"]
        assert [(p.name, p.kind) for p in c_params[:len(p_params)]] == [(p.name, p.kind) for p in p_params]
        for pp, cp in zip(p_params, c_params):
            if pp.default is not inspect.Parameter.empty:
                assert cp.default == pp.default
        for extra in c_params[len(p_params):]:
            assert extra.kind is inspect.Parameter.KEYWORD_ONLY and extra.default is not inspect.Parameter.empty


@pytest.mark.parametrize("sample_cls", _ALL_CLASSES, ids=lambda c: c.__name__)
def test_all_discovered_samples_parameter_dict_and_name(sample_cls):
    params = {}
    sample = sample_cls(parameter_dict=params, name="custom")
    assert isinstance(sample, Sample)
    assert sample.name == "custom"
    assert sample.parameter_dict is params

    first, second = sample_cls(), sample_cls()
    first.parameter_dict["extra"] = 1
    assert "extra" not in second.parameter_dict


def test_drivers_do_not_import_simulation():
    offenders = [
        str(py_file.relative_to(DRIVERS_PATH))
        for py_file in sorted(DRIVERS_PATH.rglob("*.py"))
        if "piec.simulation" in py_file.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_simulation_hub_discovers_and_swaps_global_samples(monkeypatch):
    monkeypatch.setattr(VirtualInstrument, "sample", None)
    catalog = discover_simulation_catalog()
    assert catalog

    for entry in catalog.values():
        for model_cls in entry["models"].values():
            params = get_model_parameters(model_cls)
            assert params
            string_params = {k: str(v) for k, v in params.items()}
            sample = create_sample_from_parameters(model_cls, string_params, name=f"hub_{model_cls.__name__}")
            assert isinstance(sample, entry["category_class"])
            assert VirtualInstrument.sample is sample
            assert get_model_parameters(model_cls, current_sample=sample) == params

            first_key = next(
                k for k, v in params.items() if isinstance(v, (int, float)) and not isinstance(v, bool)
            )
            modified_val = float(params[first_key]) * 2.0 if params[first_key] else 1.0
            modified_params = dict(string_params, **{first_key: str(modified_val)})
            modified_sample = create_sample_from_parameters(model_cls, modified_params)
            assert VirtualInstrument.sample is modified_sample
            assert get_model_parameters(model_cls, current_sample=modified_sample)[first_key] == pytest.approx(modified_val)


def test_simulation_hub_opens_to_gui_default_sample(monkeypatch):
    tk = pytest.importorskip("tkinter")
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip("A display is required for Tkinter SimulationHub tests")

    try:
        from piec.measurement.experiment import Experiment
        from piec.measurement.gui_utils import MeasurementApp
        from piec.simulation.simulation_hub import SimulationHubWindow

        catalog = discover_simulation_catalog()
        all_models = [
            (cat_key, model_name, model_cls)
            for cat_key, entry in catalog.items()
            for model_name, model_cls in entry["models"].items()
        ]
        assert len(all_models) >= 2

        for cat_key, model_name, model_cls in all_models:
            other_cls = next(m_cls for o_cat, _, m_cls in all_models if o_cat != cat_key)
            monkeypatch.setattr(VirtualInstrument, "sample", other_cls())
            exp_cls = type("TempExperiment", (Experiment,), {"_default_virtual_sample": model_cls})
            app_cls = type("TempApp", (MeasurementApp,), {"_experiment_cls": exp_cls})
            app = app_cls.__new__(app_cls)
            hub = SimulationHubWindow(root, default_sample=app.get_default_sample())
            try:
                assert set(hub.catalog.keys()) == {cat_key}
                assert hub.category_var.get() == cat_key
                assert hub.model_var.get() == model_name
                for key, val in get_model_parameters(model_cls).items():
                    assert float(hub.param_vars[key].get()) == pytest.approx(float(val))
            finally:
                hub.window.destroy()
    finally:
        root.destroy()


@pytest.mark.parametrize("cat_cls,model_cls", _MODELS, ids=lambda p: p.__name__)
def test_models_execute_contract_methods_and_report_unsupported_calls(cat_cls, model_cls, capsys):
    sample = model_cls()
    assert isinstance(sample, cat_cls)

    t = np.linspace(0.0, 1e-3, 16)
    v = np.sin(2.0 * np.pi * 1e3 * t)

    if hasattr(cat_cls, "apply_voltage"):
        dc_current = sample.apply_voltage(0.5)
        assert np.isfinite(dc_current)
        wf_current = sample.apply_voltage(v, t)
        assert len(wf_current) == len(t)
        assert np.all(np.isfinite(wf_current))

    if hasattr(cat_cls, "apply_current"):
        if "angle" in inspect.signature(sample.apply_current).parameters:
            assert np.isfinite(sample.apply_current(1e-3, angle=45.0, field=25.0))
        else:
            assert np.isfinite(sample.apply_current(1e-3))

    if hasattr(cat_cls, "apply_field"):
        assert np.isfinite(sample.apply_field(25.0))

    assert sample.unsupported_stimulus(1.0) is None
    captured = capsys.readouterr()
    assert "[UNSUPPORTED]" in captured.out