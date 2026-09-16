"""
Tests for driver MRO inheritance, instrument category discovery,
and virtual driver discovery/autodetect.

Consolidates:
- tests/test_driver_mro.py
- tests/test_virtual_discovery.py
- virtual autodetect tests from tests/test_autodetect.py
"""

from __future__ import annotations

import inspect
import pytest

import piec.drivers.autodetect as autodetect_module
from piec.drivers.autodetect import autodetect
from piec.drivers.awg.virtual_awg import VirtualAwg
from piec.drivers.instrument import Instrument
from piec.drivers.oscilloscope.virtual_oscilloscope import VirtualScope
from piec.drivers.virtual_dispatch import (
    VirtualDriverAmbiguityError,
    VirtualDriverDispatchError,
    _find_virtual_driver_class_by_category,
    find_virtual_driver_class,
)
from piec.drivers.virtual_instrument import VirtualInstrument
from tests.support.discovery import (
    discover_driver_classes,
    discover_instrument_categories,
)


@pytest.mark.parametrize("module_name", [
    "piec.drivers.awg.awg", "piec.drivers.awg.review_new_driver",
    "piec.drivers.emulators.review_new_adapter",
])
def test_discovery_reports_import_failure(monkeypatch, module_name):
    from pathlib import Path
    from tests.support import discovery
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


# ============================================================================
# 1. Driver MRO and Inheritance Contract Tests
# ============================================================================

@pytest.mark.parametrize("category", sorted(discover_instrument_categories()))
def test_new_driver_discovered_and_checked_without_registration(monkeypatch, category):
    """A new module gets declaration checks before its behavior fixture exists."""
    from pathlib import Path
    from types import ModuleType
    from tests.support import discovery
    from tests.support.driver_contracts import assert_driver_contract, case_for

    base = discover_instrument_categories()[category]
    module_name = f"piec.drivers.{category}.review_new_driver"
    module = ModuleType(module_name)
    cls = type("NewDriver", (base,), {
        "__module__": module_name, "channel": [1, 2, 3, 4, 5, 6],
    })
    module.NewDriver = cls
    original_glob = Path.glob
    original_import = discovery.importlib.import_module

    def with_new_module(path, pattern, **kwargs):
        entries = list(original_glob(path, pattern, **kwargs))
        if path == discovery.DRIVERS_PATH / category and pattern == "*.py":
            entries.append(path / "review_new_driver.py")
        return iter(entries)

    def with_new_import(name, *args, **kwargs):
        return module if name == module_name else original_import(name, *args, **kwargs)

    monkeypatch.setattr(Path, "glob", with_new_module)
    monkeypatch.setattr(discovery.importlib, "import_module", with_new_import)
    assert cls in discover_driver_classes()[category]
    assert_driver_contract(cls, base)
    with pytest.raises(AssertionError, match="independent behavioral fixture"):
        case_for(cls, [])
    cls.channel = [2, "one"]
    with pytest.raises(AssertionError, match="integer channel identifiers"):
        assert_driver_contract(cls, base)


@pytest.mark.parametrize("channels", [[], [True], [1.5], [1, 1], [0], [-1], "12", [2, 3, 4, 5], None])
def test_invalid_channel_declarations(channels):
    from piec.drivers.awg.awg import Awg
    from tests.support.driver_contracts import assert_driver_contract

    cls = type("InvalidAwg", (Awg,), {"channel": channels})
    with pytest.raises(AssertionError, match="channel"):
        assert_driver_contract(cls, Awg)


@pytest.mark.parametrize("required,value", [
    (["SIN", "SQU"], ["SIN"]),
    ({"mode": ["SIN"]}, {}),
    ({"mode": ["SIN"]}, {"mode": None}),
    ((0, 100), (None, 100)),
    (False, None),
])
def test_non_none_parent_attributes_are_required(required, value):
    from tests.support.driver_contracts import assert_driver_contract

    parent = type("Parent", (), {"capability": required})
    child = type("Child", (parent,), {"capability": value})
    with pytest.raises(AssertionError, match="capability"):
        assert_driver_contract(child, parent)


def test_parent_requirements_allow_extensions_inheritance_and_optional_values():
    from tests.support.driver_contracts import assert_driver_contract

    parent = type("Parent", (), {"channel": [1], "modes": ["A"], "optional": None})
    child = type("Child", (parent,), {"channel": [1, 2, 3, 4, 5, 6], "modes": ["A", "B"]})
    assert_driver_contract(child, parent)
    assert_driver_contract(type("Inherited", (parent,), {}), parent)


def test_instance_channel_override_is_checked():
    from piec.drivers.awg.awg import Awg
    from tests.support.driver_contracts import assert_driver_contract

    instrument = VirtualAwg()
    assert_driver_contract(instrument, Awg)
    instrument.channel = [2, "one"]
    with pytest.raises(AssertionError, match="integer channel identifiers"):
        assert_driver_contract(instrument, Awg)


class TestDriverMRO:
    """Verifies that all discovered drivers conform to the driver inheritance hierarchy."""

    def test_discovered_categories_inherit_from_instrument(self):
        categories = discover_instrument_categories()
        assert len(categories) >= 8
        for cat_name, cat_cls in categories.items():
            assert issubclass(cat_cls, Instrument), f"Category {cat_name} must inherit from Instrument"

    def test_all_discovered_drivers_inherit_from_category_and_instrument(self):
        categories = discover_instrument_categories()
        driver_map = discover_driver_classes()

        total_drivers = 0
        for cat_name, driver_classes in driver_map.items():
            cat_cls = categories[cat_name]
            for driver_cls in driver_classes:
                total_drivers += 1
                assert issubclass(driver_cls, cat_cls), (
                    f"Driver {driver_cls.__name__} must inherit from category {cat_cls.__name__}"
                )
                assert issubclass(driver_cls, Instrument), (
                    f"Driver {driver_cls.__name__} must inherit from Instrument"
                )

                if driver_cls.__name__.startswith("Virtual"):
                    assert issubclass(driver_cls, VirtualInstrument), (
                        f"Virtual driver {driver_cls.__name__} must inherit from VirtualInstrument"
                    )

        assert total_drivers >= 15, f"Expected at least 15 drivers discovered, found {total_drivers}"


# ============================================================================
# 2. Virtual Driver Discovery Helper Tests
# ============================================================================

class TestVirtualDriverDiscovery:
    """Tests for find_virtual_driver_class and category alias resolution."""

    def test_shared_discovery_finds_virtual_driver_by_category(self):
        assert find_virtual_driver_class("awg") is VirtualAwg
        assert find_virtual_driver_class("oscilloscope") is VirtualScope

    def test_shared_discovery_applies_category_aliases(self):
        assert find_virtual_driver_class("scope") is VirtualScope

    def test_shared_discovery_caches_by_canonical_category(self):
        _find_virtual_driver_class_by_category.cache_clear()

        assert find_virtual_driver_class("scope") is VirtualScope
        assert find_virtual_driver_class("oscilloscope") is VirtualScope

        cache_info = _find_virtual_driver_class_by_category.cache_info()
        assert cache_info.misses == 1
        assert cache_info.hits == 1

    def test_shared_discovery_returns_none_for_unknown_category(self):
        assert find_virtual_driver_class("not_a_real_category") is None

    def test_autodetect_uses_shared_discovery_function(self):
        assert autodetect_module._find_virtual_driver_class is find_virtual_driver_class
        assert autodetect_module.VirtualDriverAmbiguityError is VirtualDriverAmbiguityError

    def test_ambiguity_error_exposes_category_and_candidates(self):
        error = VirtualDriverAmbiguityError("instrument", [VirtualAwg, VirtualScope])

        assert isinstance(error, VirtualDriverDispatchError)
        assert error.category == "instrument"
        assert error.candidates == (VirtualAwg, VirtualScope)
        assert "VirtualAwg" in str(error)
        assert "VirtualScope" in str(error)


# ============================================================================
# 3. Virtual Autodetect Behavior Tests
# ============================================================================

class TestVirtualAutodetect:
    """Tests for autodetect('virtual_<category>')."""

    @pytest.mark.parametrize(
        ("category_request", "expected_class"),
        [
            ("virtual_scope", VirtualScope),
            ("VIRTUAL_SCOPE", VirtualScope),
            ("virtual_oscilloscope", VirtualScope),
            ("virtual_awg", VirtualAwg),
        ],
    )
    def test_virtual_category_selects_virtual_driver(self, category_request, expected_class):
        instrument = autodetect(category_request)
        assert isinstance(instrument, expected_class)
        assert instrument.instrument is instrument

    def test_virtual_autodetect_forwards_constructor_options(self):
        scope = autodetect("virtual_scope", check_params=True)
        assert isinstance(scope, VirtualScope)
        assert scope.check_params is True

    def test_unknown_virtual_category_returns_none(self):
        assert autodetect("virtual_not_a_real_category") is None
