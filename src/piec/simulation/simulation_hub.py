"""Dynamic sample discovery and interactive Simulation Hub GUI."""
from __future__ import annotations

import importlib
import inspect
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

from piec.drivers.virtual_instrument import VirtualInstrument
from piec.simulation.sample import Sample

SIMULATION_PATH = Path(__file__).resolve().parent


def _local_subclasses(module, base_cls):
    """Return concrete subclasses defined directly in ``module``."""
    return [
        obj for name, obj in inspect.getmembers(module, inspect.isclass)
        if obj is not base_cls and obj.__module__ == module.__name__
        and name == obj.__name__ and issubclass(obj, base_cls)
    ]


def _flatten_dict(mapping, prefix=""):
    """Flatten nested parameter dictionaries into ``'section.key'`` pairs."""
    flat = {}
    for key, value in mapping.items():
        full_key = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            flat.update(_flatten_dict(value, prefix=full_key))
        else:
            flat[full_key] = value
    return flat


def _coerce_value(value, reference=None):
    """Convert GUI string inputs back to ``int`` / ``float`` / ``str``."""
    if not isinstance(value, str):
        return value
    text = value.strip()
    if isinstance(reference, bool):
        return text.lower() in {"1", "true", "yes", "on"}
    try:
        numeric = float(text)
    except ValueError:
        return text
    if isinstance(reference, int) and not isinstance(reference, bool) and numeric.is_integer():
        return int(numeric)
    return numeric


def _nested_get(mapping, dotted_key, default=inspect._empty):
    """Read a value from a nested dictionary using a dotted key."""
    cursor = mapping
    for part in dotted_key.split("."):
        if not isinstance(cursor, dict) or part not in cursor:
            return default
        cursor = cursor[part]
    return cursor


def _nested_set(mapping, dotted_key, value):
    """Assign a value inside a nested dictionary using a dotted key."""
    parts = dotted_key.split(".")
    cursor = mapping
    for part in parts[:-1]:
        cursor = cursor.setdefault(part, {})
    cursor[parts[-1]] = value


def discover_simulation_catalog(include_example=False):
    """Discover Level-2 simulation categories and Level-3 models recursively.

    Args:
        include_example (bool): Include template models under ``example/``.

    Returns:
        dict[str, dict]: Mapping ``category_key -> {'category_class', 'models'}``.
    """
    catalog = {}
    for cat_dir in sorted(SIMULATION_PATH.rglob("*")):
        if not cat_dir.is_dir():
            continue
        rel_parts = cat_dir.relative_to(SIMULATION_PATH).parts
        if any(part.startswith("_") for part in rel_parts):
            continue
        if not include_example and "example" in rel_parts:
            continue
        if not (cat_dir / f"{cat_dir.name}.py").is_file():
            continue

        pkg_prefix = ".".join(("piec", "simulation", *rel_parts))
        cat_mod = importlib.import_module(f"{pkg_prefix}.{cat_dir.name}")
        cat_classes = _local_subclasses(cat_mod, Sample)
        if len(cat_classes) != 1:
            continue
        cat_cls = cat_classes[0]

        models = {}
        for py_file in sorted(cat_dir.glob("*.py")):
            if py_file.stem in {"__init__", cat_dir.name} or py_file.stem.startswith("_"):
                continue
            mod = importlib.import_module(f"{pkg_prefix}.{py_file.stem}")
            for model_cls in _local_subclasses(mod, Sample):
                if issubclass(model_cls, cat_cls):
                    models[model_cls.__name__] = model_cls

        if models:
            catalog[cat_dir.relative_to(SIMULATION_PATH).as_posix()] = {
                "category_class": cat_cls,
                "models": models,
            }
    return catalog


def get_model_parameters(model_cls, current_sample=None):
    """Extract editable constructor and nested dictionary parameters for ``model_cls``."""
    params = {}
    sig = inspect.signature(model_cls.__init__)
    for param_name, param in sig.parameters.items():
        if param_name in {"self", "parameter_dict", "name"}:
            continue
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        if param.default is not inspect.Parameter.empty:
            params[param_name] = param.default

    module = inspect.getmodule(model_cls)
    if module is not None:
        for attr_name, attr_val in vars(module).items():
            if attr_name.startswith("DEFAULT_") and isinstance(attr_val, dict):
                for key, val in _flatten_dict(attr_val).items():
                    params.setdefault(key, val)

    if current_sample is not None and isinstance(current_sample, model_cls):
        active_dict = getattr(current_sample, "parameter_dict", {}) or {}
        for key, default in list(params.items()):
            if "." in key:
                current_val = _nested_get(active_dict, key, default)
                params[key] = current_val
            elif hasattr(current_sample, key):
                params[key] = getattr(current_sample, key)
            elif key in active_dict:
                params[key] = active_dict[key]
    return params


def create_sample_from_parameters(model_cls, params, name=None, set_global=True):
    """Instantiate ``model_cls`` from flat/dotted parameters and update global sample."""
    defaults = get_model_parameters(model_cls)
    init_sig = inspect.signature(model_cls.__init__).parameters
    kwargs = {}
    parameter_dict = {}

    for key, raw_value in params.items():
        coerced = _coerce_value(raw_value, defaults.get(key))
        if "." in key:
            _nested_set(parameter_dict, key, coerced)
        else:
            if key in init_sig:
                kwargs[key] = coerced
            parameter_dict[key] = coerced

    if "parameter_dict" in init_sig:
        kwargs["parameter_dict"] = parameter_dict
    if name and "name" in init_sig:
        kwargs["name"] = name

    sample = model_cls(**kwargs)
    if set_global:
        VirtualInstrument.sample = sample
    return sample


class SimulationHubWindow:
    """Interactive Tkinter window for choosing and parameterizing virtual samples."""

    def __init__(self, parent=None, include_example=False, default_sample=None):
        self._owns_root = parent is None
        self.window = tk.Tk() if self._owns_root else tk.Toplevel(parent)
        self.window.title("PIEC Simulation Hub")
        self.window.geometry("540x620")

        self.catalog = discover_simulation_catalog(include_example=include_example)
        self._default_sample = self._resolve_default_sample(default_sample)
        self.param_vars = {}

        self._build_ui()
        self._select_initial_model()

    @staticmethod
    def _resolve_default_sample(default_sample):
        if default_sample is None:
            return None
        if isinstance(default_sample, Sample):
            return default_sample
        if callable(default_sample):
            return default_sample()
        return None

    def _build_ui(self):
        container = ttk.Frame(self.window, padding=12)
        container.pack(fill=tk.BOTH, expand=True)

        self.status_var = tk.StringVar()
        ttk.Label(container, textvariable=self.status_var, font=("Helvetica", 10, "bold")).pack(
            fill=tk.X, pady=(0, 10)
        )

        selector_frame = ttk.LabelFrame(container, text="Sample Selection", padding=10)
        selector_frame.pack(fill=tk.X, pady=(0, 10))
        selector_frame.columnconfigure(1, weight=1)

        ttk.Label(selector_frame, text="Category:").grid(row=0, column=0, sticky="w", padx=4, pady=4)
        self.category_var = tk.StringVar()
        self.category_combo = ttk.Combobox(
            selector_frame,
            textvariable=self.category_var,
            values=list(self.catalog.keys()),
            state="readonly",
        )
        self.category_combo.grid(row=0, column=1, sticky="ew", padx=4, pady=4)
        self.category_combo.bind("<<ComboboxSelected>>", self._on_category_changed)

        ttk.Label(selector_frame, text="Model:").grid(row=1, column=0, sticky="w", padx=4, pady=4)
        self.model_var = tk.StringVar()
        self.model_combo = ttk.Combobox(selector_frame, textvariable=self.model_var, state="readonly")
        self.model_combo.grid(row=1, column=1, sticky="ew", padx=4, pady=4)
        self.model_combo.bind("<<ComboboxSelected>>", self._on_model_changed)

        ttk.Label(selector_frame, text="Sample Name:").grid(row=2, column=0, sticky="w", padx=4, pady=4)
        self.name_var = tk.StringVar()
        ttk.Entry(selector_frame, textvariable=self.name_var).grid(row=2, column=1, sticky="ew", padx=4, pady=4)

        params_outer = ttk.LabelFrame(container, text="Model Parameters", padding=6)
        params_outer.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        self.canvas = tk.Canvas(params_outer, highlightthickness=0)
        scrollbar = ttk.Scrollbar(params_outer, orient="vertical", command=self.canvas.yview)
        self.params_frame = ttk.Frame(self.canvas, padding=6)
        self.params_frame.bind(
            "<Configure>", lambda _: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )
        self.canvas.create_window((0, 0), window=self.params_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        buttons = ttk.Frame(container)
        buttons.pack(fill=tk.X)
        ttk.Button(buttons, text="APPLY TO GLOBAL SAMPLE", command=self.apply_sample).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5)
        )
        ttk.Button(buttons, text="RESET DEFAULTS", command=self.reset_defaults).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 0)
        )

    def _find_catalog_match(self, sample):
        if sample is None:
            return None, None, None
        for cat_name, entry in self.catalog.items():
            if type(sample).__name__ in entry["models"]:
                return cat_name, type(sample).__name__, entry["category_class"]
        return None, None, None

    def _select_initial_model(self):
        self._refresh_status()
        if not self.catalog:
            return
        current = VirtualInstrument.sample
        def_cat, def_model, def_cat_cls = self._find_catalog_match(self._default_sample)
        cur_cat, cur_model, _ = self._find_catalog_match(current)

        selected_cat = next(iter(self.catalog))
        selected_model = None
        if cur_cat is not None and (def_cat_cls is None or isinstance(current, def_cat_cls)):
            selected_cat, selected_model = cur_cat, cur_model
        elif def_cat is not None:
            selected_cat, selected_model = def_cat, def_model

        self.category_var.set(selected_cat)
        self._on_category_changed()
        if selected_model is not None:
            self.model_var.set(selected_model)
            self._on_model_changed()

    def _on_category_changed(self, _event=None):
        cat_entry = self.catalog.get(self.category_var.get())
        if not cat_entry:
            return
        model_names = list(cat_entry["models"].keys())
        self.model_combo["values"] = model_names
        if model_names:
            self.model_var.set(model_names[0])
            self._on_model_changed()

    def _selected_model_class(self):
        cat_entry = self.catalog.get(self.category_var.get())
        if not cat_entry:
            return None
        return cat_entry["models"].get(self.model_var.get())

    def _on_model_changed(self, _event=None, *, use_defaults=False):
        model_cls = self._selected_model_class()
        if model_cls is None:
            return
        if not use_defaults and isinstance(VirtualInstrument.sample, model_cls):
            current = VirtualInstrument.sample
        elif isinstance(self._default_sample, model_cls):
            current = self._default_sample
        else:
            current = None
        self.name_var.set(
            getattr(current, "name", "") or ""
            if current is not None
            else ""
        )
        for child in self.params_frame.winfo_children():
            child.destroy()
        self.param_vars = {}
        self.params_frame.columnconfigure(1, weight=1)

        params = get_model_parameters(model_cls, current_sample=current)
        for row, (key, value) in enumerate(params.items()):
            ttk.Label(self.params_frame, text=f"{key}:").grid(row=row, column=0, sticky="w", padx=4, pady=3)
            var = tk.StringVar(value=str(value))
            ttk.Entry(self.params_frame, textvariable=var).grid(row=row, column=1, sticky="ew", padx=4, pady=3)
            self.param_vars[key] = var

    def apply_sample(self):
        """Instantiate the chosen model with current GUI inputs and set as global sample."""
        model_cls = self._selected_model_class()
        if model_cls is None:
            return None
        raw_params = {k: v.get() for k, v in self.param_vars.items()}
        try:
            sample = create_sample_from_parameters(
                model_cls,
                raw_params,
                name=self.name_var.get().strip() or None,
                set_global=True,
            )
        except Exception as exc:
            messagebox.showerror("Invalid Sample Parameters", str(exc), parent=self.window)
            return None
        self._refresh_status()
        return sample

    def reset_defaults(self):
        """Reload default parameter values for the currently selected model."""
        self._on_model_changed(use_defaults=True)

    def _refresh_status(self):
        sample = VirtualInstrument.sample
        if sample is None:
            self.status_var.set("Active Global Sample: None (experiment defaults will be used)")
        else:
            label = f"{type(sample).__name__}"
            if getattr(sample, "name", None):
                label += f" ({sample.name})"
            self.status_var.set(f"Active Global Sample: {label}")

    def mainloop(self):
        """Run the event loop when opened standalone."""
        if self._owns_root:
            self.window.mainloop()


if __name__ == "__main__":
    SimulationHubWindow().mainloop()