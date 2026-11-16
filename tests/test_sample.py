"""Dynamic architectural contract tests for PIEC's 3-level simulation hierarchy."""
from __future__ import annotations

import ast
import importlib
import inspect
from pathlib import Path
import textwrap

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
    assert {"resistor", "fe_material", "magnetic/moke", "magnetic/amr"} <= set(catalog)

    for entry in catalog.values():
        for model_cls in entry["models"].values():
            params = get_model_parameters(model_cls)
            assert params
            string_params = {k: str(v) for k, v in params.items()}
            sample = create_sample_from_parameters(model_cls, string_params, name=f"hub_{model_cls.__name__}")
            assert isinstance(sample, entry["category_class"])
            assert VirtualInstrument.sample is sample
            assert get_model_parameters(model_cls, current_sample=sample) == params


def test_simulation_hub_opens_to_gui_default_sample(monkeypatch):
    tk = pytest.importorskip("tkinter")
    from piec.measurement.gui_utils import MeasurementApp
    from piec.simulation.fe_material.landau_ferroelectric import LandauFerroelectric
    from piec.simulation.resistor.ohmic_resistor import OhmicResistor
    from piec.simulation.simulation_hub import SimulationHubWindow

    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip("A display is required for Tkinter SimulationHub tests")

    monkeypatch.setattr(VirtualInstrument, "sample", LandauFerroelectric())
    try:
        cases = [
            (("sourcemeter",), None, "resistor", "OhmicResistor", "resistance", "1000.0"),
            (("awg", "oscilloscope"), staticmethod(lambda: OhmicResistor(50.0)), "resistor", "OhmicResistor", "resistance", "50.0"),
            (("awg", "oscilloscope"), None, "fe_material", "LandauFerroelectric", "temperature", "300"),
            (("dmm", "dc_calibrator", "stepper_motor", "lockin"), None, "magnetic/amr", "CosSquaredAMR", "r_base", "100.0"),
            (("field_controller", "dmm", "gaussmeter"), None, "magnetic/moke", "ArctanMOKE", "coercivity", "100.0"),
        ]
        for instruments, override, expected_cat, expected_model, param_key, expected_val in cases:
            app_cls = type("TempApp", (MeasurementApp,), {"_instruments": instruments, "_default_sample": override})
            app = app_cls.__new__(app_cls)
            app._instrument_types = {name: name for name in instruments}
            hub = SimulationHubWindow(root, default_sample=app.get_default_sample())
            try:
                assert hub.category_var.get() == expected_cat
                assert hub.model_var.get() == expected_model
                assert hub.param_vars[param_key].get() == expected_val
            finally:
                hub.window.destroy()
    finally:
        root.destroy()


def test_universal_sample_io_across_calibrator_dmm_and_amr_resistor(monkeypatch, tmp_path):
    from types import SimpleNamespace
    import numpy as np
    from piec.drivers.dc_calibrator.virtual_calibrator import VirtualCalibrator
    from piec.drivers.dmm.virtual_dmm import VirtualDMM
    from piec.drivers.lockin.virtual_lockin import VirtualLockin
    from piec.drivers.stepper_motor.virtual_stepper import VirtualStepper
    from piec.measurement.amr import AMR
    from piec.simulation.resistor.ohmic_resistor import OhmicResistor

    resistor = OhmicResistor(resistance=1000.0)
    monkeypatch.setattr(VirtualInstrument, "sample", resistor)

    calibrator = VirtualCalibrator()
    dmm = VirtualDMM()
    calibrator.set_output(2.5, mode="voltage")
    assert dmm.get_voltage() == pytest.approx(2.5)
    assert resistor.get_current() == pytest.approx(0.0025)
    calibrator.set_output(0.004, mode="current")
    assert dmm.get_voltage() == pytest.approx(4.0)
    calibrator.output(False)
    assert dmm.get_voltage() == pytest.approx(0.0)

    elapsed = [0.0]
    monkeypatch.setattr(
        "piec.measurement.magneto_transport.time",
        SimpleNamespace(time=lambda: elapsed[0], sleep=lambda s: elapsed.__setitem__(0, elapsed[0] + s)),
    )
    experiment = AMR(
        dmm=dmm,
        calibrator=calibrator,
        arduino=VirtualStepper(),
        lockin=VirtualLockin(),
        field=100.0,
        angle_step=90.0,
        total_angle=180.0,
        measure_time=0.15,
        save_dir=str(tmp_path),
        live_plot=False,
    )
    assert VirtualInstrument.sample is resistor
    experiment.run_experiment(configure_lockin=False)
    np.testing.assert_allclose(experiment.data["X"], 1e-3)
    np.testing.assert_allclose(experiment.data["Y"], 1e-4)