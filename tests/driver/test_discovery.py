"""
Tests for instrument category discovery, dynamic driver registration,
and autodetect discovery capabilities.
"""

from __future__ import annotations

import pytest

import piec.drivers.autodetect as autodetect_module
from piec.drivers.autodetect import autodetect
from tests.driver.driver_discovery import (
    discover_driver_classes,
    discover_instrument_categories,
)


@pytest.mark.parametrize("module_name", [
    "piec.drivers.awg.awg", "piec.drivers.awg.review_new_driver",
    "piec.drivers.emulators.review_new_adapter",
])
def test_discovery_reports_import_failure(monkeypatch, module_name):
    """Ensure broken or missing driver modules report clear import errors during discovery."""
    from pathlib import Path
    from tests.driver import driver_discovery as discovery
    original_import = discovery.importlib.import_module
    original_glob = Path.glob
    failure = ImportError("missing dependency in a new implementation")
    parent, stem = module_name.rsplit(".", 1)
    directory = discovery.DRIVERS_PATH / parent.rsplit(".", 1)[1]

    def with_new_module(path, pattern, **kwargs):
        entries = list(original_glob(path, pattern, **kwargs))
        if path == directory and pattern == "*.py" and stem.startswith("review_"):
            entries.append(path / (stem + ".py"))
        return iter(entries)

    def import_module(name, *args, **kwargs):
        if name == module_name:
            raise failure
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(Path, "glob", with_new_module)
    monkeypatch.setattr(discovery.importlib, "import_module", import_module)
    discover = discovery.discover_driver_classes
    with pytest.raises(AssertionError, match=module_name) as error:
        discover()
    assert error.value.__cause__ is failure


def test_discover_instrument_categories_finds_all_categories():
    """Verify that all core instrument category base classes are discoverable."""
    categories = discover_instrument_categories()
    assert len(categories) >= 8, f"Expected at least 8 instrument categories, found {len(categories)}"
    expected_categories = {"awg", "daq", "dc_calibrator", "dmm", "lockin", "oscilloscope", "pulser", "sourcemeter", "stepper_motor"}
    assert expected_categories.issubset(set(categories.keys())), (
        f"Missing expected categories: {expected_categories - set(categories.keys())}"
    )


def test_discover_driver_classes_finds_registered_drivers():
    """Verify that driver discovery scans and populates classes across categories."""
    driver_map = discover_driver_classes()
    assert len(driver_map) >= 8, f"Expected driver classes in at least 8 categories, found {len(driver_map)}"
    total_drivers = sum(len(drivers) for drivers in driver_map.values())
    assert total_drivers >= 10, f"Expected at least 10 discovered drivers, found {total_drivers}"


def test_dynamic_driver_scan_populates_autodetect_registry():
    """Verify that autodetect's dynamic scan successfully registers drivers under their AUTODETECT_ID."""
    from piec.drivers.autodetect import _dynamic_driver_scan

    registry = _dynamic_driver_scan()
    assert isinstance(registry, dict)
    assert len(registry) > 0, "Expected non-empty autodetect registry"
    # Verify key driver IDs are registered
    assert "33220A" in registry, "Expected Agilent 33220A to be registered in autodetect"
    assert "335" in registry, "Expected Agilent 33500 to be registered in autodetect"
