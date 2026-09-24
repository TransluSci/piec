"""
Dynamic virtual driver verification test suite.

Validates all PIEC virtual instrument drivers against core architectural contracts:
1. Asserts that every virtual driver inherits from VirtualInstrument, Instrument,
   and its Category Base Class with _is_virtual_driver = True.
2. Asserts all non-optional methods defined on the category base class are implemented
   with simulated logic (no blank stubs).
3. Asserts category-level autodetect (autodetect('virtual_<category>')) and model-level
   virtual dispatch (ModelClass('VIRTUAL')).
"""

from __future__ import annotations

import ast
import dis
import inspect
import textwrap
from typing import Dict, List, Type

import pytest

from piec.drivers.autodetect import autodetect
from piec.drivers.instrument import Instrument
from piec.drivers.virtual_instrument import VirtualInstrument
from tests.driver.driver_discovery import (
    discover_driver_classes,
    discover_instrument_categories,
)



# ============================================================================
# Helpers: Virtual Driver Discovery & Stub Detection
# ============================================================================

def is_virtual_driver_class(cls: Type[Instrument]) -> bool:
    """Return True if cls is a virtual driver (subclass of VirtualInstrument)."""
    return issubclass(cls, VirtualInstrument) or cls.__name__.startswith("Virtual")


def discover_virtual_driver_classes() -> Dict[str, List[Type[Instrument]]]:
    """Discover all virtual drivers grouped by category."""
    all_drivers = discover_driver_classes()
    virtual_drivers: Dict[str, List[Type[Instrument]]] = {}
    for cat_name, driver_list in all_drivers.items():
        virt_list = [d for d in driver_list if is_virtual_driver_class(d)]
        if virt_list:
            virtual_drivers[cat_name] = virt_list
    return virtual_drivers


def _all_virtual_driver_classes() -> List[Type[Instrument]]:
    """Flattened list of all discovered virtual driver classes."""
    classes = []
    for cat_name, drvs in sorted(discover_virtual_driver_classes().items()):
        for drv in drvs:
            classes.append(pytest.param(drv, id=drv.__name__))
    return classes


def is_default_instrument_idn(fn) -> bool:
    """Check if fn is the un-overridden placeholder idn() from Instrument."""
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__
    instrument_idn = Instrument.idn
    while hasattr(instrument_idn, "__wrapped__"):
        instrument_idn = instrument_idn.__wrapped__
    return getattr(fn, "__code__", None) is getattr(instrument_idn, "__code__", None)


def is_blank_stub(fn) -> bool:
    """
    Check if a function contains only docstrings, pass, or ellipsis (no real logic).

    Uses AST inspection with bytecode fallback.
    """
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__

    if is_default_instrument_idn(fn):
        return True

    # 1. AST Inspection
    try:
        src = inspect.getsource(fn)
        tree = ast.parse(textwrap.dedent(src))
        func_node = None
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                func_node = node
                break
        if func_node is not None:
            real_stmts = []
            for stmt in func_node.body:
                if isinstance(stmt, ast.Expr):
                    val = stmt.value
                    if isinstance(val, ast.Constant) and (isinstance(val.value, str) or val.value is ...):
                        continue
                elif isinstance(stmt, ast.Pass):
                    continue
                real_stmts.append(stmt)
            return len(real_stmts) == 0
    except Exception:
        pass

    # 2. Bytecode Disassembly Fallback
    try:
        opnames = [instr.opname for instr in dis.get_instructions(fn)]
        return opnames in (
            ["RESUME", "RETURN_CONST"],
            ["RESUME", "LOAD_CONST", "RETURN_VALUE"],
        )
    except Exception:
        return False


# ============================================================================
# Test Suite: 1. Virtual Driver Hierarchy & Inheritance
# ============================================================================

class TestVirtualDriverHierarchy:
    """Verifies that all virtual drivers inherit from VirtualInstrument and Category."""

    @pytest.mark.parametrize("category_name", sorted(discover_instrument_categories().keys()))
    def test_virtual_driver_bases(self, category_name):
        """
        Each virtual driver must inherit from VirtualInstrument, Instrument,
        and its Category Base Class.
        """
        categories = discover_instrument_categories()
        cat_cls = categories[category_name]
        virt_drivers = discover_virtual_driver_classes().get(category_name, [])

        assert virt_drivers, f"No virtual drivers found in category {category_name}"
        for virt_cls in virt_drivers:
            assert issubclass(virt_cls, VirtualInstrument), (
                f"{virt_cls.__name__} must inherit from VirtualInstrument"
            )
            assert issubclass(virt_cls, cat_cls), (
                f"{virt_cls.__name__} must inherit from category {cat_cls.__name__}"
            )
            assert issubclass(virt_cls, Instrument), (
                f"{virt_cls.__name__} must inherit from Instrument"
            )
            assert getattr(virt_cls, "_is_virtual_driver", False) is True, (
                f"{virt_cls.__name__} must set _is_virtual_driver = True"
            )


# ============================================================================
# Test Suite: 2. Method Implementation (Blank Stub Detection)
# ============================================================================

class TestVirtualDriverMethodImplementation:
    """Verifies that virtual drivers provide simulated implementations."""

    @pytest.mark.parametrize("driver_cls", _all_virtual_driver_classes())
    def test_virtual_driver_non_optional_methods_implemented(self, driver_cls):
        """
        Assert that every virtual driver implements all non-optional methods
        defined by its category base class (i.e. does not inherit blank stubs).
        """
        categories = discover_instrument_categories()
        cat_cls = None
        for c_cls in categories.values():
            if issubclass(driver_cls, c_cls):
                cat_cls = c_cls
                break

        assert cat_cls is not None, f"Could not find category base class for {driver_cls.__name__}"

        unimplemented = []
        for method_name, parent_fn in inspect.getmembers(cat_cls, inspect.isfunction):
            if method_name.startswith("_"):
                continue
            if getattr(parent_fn, "_is_optional", False):
                continue
            if not is_blank_stub(parent_fn):
                continue

            method = getattr(driver_cls, method_name, None)
            if method is None or is_blank_stub(method):
                unimplemented.append(method_name)

        assert not unimplemented, (
            f"{driver_cls.__name__} has unimplemented category methods (blank stubs): {unimplemented}"
        )


# ============================================================================
# Test Suite: 3. Autodetect Verification for Virtual Drivers
# ============================================================================

class TestVirtualDriverAutodetect:
    """Verifies category-level autodetect and model-level virtual dispatch."""

    @pytest.mark.parametrize("category_name", sorted(discover_virtual_driver_classes().keys()))
    def test_category_virtual_address_autodetect(self, category_name):
        """
        autodetect('virtual_<category>') and autodetect('VIRTUAL_<CATEGORY>')
        must resolve and return an instance of the category's VirtualInstrument subclass.
        """
        expected_classes = discover_virtual_driver_classes()[category_name]
        expected_cls = expected_classes[0]

        # 1. Lowercase format
        inst_lower = autodetect(f"virtual_{category_name}")
        assert inst_lower is not None, f"autodetect('virtual_{category_name}') returned None"
        assert isinstance(inst_lower, expected_cls), (
            f"autodetect('virtual_{category_name}') returned {type(inst_lower).__name__}, expected {expected_cls.__name__}"
        )
        assert isinstance(inst_lower, VirtualInstrument)

        # 2. Uppercase format
        inst_upper = autodetect(f"VIRTUAL_{category_name.upper()}")
        assert inst_upper is not None, f"autodetect('VIRTUAL_{category_name.upper()}') returned None"
        assert isinstance(inst_upper, expected_cls)
        assert isinstance(inst_upper, VirtualInstrument)

    def test_model_virtual_dispatch_mock_instrument(self):
        """
        Calling ModelClass('VIRTUAL') on a concrete model returns a profiled virtual driver that:
        1. Subclasses VirtualInstrument and the category's Virtual driver.
        2. Sets is_profiled_virtual_driver = True and emulated_driver_class = model_cls.
        3. Preserves model-specific capabilities (e.g. channel).
        """
        categories = discover_instrument_categories()
        awg_cat = categories["awg"]

        class MockPhysicalAwg(awg_cat):
            channel = [1, 2, 3]

        MockPhysicalAwg.__module__ = "piec.drivers.awg.mock_physical_awg"

        inst = MockPhysicalAwg("VIRTUAL")
        assert isinstance(inst, VirtualInstrument), (
            f"{MockPhysicalAwg.__name__}('VIRTUAL') did not produce a VirtualInstrument"
        )
        assert inst.is_profiled_virtual_driver is True
        assert inst.emulated_driver_class is MockPhysicalAwg
        assert inst.channel == [1, 2, 3], (
            f"Mock instrument channel ({inst.channel}) did not match model capabilities [1, 2, 3]"
        )
