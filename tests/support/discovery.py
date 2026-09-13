"""
Discovery utilities for instrument drivers, adapters, and measurement classes.
"""

from __future__ import annotations

import importlib
import inspect
from pathlib import Path
from typing import Dict, List, Set, Type

import piec.drivers as drivers_package
import piec.measurement as measurement_package
from piec.drivers.instrument import Instrument
from piec.measurement.base import BaseMeasurement

DRIVERS_PATH = Path(drivers_package.__file__).resolve().parent
MEASUREMENT_PATH = Path(measurement_package.__file__).resolve().parent

EXCLUDED_CATEGORY_NAMES = {
    "__pycache__",
    "emulators",
    "example",
    "old",
    "tests",
    "z_old",
}
EXCLUDED_MODULE_SUFFIXES = ("_old",)


def _import_module(name):
    try:
        return importlib.import_module(name)
    except Exception as error:
        raise AssertionError(f"Could not import production module {name!r}") from error


def local_subclasses_in_module(module, base_class):
    """Return subclasses of base_class defined in, rather than imported by, a module."""
    classes = []
    for exported_name, class_object in inspect.getmembers(module, inspect.isclass):
        if class_object is base_class:
            continue
        if class_object.__module__ != module.__name__:
            continue
        if exported_name != class_object.__name__:
            continue
        if issubclass(class_object, base_class):
            classes.append(class_object)
    return classes


def discover_instrument_categories() -> Dict[str, Type[Instrument]]:
    """Discover all category base classes (e.g. Awg, Oscilloscope, DMM)."""
    categories = {}
    for category_path in sorted(DRIVERS_PATH.iterdir()):
        if not category_path.is_dir():
            continue
        category_name = category_path.name
        if category_name in EXCLUDED_CATEGORY_NAMES or category_name.startswith("_"):
            continue

        interface_path = category_path / f"{category_name}.py"
        if not interface_path.is_file():
            continue

        mod = _import_module(f"piec.drivers.{category_name}.{category_name}")

        category_classes = local_subclasses_in_module(mod, Instrument)
        assert len(category_classes) == 1, (
            f"{mod.__name__} must define exactly one instrument category; found {category_classes}"
        )
        categories[category_name] = category_classes[0]
    assert categories, f"No instrument categories discovered in {DRIVERS_PATH}"
    return categories


def discover_driver_classes() -> Dict[str, List[Type[Instrument]]]:
    """Discover all concrete model drivers and virtual drivers grouped by category."""
    categories = discover_instrument_categories()
    discovered: Dict[str, List[Type[Instrument]]] = {cat: [] for cat in categories}

    for category_name, category_class in categories.items():
        category_path = DRIVERS_PATH / category_name
        for module_path in sorted(category_path.glob("*.py")):
            stem = module_path.stem
            if stem in {"__init__", category_name} or stem.startswith("_") or stem.endswith(EXCLUDED_MODULE_SUFFIXES):
                continue
            mod = _import_module(f"piec.drivers.{category_name}.{stem}")
            for driver_class in local_subclasses_in_module(mod, Instrument):
                assert issubclass(driver_class, category_class), (
                    f"{mod.__name__}.{driver_class.__name__} must inherit {category_class.__name__}"
                )
                if driver_class not in discovered[category_name]:
                    discovered[category_name].append(driver_class)

    # Discover adapters from emulators
    emulators_path = DRIVERS_PATH / "emulators"
    if emulators_path.is_dir():
        for module_path in sorted(emulators_path.glob("*.py")):
            stem = module_path.stem
            if stem.startswith("_"):
                continue
            mod = _import_module(f"piec.drivers.emulators.{stem}")
            for name, cls_obj in inspect.getmembers(mod, inspect.isclass):
                if cls_obj.__module__ == mod.__name__ and issubclass(cls_obj, Instrument):
                    for cat_name, cat_class in categories.items():
                        if issubclass(cls_obj, cat_class) and cls_obj not in discovered[cat_name]:
                            discovered[cat_name].append(cls_obj)

    return discovered


def discover_measurement_classes() -> Dict[str, Type[BaseMeasurement]]:
    """Discover all concrete BaseMeasurement subclasses exported or defined in piec.measurement."""
    measurements = {}

    # Check what is exported from top-level package
    for name, obj in inspect.getmembers(measurement_package, inspect.isclass):
        if issubclass(obj, BaseMeasurement) and obj is not BaseMeasurement:
            if not inspect.isabstract(obj):
                measurements[obj.__name__] = obj

    # Also scan modules under measurement package
    for module_path in sorted(MEASUREMENT_PATH.glob("*.py")):
        stem = module_path.stem
        if stem.startswith("__"):
            continue
        mod = _import_module(f"piec.measurement.{stem}")
        for name, obj in inspect.getmembers(mod, inspect.isclass):
            if issubclass(obj, BaseMeasurement) and obj is not BaseMeasurement:
                if not inspect.isabstract(obj):
                    measurements[obj.__name__] = obj

    return measurements


def assert_all_drivers_registered(category_name: str, registered_classes: Set[Type[Instrument]]) -> None:
    """Enforce that every discovered driver subclass in category_name is present in registered_classes."""
    all_discovered = discover_driver_classes()
    if category_name not in all_discovered:
        raise AssertionError(f"Unknown instrument category: {category_name!r}")

    discovered_in_cat = set(all_discovered[category_name])
    missing = discovered_in_cat - set(registered_classes)
    if missing:
        missing_names = sorted(cls.__name__ for cls in missing)
        raise AssertionError(
            f"Missing test fixture for discovered driver subclass(es) in category {category_name!r}: "
            f"{missing_names}. Every driver subclass must have runtime test coverage."
        )


def assert_all_measurements_registered(registered_classes: Set[Type[BaseMeasurement]]) -> None:
    """Enforce that every discovered concrete BaseMeasurement subclass is present in registered_classes."""
    discovered = discover_measurement_classes()
    discovered_classes = set(discovered.values())
    missing = discovered_classes - set(registered_classes)
    if missing:
        missing_names = sorted(cls.__name__ for cls in missing)
        raise AssertionError(
            f"Missing test fixture for discovered measurement subclass(es): {missing_names}. "
            "Every measurement subclass must have runtime test coverage."
        )
