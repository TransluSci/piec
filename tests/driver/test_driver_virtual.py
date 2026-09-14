"""
Dynamic virtual driver verification test suite.

Validates all PIEC virtual instrument drivers against the core architectural contracts:
1. Asserts that every virtual driver inherits from both VirtualInstrument and its
   Category Base Class (e.g. VirtualAwg inherits (VirtualInstrument, Awg)).
2. Asserts class attribute conformance: any non-None class attribute of the parent
   category is present in the virtual driver, has matching schema/type, and contains
   at least the parent's values (1:1 capability parity with physical drivers).
3. Asserts all non-optional functions are implemented with simulated logic rather than
   inheriting empty/blank stubs from the category parent.
4. Asserts that virtual drivers provide simulated implementations of the universal
   lifecycle commands (reset, clear, idn, error, wait, self_test, operation_complete).
"""

from __future__ import annotations

import ast
import dis
import inspect
from numbers import Real
from pathlib import Path
import textwrap
from typing import Any, Dict, List, Set, Tuple, Type

import pytest

import piec.drivers as drivers_pkg
from piec.drivers.autodetect import autodetect
from piec.drivers.instrument import Instrument, get_class_attributes_from_instance, optional
from piec.drivers.scpi import Scpi
from piec.drivers.virtual_instrument import VirtualInstrument
from tests.driver.test_driver_physical import discover_physical_driver_classes
from tests.support.discovery import (
    DRIVERS_PATH,
    EXCLUDED_CATEGORY_NAMES,
    EXCLUDED_MODULE_SUFFIXES,
    discover_driver_classes,
    discover_instrument_categories,
    local_subclasses_in_module,
)
from tests.support.driver_contracts import assert_capability



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


def assert_class_attributes_conformance(child_cls: Type[Instrument], parent_cls: type) -> None:
    """
    Assert that any class attribute of parent_cls that is defined (not None)
    is also present in child_cls, has matching schema/type, and contains
    at least what the parent specifies (superset containment).
    """
    for name, parent_val in vars(parent_cls).items():
        if name.startswith("_") or callable(parent_val):
            continue
        if parent_val is None:
            continue

        child_val = inspect.getattr_static(child_cls, name, None)
        label = f"{child_cls.__name__}.{name}"

        assert child_val is not None, (
            f"{label} is defined on parent {parent_cls.__name__} as {parent_val!r} "
            f"and cannot be missing or None in {child_cls.__name__}"
        )

        # Open capability schema (None, None)
        if parent_val == (None, None):
            assert_capability(child_val, label)
            continue

        # Type checks and value supersets
        if isinstance(parent_val, tuple):
            assert isinstance(child_val, tuple), (
                f"{label} must be a tuple matching parent {parent_cls.__name__} type {type(parent_val).__name__}"
            )
            assert len(child_val) == len(parent_val), (
                f"{label} tuple length ({len(child_val)}) must match parent length ({len(parent_val)})"
            )
        elif isinstance(parent_val, list):
            assert isinstance(child_val, (list, tuple)), (
                f"{label} must be a list or tuple matching parent {parent_cls.__name__}"
            )
            missing = []
            for item in parent_val:
                if isinstance(item, tuple) and item == (None, None):
                    continue
                if item not in child_val:
                    missing.append(item)
            assert not missing, (
                f"{label} is missing parent-required values {missing!r} from {parent_cls.__name__}. "
                f"Child has: {child_val!r}"
            )
        elif isinstance(parent_val, dict):
            assert isinstance(child_val, dict), (
                f"{label} must be a dict matching parent {parent_cls.__name__}"
            )
            missing_keys = [k for k in parent_val if k not in child_val]
            assert not missing_keys, (
                f"{label} is missing parent-required keys {missing_keys!r} from {parent_cls.__name__}"
            )
        elif isinstance(parent_val, Real) and not isinstance(parent_val, bool):
            assert isinstance(child_val, Real) and not isinstance(child_val, bool), (
                f"{label} must be numeric matching parent {parent_cls.__name__}"
            )
        else:
            assert isinstance(child_val, type(parent_val)), (
                f"{label} type ({type(child_val).__name__}) must match parent type ({type(parent_val).__name__})"
            )


# ============================================================================
# Test Suite: 1. Virtual Driver Hierarchy & Inheritance
# ============================================================================

class TestVirtualDriverHierarchy:
    """Verifies that all virtual drivers inherit from VirtualInstrument and Category."""

    def test_all_categories_have_virtual_driver(self):
        """Every instrument category must define a virtual driver."""
        categories = discover_instrument_categories()
        virtual_drivers = discover_virtual_driver_classes()

        assert len(virtual_drivers) >= 8, (
            f"Expected at least 8 categories with virtual drivers, found {len(virtual_drivers)}"
        )
        for cat_name, cat_cls in categories.items():
            assert cat_name in virtual_drivers, (
                f"Category {cat_name} is missing a Virtual driver"
            )

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
            # Must have _is_virtual_driver flag
            assert getattr(virt_cls, "_is_virtual_driver", False) is True, (
                f"{virt_cls.__name__} must set _is_virtual_driver = True"
            )


# ============================================================================
# Test Suite: 2. Class Attribute Conformance
# ============================================================================

class TestVirtualDriverClassAttributes:
    """Verifies that virtual drivers conform to category class attributes."""

    @pytest.mark.parametrize("category_name", sorted(discover_instrument_categories().keys()))
    def test_virtual_driver_attribute_conformance(self, category_name):
        """
        Dynamically test all virtual drivers in a category: every non-None class attribute
        on the parent class must be defined, preserve type, and contain parent elements.
        """
        categories = discover_instrument_categories()
        category_cls = categories[category_name]
        virt_drivers = discover_virtual_driver_classes().get(category_name, [])

        for virt_cls in virt_drivers:
            for base in virt_cls.__mro__:
                if base in (object, Instrument, VirtualInstrument):
                    continue
                assert_class_attributes_conformance(virt_cls, base)


# ============================================================================
# Test Suite: 3. Method Implementation (Blank Stub Detection)
# ============================================================================

class TestVirtualDriverMethodImplementation:
    """Verifies that virtual drivers provide simulated implementations."""

    @pytest.mark.parametrize("category_name", sorted(discover_instrument_categories().keys()))
    def test_virtual_drivers_implement_idn(self, category_name):
        """Every virtual driver must implement idn()."""
        virt_drivers = discover_virtual_driver_classes().get(category_name, [])
        for virt_cls in virt_drivers:
            idn_method = getattr(virt_cls, "idn", None)
            assert idn_method is not None, f"{virt_cls.__name__} has no idn method"
            assert not is_default_instrument_idn(idn_method), (
                f"{virt_cls.__name__}.idn is still the default un-overridden Instrument.idn"
            )
            assert not is_blank_stub(idn_method), (
                f"{virt_cls.__name__}.idn resolves to a blank stub"
            )


# ============================================================================
# Parameterized Non-Optional Method Tests Across All Discovered Virtual Drivers
# ============================================================================

def _build_virtual_driver_method_cases():
    """Build parameterized test cases for all virtual drivers and category methods."""
    categories = discover_instrument_categories()
    virtual_drivers = discover_virtual_driver_classes()
    cases = []

    for category_name, drivers in virtual_drivers.items():
        cat_cls = categories[category_name]

        for method_name, parent_fn in inspect.getmembers(cat_cls, inspect.isfunction):
            if method_name.startswith("_"):
                continue
            if getattr(parent_fn, "_is_optional", False):
                continue
            if not is_blank_stub(parent_fn):
                continue

            for driver_cls in drivers:
                test_id = f"{driver_cls.__name__}-{method_name}"
                cases.append(pytest.param(driver_cls, method_name, id=test_id))
    return cases


@pytest.mark.parametrize("driver_cls,method_name", _build_virtual_driver_method_cases())
def test_virtual_driver_non_optional_methods_implemented(driver_cls, method_name):
    """
    Assert that every virtual driver implements all non-optional methods
    defined by its category base class (i.e. does not inherit blank stubs).
    """
    method = getattr(driver_cls, method_name, None)
    assert method is not None, f"{driver_cls.__name__} is missing method '{method_name}'"
    assert not is_blank_stub(method), (
        f"{driver_cls.__name__}.{method_name} is not implemented in virtual driver (inherits a blank stub)"
    )


# ============================================================================
# Test Suite: 5. Autodetect Verification for Virtual Drivers
# ============================================================================

def _all_virtual_drivers_list() -> List[Type[Instrument]]:
    """Return a flat list of all discovered virtual driver classes."""
    res: List[Type[Instrument]] = []
    for drv_list in discover_virtual_driver_classes().values():
        res.extend(drv_list)
    return sorted(res, key=lambda c: c.__name__)


def _all_physical_models_for_virtual_dispatch():
    """List of all concrete physical driver classes for model virtual dispatch."""
    cases = []
    for cat_name, drv_list in sorted(discover_physical_driver_classes().items()):
        for drv_cls in drv_list:
            cases.append(pytest.param(drv_cls, cat_name, id=drv_cls.__name__))
    return cases


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

    @pytest.mark.parametrize("model_cls,cat_name", _all_physical_models_for_virtual_dispatch())
    def test_model_virtual_dispatch_profiled_driver(self, model_cls, cat_name):
        """
        Calling ModelClass('VIRTUAL') returns a profiled virtual driver that:
        1. Subclasses VirtualInstrument and the category's Virtual driver.
        2. Sets is_profiled_virtual_driver = True and emulated_driver_class = model_cls.
        3. Preserves model-specific capabilities (e.g. channel).
        """
        inst = model_cls("VIRTUAL")
        assert isinstance(inst, VirtualInstrument), (
            f"{model_cls.__name__}('VIRTUAL') did not produce a VirtualInstrument"
        )
        assert inst.is_profiled_virtual_driver is True
        assert inst.emulated_driver_class is model_cls

        # Capability preservation
        if hasattr(model_cls, "channel"):
            assert inst.channel == model_cls.channel, (
                f"{inst} channel ({inst.channel}) did not match {model_cls.__name__}.channel ({model_cls.channel})"
            )


# ============================================================================
# Test Suite: 6. Runtime Parameter Validation Across Virtual Drivers
# ============================================================================

class TestVirtualDriverRuntimeParameterValidation:
    """Verifies check_params=True behavior on virtual drivers."""

    @pytest.mark.parametrize("driver_cls", _all_virtual_drivers_list(), ids=lambda c: c.__name__)
    def test_virtual_driver_direct_parameter_checking(self, driver_cls):
        """
        Directly validates virtual driver class attributes through _check_params:
        - Valid list items pass; invalid items raise ValueError.
        - Valid range midpoints pass; out-of-range values raise ValueError.
        """
        inst = driver_cls(check_params=True)
        assert inst.check_params is True

        for attr_name, attr_val in vars(driver_cls).items():
            if attr_name.startswith("_") or callable(attr_val):
                continue

            # 1. Discrete list attributes
            if isinstance(attr_val, list) and len(attr_val) > 0:
                valid_val = attr_val[0]
                inst._check_params(inst, {attr_name: valid_val})

                invalid_val = 999999 if isinstance(valid_val, (int, float)) else "__PIEC_INVALID_VAL__"
                with pytest.raises(ValueError, match="not in list|out of acceptable"):
                    inst._check_params(inst, {attr_name: invalid_val})

            # 2. Numeric range tuples
            elif isinstance(attr_val, tuple) and len(attr_val) == 2:
                low, high = attr_val
                if (
                    low is not None
                    and high is not None
                    and isinstance(low, Real)
                    and isinstance(high, Real)
                    and not isinstance(low, bool)
                    and not isinstance(high, bool)
                    and low < high
                ):
                    mid = (low + high) / 2.0
                    inst._check_params(inst, {attr_name: mid})

                    bad_high = high + 1000.0 if high >= 0 else high + abs(high) + 1000.0
                    with pytest.raises(ValueError, match="out of acceptable Range|out of range"):
                        inst._check_params(inst, {attr_name: bad_high})

    @pytest.mark.parametrize("driver_cls", _all_virtual_drivers_list(), ids=lambda c: c.__name__)
    def test_virtual_driver_method_parameter_validation(self, driver_cls):
        """
        When check_params=True, calling an implemented virtual method with invalid parameters
        raises ValueError. When check_params=False, parameter validation is bypassed.
        """
        inst_checked = driver_cls(check_params=True)
        class_attrs = get_class_attributes_from_instance(inst_checked)

        target_method_name = None
        target_param_name = None
        invalid_param_val = None

        for m_name, fn in inspect.getmembers(driver_cls, inspect.isfunction):
            if m_name.startswith("_") or getattr(fn, "_is_optional", False):
                continue
            if is_blank_stub(fn):
                continue

            sig = inspect.signature(fn)
            for p_name in sig.parameters:
                if p_name in class_attrs and class_attrs[p_name] is not None:
                    attr_spec = class_attrs[p_name]
                    if isinstance(attr_spec, list) and len(attr_spec) > 0:
                        target_method_name = m_name
                        target_param_name = p_name
                        invalid_param_val = 999999 if isinstance(attr_spec[0], (int, float)) else "__PIEC_INVALID__"
                        break
                    elif isinstance(attr_spec, tuple) and len(attr_spec) == 2:
                        low, high = attr_spec
                        if low is not None and high is not None and isinstance(low, Real) and isinstance(high, Real) and low < high:
                            target_method_name = m_name
                            target_param_name = p_name
                            invalid_param_val = high + 1000.0 if high >= 0 else high + abs(high) + 1000.0
                            break
            if target_method_name is not None:
                break

        if target_method_name is None:
            # Virtual driver has no implemented method accepting checked parameters yet
            return

        fn = getattr(driver_cls, target_method_name)
        sig = inspect.signature(fn)

        bad_kwargs = {}
        for p_name, param in sig.parameters.items():
            if p_name == "self":
                continue
            if p_name == target_param_name:
                bad_kwargs[p_name] = invalid_param_val
            elif param.default is not inspect._empty:
                bad_kwargs[p_name] = param.default
            else:
                bad_kwargs[p_name] = 1

        # 1. With check_params=True: raises ValueError
        with pytest.raises(ValueError):
            getattr(inst_checked, target_method_name)(**bad_kwargs)

        # 2. With check_params=False: validation is bypassed
        inst_unchecked = driver_cls(check_params=False)
        try:
            getattr(inst_unchecked, target_method_name)(**bad_kwargs)
        except ValueError as exc:
            err_text = str(exc)
            assert "out of acceptable" not in err_text and "not in list" not in err_text, (
                f"Unexpected validation error with check_params=False: {exc}"
            )
        except Exception:
            pass

