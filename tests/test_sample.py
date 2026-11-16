"""Dynamic architectural contract tests for PIEC's 3-level simulation hierarchy."""
from __future__ import annotations

import ast
import importlib
import inspect
from pathlib import Path
import textwrap

import numpy as np
import pytest

import piec.drivers as drivers_pkg
import piec.simulation as simulation_pkg
from piec.drivers.virtual_instrument import VirtualInstrument
from piec.simulation.sample import Sample
from piec.simulation.simulation_hub import (
    create_sample_from_parameters,
    discover_simulation_catalog,
    get_model_parameters,
)

SIMULATION_PATH = Path(simulation_pkg.__file__).resolve().parent
DRIVERS_PATH = Path(drivers_pkg.__file__).resolve().parent


def _local_subclasses(module, base_cls):
    return [
        obj for name, obj in inspect.getmembers(module, inspect.isclass)
        if obj is not base_cls and obj.__module__ == module.__name__
        and name == obj.__name__ and issubclass(obj, base_cls)
    ]


def _discover_category_dirs():
    dirs = []
    for cat_dir in sorted(SIMULATION_PATH.rglob("*")):
        if not cat_dir.is_dir():
            continue
        rel_parts = cat_dir.relative_to(SIMULATION_PATH).parts
        if any(part.startswith("_") for part in rel_parts):
            continue
        if (cat_dir / f"{cat_dir.name}.py").is_file():
            dirs.append((cat_dir, rel_parts))
    assert dirs
    return dirs


def _discover_categories():
    categories = {}
    for cat_dir, rel_parts in _discover_category_dirs():
        pkg_prefix = ".".join(("piec", "simulation", *rel_parts))
        mod = importlib.import_module(f"{pkg_prefix}.{cat_dir.name}")
        found = _local_subclasses(mod, Sample)
        assert len(found) == 1, f"{mod.__name__} must define one Sample subclass, found {found}"
        categories["/".join(rel_parts)] = (cat_dir, pkg_prefix, found[0])
    return categories


def _discover_models():
    models = []
    for cat_dir, pkg_prefix, cat_cls in _discover_categories().values():
        for py_file in sorted(cat_dir.glob("*.py")):
            if py_file.stem in {"__init__", cat_dir.name} or py_file.stem.startswith("_"):
                continue
            mod = importlib.import_module(f"{pkg_prefix}.{py_file.stem}")
            for model_cls in _local_subclasses(mod, Sample):
                models.append((cat_cls, model_cls))
    assert models
    return models


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


_CATEGORIES = [entry[2] for entry in _discover_categories().values()]
_MODELS = _discover_models()
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
        assert _is_not_implemented_stub(fn), f"{cat_cls.__name__}.{name} must be a stub raising NotImplementedError"


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
    expected_categories = {key for key in _discover_categories() if key != "example"}
    assert set(catalog) == expected_categories

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
    from piec.measurement.gui_utils import MeasurementApp
    from piec.simulation.simulation_hub import SimulationHubWindow

    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip("A display is required for Tkinter SimulationHub tests")

    catalog = discover_simulation_catalog()
    all_models = [
        (cat_key, model_name, model_cls)
        for cat_key, entry in catalog.items()
        for model_name, model_cls in entry["models"].items()
    ]
    assert len(all_models) >= 2

    try:
        for cat_key, model_name, model_cls in all_models:
            other_cls = next(m_cls for o_cat, _, m_cls in all_models if o_cat != cat_key)
            monkeypatch.setattr(VirtualInstrument, "sample", other_cls())
            app_cls = type("TempApp", (MeasurementApp,), {"_default_sample": model_cls})
            app = app_cls.__new__(app_cls)
            hub = SimulationHubWindow(root, default_sample=app.get_default_sample())
            try:
                assert hub.category_var.get() == cat_key
                assert hub.model_var.get() == model_name
                for key, val in get_model_parameters(model_cls).items():
                    assert float(hub.param_vars[key].get()) == pytest.approx(float(val))
            finally:
                hub.window.destroy()
    finally:
        root.destroy()


@pytest.mark.parametrize("cat_cls,model_cls", _MODELS, ids=lambda p: p.__name__)
def test_all_models_support_universal_sample_io(cat_cls, model_cls, monkeypatch):
    sample = model_cls()
    assert isinstance(sample, cat_cls)
    monkeypatch.setattr(VirtualInstrument, "sample", sample)
    assert VirtualInstrument.sample is sample

    sample.set_field(25.0)
    assert sample.get_field() == pytest.approx(25.0)
    assert sample.current_field == pytest.approx(25.0)

    sample.set_angle(45.0)
    assert sample.get_angle() == pytest.approx(45.0)
    assert sample.current_angle == pytest.approx(45.0)

    sample.set_voltage(0.5)
    assert np.isfinite(sample.get_voltage())
    assert np.isfinite(sample.get_current())

    sample.set_current(1e-3)
    assert np.isfinite(sample.get_voltage())
    assert np.isfinite(sample.get_current())
    assert np.isfinite(sample.get_resistance())

    t = np.linspace(0.0, 1e-3, 16)
    v = np.sin(2.0 * np.pi * 1e3 * t)
    sample.apply_waveform(v, t)
    v_out, t_out = sample.get_waveform()
    assert len(v_out) == len(t_out) == len(t)
    assert np.all(np.isfinite(v_out))