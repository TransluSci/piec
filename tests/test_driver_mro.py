"""Dynamic regression tests for the driver inheritance contract."""

import importlib
import inspect
from pathlib import Path

import pytest

import piec.drivers as drivers_package
from piec.drivers.instrument import Instrument
from piec.drivers.virtual_instrument import VirtualInstrument


DRIVERS_PATH = Path(drivers_package.__file__).resolve().parent
EXCLUDED_CATEGORY_NAMES = {
    "__pycache__",
    "emulators",
    "example",
    "old",
    "tests",
    "z_old",
}
EXCLUDED_MODULE_SUFFIXES = ("_old",)


def _local_instrument_classes(module):
    """Return Instrument subclasses defined in, rather than imported by, a module."""
    classes = []

    for exported_name, class_object in inspect.getmembers(module, inspect.isclass):
        if class_object is Instrument:
            continue
        if class_object.__module__ != module.__name__:
            continue
        if exported_name != class_object.__name__:
            continue
        if issubclass(class_object, Instrument):
            classes.append(class_object)

    return classes


def _import_driver_module(module_name):
    try:
        return importlib.import_module(module_name)
    except Exception as error:
        raise AssertionError(f"Could not import driver module {module_name!r}") from error


def _discover_driver_cases():
    """Discover model drivers independently from the production autodetect code."""
    cases = []

    for category_path in sorted(DRIVERS_PATH.iterdir()):
        if not category_path.is_dir():
            continue

        category_name = category_path.name
        if category_name in EXCLUDED_CATEGORY_NAMES or category_name.startswith("_"):
            continue

        interface_path = category_path / f"{category_name}.py"
        if not interface_path.is_file():
            continue

        interface_module = _import_driver_module(
            f"piec.drivers.{category_name}.{category_name}"
        )
        category_classes = _local_instrument_classes(interface_module)
        if len(category_classes) != 1:
            names = [class_object.__name__ for class_object in category_classes]
            raise AssertionError(
                f"Category module {interface_module.__name__!r} must define exactly "
                f"one Instrument subclass; found {names}"
            )
        category_class = category_classes[0]

        for module_path in sorted(category_path.glob("*.py")):
            if module_path.stem in {"__init__", category_name}:
                continue
            if module_path.stem.startswith("_"):
                continue
            if module_path.stem.endswith(EXCLUDED_MODULE_SUFFIXES):
                continue

            module = _import_driver_module(
                f"piec.drivers.{category_name}.{module_path.stem}"
            )
            is_virtual_module = module_path.stem.startswith("virtual_")

            for driver_class in _local_instrument_classes(module):
                cases.append((driver_class, category_class, is_virtual_module))

    if not cases:
        raise AssertionError(f"No model drivers were discovered under {DRIVERS_PATH}")

    return cases


def _case_id(case):
    driver_class, _, _ = case
    return f"{driver_class.__module__}.{driver_class.__name__}"


DRIVER_CASES = _discover_driver_cases()
PHYSICAL_DRIVER_CASES = [case for case in DRIVER_CASES if not case[2]]
VIRTUAL_DRIVER_CASES = [case for case in DRIVER_CASES if case[2]]


def test_discovery_excludes_nonproduction_driver_locations():
    discovered_modules = {case[0].__module__ for case in DRIVER_CASES}

    # These directories are committed fixtures, so these assertions ensure the
    # exclusion test cannot pass merely because the directories are absent.
    assert (DRIVERS_PATH / "example").is_dir()
    assert (DRIVERS_PATH / "emulators").is_dir()

    for excluded_name in EXCLUDED_CATEGORY_NAMES:
        module_prefix = f"piec.drivers.{excluded_name}."
        assert all(
            not module_name.startswith(module_prefix)
            for module_name in discovered_modules
        )

    assert all(
        not module_name.rsplit(".", 1)[-1].endswith(EXCLUDED_MODULE_SUFFIXES)
        for module_name in discovered_modules
    )


@pytest.mark.parametrize(
    ("driver_class", "category_class", "is_virtual_module"),
    DRIVER_CASES,
    ids=[_case_id(case) for case in DRIVER_CASES],
)
def test_driver_inherits_from_its_folder_category(
    driver_class,
    category_class,
    is_virtual_module,
):
    assert issubclass(driver_class, category_class)
    assert issubclass(driver_class, VirtualInstrument) is is_virtual_module


@pytest.mark.parametrize(
    ("driver_class", "category_class", "is_virtual_module"),
    PHYSICAL_DRIVER_CASES,
    ids=[_case_id(case) for case in PHYSICAL_DRIVER_CASES],
)
def test_physical_protocol_bases_precede_category_skeleton(
    driver_class,
    category_class,
    is_virtual_module,
):
    mro = driver_class.__mro__
    category_position = mro.index(category_class)

    assert is_virtual_module is False
    assert category_position < mro.index(Instrument)

    protocol_bases = [
        base
        for base in driver_class.__bases__
        if base is not category_class and issubclass(base, Instrument)
    ]
    for protocol_base in protocol_bases:
        assert mro.index(protocol_base) < category_position


@pytest.mark.parametrize(
    ("driver_class", "category_class", "is_virtual_module"),
    VIRTUAL_DRIVER_CASES,
    ids=[_case_id(case) for case in VIRTUAL_DRIVER_CASES],
)
def test_virtual_instrument_precedes_category_in_mro(
    driver_class,
    category_class,
    is_virtual_module,
):
    mro = driver_class.__mro__

    assert is_virtual_module is True
    assert mro.index(VirtualInstrument) < mro.index(category_class)
    assert mro.index(category_class) < mro.index(Instrument)


@pytest.mark.parametrize(
    ("driver_class", "category_class", "is_virtual_module"),
    VIRTUAL_DRIVER_CASES,
    ids=[_case_id(case) for case in VIRTUAL_DRIVER_CASES],
)
def test_virtual_driver_reaches_instrument_initializer_once(
    driver_class,
    category_class,
    is_virtual_module,
    monkeypatch,
):
    original_init = Instrument.__init__
    calls = []

    def counting_init(self, *args, **kwargs):
        calls.append(self)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(Instrument, "__init__", counting_init)

    instrument = driver_class(check_params=True)

    assert calls == [instrument]
    assert instrument.virtual is True
    assert instrument.check_params is True
