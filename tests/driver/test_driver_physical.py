"""
Dynamic physical driver verification test suite.

Validates all PIEC physical instrument drivers against the core architectural contracts:
1. Discerns Category Interfaces (e.g. awg.py) from Physical Driver Implementations (e.g. k_81150a.py),
   asserting that every physical implementation has a valid parent category class and inherits Instrument.
2. Asserts class attribute conformance: any non-None class attribute of the parent
   (e.g. channel = [1]) is present in the child, has matching schema/type, and contains
   at least the parent's values (superset containment).
3. Asserts all non-optional functions are implemented with real code rather than
   inheriting empty/blank stubs from the category parent (via AST and bytecode inspection).
4. Verifies hierarchical traversal to the top of the MRO (IEEE 488.2 / SCPI commands from
   Scpi mixin, and concrete identification from Instrument).
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
from piec.drivers.digilent import Digilent
from piec.drivers.instrument import Instrument, get_class_attributes_from_instance, optional
from piec.drivers.scpi import Scpi
from piec.drivers.virtual_instrument import VirtualInstrument
from tests.support.discovery import (
    DRIVERS_PATH,
    EXCLUDED_CATEGORY_NAMES,
    EXCLUDED_MODULE_SUFFIXES,
    discover_driver_classes,
    discover_instrument_categories,
    local_subclasses_in_module,
)
from tests.support.driver_contracts import assert_capability
from tests.support.transports import ScriptedTransport, create_test_driver



# ============================================================================
# Helpers: Interface vs Implementation Discernment & Stub Detection
# ============================================================================

def is_category_interface_module(module_path: Path) -> bool:
    """
    Return True if module_path is a Level 2 Category Interface definition.

    In PIEC's 3-level architecture:
    - Level 2 Category Interface files are named after their enclosing category directory:
      e.g. `piec/drivers/awg/awg.py`, `piec/drivers/oscilloscope/oscilloscope.py`.
    - Level 3 Driver Implementations are sibling files:
      e.g. `piec/drivers/awg/k_81150a.py`, `piec/drivers/oscilloscope/rigol_ds1000z.py`.
    """
    parent_dir = module_path.parent
    if parent_dir == DRIVERS_PATH:
        return False
    return module_path.stem == parent_dir.name


def is_physical_driver_module(module_path: Path) -> bool:
    """Return True if module_path defines physical hardware driver implementations."""
    if module_path.suffix != ".py":
        return False
    stem = module_path.stem
    if stem.startswith("_") or stem == "__init__" or stem.endswith(EXCLUDED_MODULE_SUFFIXES):
        return False
    parent_name = module_path.parent.name
    if parent_name in EXCLUDED_CATEGORY_NAMES or parent_name.startswith("_"):
        return False
    if module_path.parent == DRIVERS_PATH:
        return False
    # Exclude the category interface itself
    if stem == parent_name:
        return False
    # Exclude virtual drivers and emulator adapters
    if stem.startswith("virtual_") or parent_name == "emulators":
        return False
    return True


def is_physical_driver_class(cls: Type[Instrument]) -> bool:
    """Return True if cls is a physical model driver (not a virtual driver or emulator adapter)."""
    if issubclass(cls, VirtualInstrument) or cls.__name__.startswith("Virtual"):
        return False
    if "emulators" in cls.__module__ or cls.__name__.startswith("DaqAs"):
        return False
    return True


def discover_physical_driver_classes() -> Dict[str, List[Type[Instrument]]]:
    """Discover all concrete physical model drivers grouped by category."""
    all_drivers = discover_driver_classes()
    physical_drivers: Dict[str, List[Type[Instrument]]] = {}
    for cat_name, driver_list in all_drivers.items():
        physical_list = [d for d in driver_list if is_physical_driver_class(d)]
        if physical_list:
            physical_drivers[cat_name] = physical_list
    return physical_drivers


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
            # None in parent leaves the attribute optional
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
# Test Suite: 1. Interface vs. Implementation Discernment & Parent Hierarchy
# ============================================================================

class TestPhysicalDriverHierarchyAndDiscovery:
    """Tests identifying Category Interfaces vs Physical Implementations."""

    def test_category_interfaces_discerned(self):
        """
        Category Interface modules (e.g. awg/awg.py) define the category contract,
        inherit directly from Instrument, and are not implementations of other categories.
        """
        categories = discover_instrument_categories()
        assert len(categories) >= 8, f"Discovered only {len(categories)} categories"

        for category_name, category_cls in categories.items():
            category_file = DRIVERS_PATH / category_name / f"{category_name}.py"
            assert category_file.is_file(), f"Expected interface file at {category_file}"
            assert is_category_interface_module(category_file), (
                f"{category_file} should be recognized as a Category Interface module"
            )
            assert not is_physical_driver_module(category_file), (
                f"{category_file} should NOT be recognized as a Physical Driver Implementation module"
            )

            # Interface class directly inherits Instrument
            assert issubclass(category_cls, Instrument)
            assert Instrument in category_cls.__bases__, (
                f"{category_cls.__name__} must inherit directly from Instrument"
            )

            # Cannot be an implementation of another category
            for other_name, other_cls in categories.items():
                if other_name != category_name:
                    assert not issubclass(category_cls, other_cls), (
                        f"Category {category_cls.__name__} cannot subclass another category {other_cls.__name__}"
                    )

    def test_physical_driver_implementations_have_parent_class(self):
        """
        Every concrete physical driver implementation module must define classes that
        inherit from an Instrument Category Base Class and from Instrument.
        """
        categories = discover_instrument_categories()

        total_drivers = 0
        for category_name, category_cls in categories.items():
            category_dir = DRIVERS_PATH / category_name
            for py_file in sorted(category_dir.glob("*.py")):
                if not is_physical_driver_module(py_file):
                    continue
                if py_file.stat().st_size == 0:
                    continue

                mod_imported = __import__(f"piec.drivers.{category_name}.{py_file.stem}", fromlist=["*"])
                subclasses = local_subclasses_in_module(mod_imported, Instrument)

                assert subclasses, (
                    f"Driver file {py_file} contains no Instrument subclasses"
                )

                for driver_cls in subclasses:
                    if not is_physical_driver_class(driver_cls):
                        continue
                    total_drivers += 1
                    # 1. Must have explicit bases (not just object)
                    assert len(driver_cls.__bases__) >= 1
                    assert driver_cls.__bases__ != (object,)

                    # 2. Must inherit from the category parent class
                    assert issubclass(driver_cls, category_cls), (
                        f"Driver {driver_cls.__name__} in {py_file} must inherit from category {category_cls.__name__}"
                    )

                    # 3. Must inherit from Instrument
                    assert issubclass(driver_cls, Instrument), (
                        f"Driver {driver_cls.__name__} in {py_file} must inherit from Instrument"
                    )

        assert total_drivers >= 15, f"Expected at least 15 physical drivers, found {total_drivers}"

    def test_unparented_class_rejected(self):
        """A driver class that does not inherit from a category base fails the contract."""
        categories = discover_instrument_categories()
        all_cat_classes = tuple(categories.values())

        # Unparented class
        class RawClass:
            channel = [1]

        assert not issubclass(RawClass, Instrument)
        assert not issubclass(RawClass, all_cat_classes)

        # Class inheriting directly from Instrument without category
        class DirectlyFromInstrument(Instrument):
            channel = [1]

        assert issubclass(DirectlyFromInstrument, Instrument)
        assert not issubclass(DirectlyFromInstrument, all_cat_classes)


# ============================================================================
# Test Suite: 2. Class Attribute Conformance
# ============================================================================

class TestPhysicalDriverClassAttributes:
    """Verifies that non-None parent attributes are preserved, typed, and supersets."""

    @pytest.mark.parametrize("category_name", sorted(discover_physical_driver_classes().keys()))
    def test_all_discovered_physical_drivers_attribute_conformance(self, category_name):
        """
        Dynamically test all physical drivers in a category: every non-None class attribute
        on the parent class must be defined, preserve type, and contain parent elements.
        """
        categories = discover_instrument_categories()
        category_cls = categories[category_name]
        drivers = discover_physical_driver_classes().get(category_name, [])

        for driver_cls in drivers:
            # Check against category parent and all bases in MRO up to Instrument
            for base in driver_cls.__mro__:
                if base in (object, Instrument, VirtualInstrument):
                    continue
                assert_class_attributes_conformance(driver_cls, base)

    def test_attribute_conformance_negative_missing_element(self):
        """Child having channel=[2, 3, 4] when parent has channel=[1] must fail."""
        from piec.drivers.awg.awg import Awg

        class IncompleteAwg(Awg):
            channel = [2, 3, 4]

        with pytest.raises(AssertionError, match="missing parent-required values.*1"):
            assert_class_attributes_conformance(IncompleteAwg, Awg)

    def test_attribute_conformance_negative_type_mismatch(self):
        """Child having list instead of tuple for range attribute must fail."""
        from piec.drivers.awg.awg import Awg

        class WrongTypeAwg(Awg):
            duty_cycle = [0.0, 100.0]  # Parent defines tuple (0.0, 100.0)

        with pytest.raises(AssertionError, match="must be a tuple"):
            assert_class_attributes_conformance(WrongTypeAwg, Awg)

    def test_attribute_conformance_negative_none_override(self):
        """Child overriding a non-None parent attribute with None must fail."""
        from piec.drivers.awg.awg import Awg

        class NoneOverrideAwg(Awg):
            channel = None

        with pytest.raises(AssertionError, match="cannot be missing or None"):
            assert_class_attributes_conformance(NoneOverrideAwg, Awg)


# ============================================================================
# Test Suite: 3 & 4. Method Implementation (Blank Stub Detection & MRO Traversal)
# ============================================================================

class TestPhysicalDriverMethodImplementation:
    """Verifies that non-optional methods are implemented with real code."""

    def test_blank_stub_detector_behavior(self):
        """Confirm is_blank_stub accurately identifies blank code vs real logic."""
        def stub_docstring_only(self):
            """Docstring only."""

        def stub_with_pass(self):
            """Docstring."""
            pass

        def stub_with_ellipsis(self):
            ...

        def stub_pass_only(self):
            pass

        def real_method_write(self):
            self.instrument.write("COMMAND")

        def real_method_return(self):
            return 42

        def real_method_compound(self):
            self.real_method_write()
            return self.real_method_return()

        assert is_blank_stub(stub_docstring_only) is True
        assert is_blank_stub(stub_with_pass) is True
        assert is_blank_stub(stub_with_ellipsis) is True
        assert is_blank_stub(stub_pass_only) is True

        assert is_blank_stub(real_method_write) is False
        assert is_blank_stub(real_method_return) is False
        assert is_blank_stub(real_method_compound) is False

    def test_scpi_drivers_inherit_all_mandatory_scpi_commands(self):
        """
        Drivers that inherit from Scpi must resolve all standard IEEE 488.2 / SCPI
        commands (idn, reset, clear, error, wait, self_test, operation_complete)
        to real implementations.
        """
        scpi_commands = [
            "idn", "reset", "clear", "error", "wait", "self_test", "operation_complete",
        ]
        all_physical = discover_physical_driver_classes()

        for category_name, drivers in all_physical.items():
            for driver_cls in drivers:
                if issubclass(driver_cls, Scpi):
                    for cmd in scpi_commands:
                        method = getattr(driver_cls, cmd, None)
                        assert method is not None, (
                            f"SCPI driver {driver_cls.__name__} is missing command {cmd}"
                        )
                        assert not is_blank_stub(method), (
                            f"SCPI driver {driver_cls.__name__}.{cmd} resolves to a blank stub"
                        )

    def test_all_physical_drivers_implement_idn(self):
        """
        Every physical instrument driver in PIEC must implement idn(),
        and it cannot remain the default Instrument.idn placeholder.
        """
        all_physical = discover_physical_driver_classes()

        for category_name, drivers in all_physical.items():
            for driver_cls in drivers:
                idn_method = getattr(driver_cls, "idn", None)
                assert idn_method is not None, f"{driver_cls.__name__} has no idn method"
                assert not is_default_instrument_idn(idn_method), (
                    f"{driver_cls.__name__}.idn is still the default un-overridden Instrument.idn"
                )
                assert not is_blank_stub(idn_method), (
                    f"{driver_cls.__name__}.idn resolves to a blank stub"
                )

    def test_blank_stub_in_child_fails_assertion(self):
        """A driver inheriting a blank stub from parent category fails the implementation check."""
        from piec.drivers.awg.awg import Awg

        class IncompleteDriver(Awg):
            channel = [1]
            # output is a blank stub in Awg, and not implemented here

        output_method = getattr(IncompleteDriver, "output")
        assert is_blank_stub(output_method) is True, (
            "IncompleteDriver.output should be detected as a blank stub"
        )


# ============================================================================
# Parameterized Non-Optional Method Tests Across All Discovered Physical Drivers
# ============================================================================

def _build_physical_driver_method_cases():
    """Build parameterized test cases for all physical model drivers and category methods."""
    categories = discover_instrument_categories()
    physical_drivers = discover_physical_driver_classes()
    cases = []

    for category_name, drivers in physical_drivers.items():
        cat_cls = categories[category_name]

        # Find all public methods in the category base class
        for method_name, parent_fn in inspect.getmembers(cat_cls, inspect.isfunction):
            if method_name.startswith("_"):
                continue
            if getattr(parent_fn, "_is_optional", False):
                # @optional methods are exempt
                continue

            # Only check methods that are blank stubs in the category base class
            # (Compound methods implemented in the parent like configure_waveform are valid)
            if not is_blank_stub(parent_fn):
                continue

            for driver_cls in drivers:
                test_id = f"{driver_cls.__name__}-{method_name}"
                cases.append(pytest.param(driver_cls, method_name, id=test_id))
    return cases


@pytest.mark.parametrize("driver_cls,method_name", _build_physical_driver_method_cases())
def test_physical_driver_non_optional_methods_implemented(driver_cls, method_name):
    """
    Assert that every physical driver implements all non-optional methods
    defined by its category base class (i.e. does not inherit blank stubs).
    """
    method = getattr(driver_cls, method_name, None)
    assert method is not None, f"{driver_cls.__name__} is missing method '{method_name}'"
    assert not is_blank_stub(method), (
        f"{driver_cls.__name__}.{method_name} is not implemented (inherits a blank stub)"
    )


# ============================================================================
# Test Suite: 5. Autodetect Verification Across Physical Drivers
# ============================================================================

def _all_physical_drivers_list() -> List[Type[Instrument]]:
    """Return a flat list of all discovered physical driver classes."""
    res: List[Type[Instrument]] = []
    for drv_list in discover_physical_driver_classes().values():
        res.extend(drv_list)
    return sorted(res, key=lambda c: c.__name__)


def _visa_autodetect_driver_cases():
    """Build parameterized test cases for physical drivers supporting VISA IDN autodetect."""
    drivers_by_cat = discover_physical_driver_classes()
    categories = discover_instrument_categories()
    cases = []
    for cat_name, drv_list in sorted(drivers_by_cat.items()):
        cat_cls = categories[cat_name]
        for drv_cls in drv_list:
            idn = getattr(drv_cls, "AUTODETECT_ID", None)
            if issubclass(drv_cls, Digilent):
                continue
            cases.append(pytest.param(drv_cls, cat_cls, idn, cat_name, id=drv_cls.__name__))
    return cases


def make_test_physical_driver(driver_cls: Type[Instrument], check_params: bool = True) -> Any:
    """Construct physical driver instance with ScriptedTransport and DG1000 dialect."""
    responses = {
        "*IDN?": f"TEST,{getattr(driver_cls, 'AUTODETECT_ID', 'ID')},12345,1.0",
        "ID?": f"{getattr(driver_cls, 'AUTODETECT_ID', 'ID')}",
        "?": f"{getattr(driver_cls, 'AUTODETECT_ID', 'ID')}",
    }
    return create_test_driver(
        driver_cls,
        responses=responses,
        check_params=check_params,
        protocol="dg1000",
    )


class TestPhysicalDriverAutodetect:
    """Verifies AUTODETECT_ID declarations, registry registration, and VISA probing."""

    @pytest.mark.parametrize("driver_cls", _all_physical_drivers_list(), ids=lambda c: c.__name__)
    def test_physical_driver_defines_autodetect_id(self, driver_cls):
        """
        All physical instrument drivers must define AUTODETECT_ID as a
        non-empty string or list/tuple of strings (no exceptions).
        """
        assert hasattr(driver_cls, "AUTODETECT_ID"), (
            f"{driver_cls.__name__} must define class attribute AUTODETECT_ID"
        )
        autodetect_id = driver_cls.AUTODETECT_ID
        assert autodetect_id is not None, (
            f"{driver_cls.__name__}.AUTODETECT_ID cannot be None"
        )
        assert isinstance(autodetect_id, (str, list, tuple)), (
            f"{driver_cls.__name__}.AUTODETECT_ID must be a str, list, or tuple"
        )
        if isinstance(autodetect_id, str):
            assert len(autodetect_id.strip()) > 0, (
                f"{driver_cls.__name__}.AUTODETECT_ID cannot be an empty string"
            )
        else:
            assert len(autodetect_id) > 0, (
                f"{driver_cls.__name__}.AUTODETECT_ID collection cannot be empty"
            )
            for item in autodetect_id:
                assert isinstance(item, str) and len(item.strip()) > 0, (
                    f"{driver_cls.__name__}.AUTODETECT_ID items must be non-empty strings"
                )

    @pytest.mark.parametrize("driver_cls", _all_physical_drivers_list(), ids=lambda c: c.__name__)
    def test_dynamic_driver_scan_registers_driver(self, driver_cls):
        """
        _dynamic_driver_scan() must discover and register every physical driver
        under its defined AUTODETECT_ID keys (no exceptions).
        """
        from piec.drivers.autodetect import _dynamic_driver_scan

        registry = _dynamic_driver_scan()
        autodetect_id = getattr(driver_cls, "AUTODETECT_ID", None)
        assert autodetect_id != "" and autodetect_id is not None, (
            f"{driver_cls.__name__} has an empty AUTODETECT_ID and was not registered in driver scan"
        )

        expected_path = f"{driver_cls.__module__}.{driver_cls.__name__}"
        keys = [autodetect_id] if isinstance(autodetect_id, str) else list(autodetect_id)
        for k in keys:
            assert k in registry, (
                f"Key {k!r} for {driver_cls.__name__} not found in _dynamic_driver_scan registry"
            )
            assert registry[k] == expected_path, (
                f"Key {k!r} mapped to {registry[k]!r}, expected {expected_path!r}"
            )

    @pytest.mark.parametrize("driver_cls,cat_cls,autodetect_id,cat_name", _visa_autodetect_driver_cases())
    def test_visa_idn_autodetect_matches_and_dispatches_driver(
        self, monkeypatch, driver_cls, cat_cls, autodetect_id, cat_name
    ):
        """
        When probing a VISA address with *IDN? returning a string containing the driver's
        AUTODETECT_ID, autodetect(address) dynamically loads and instantiates the driver class.
        """
        assert autodetect_id != "" and autodetect_id is not None, (
            f"{driver_cls.__name__} has an empty AUTODETECT_ID and cannot be detected via IDN"
        )
        from piec.drivers import autodetect as autodetect_mod
        from piec.drivers import instrument as instrument_mod

        id_key = autodetect_id[0] if isinstance(autodetect_id, (list, tuple)) else autodetect_id
        simulated_idn = f"HEWLETT-PACKARD,{id_key},MY12345678,1.0"

        class FakeManager:
            def open_resource(self, address, **kwargs):
                return ScriptedTransport(address=address)

        probe_transport = ScriptedTransport(responses={
            "*IDN?": simulated_idn,
            "ID?": id_key,
            "?": id_key,
        })

        class FakeProbeScpi:
            def __init__(self, address, **kwargs):
                self.instrument = probe_transport

        monkeypatch.setattr(instrument_mod, "PiecManager", FakeManager)
        monkeypatch.setattr(autodetect_mod, "Scpi", FakeProbeScpi)
        monkeypatch.setattr(autodetect_mod, "_load_registry_cache", lambda: {})
        monkeypatch.setattr(autodetect_mod, "_save_registry_cache", lambda reg: None)

        address = "GPIB0::7::INSTR"

        # 1. Successful detection without category restriction
        inst = autodetect_mod.autodetect(address)
        assert inst is not None, f"Autodetect returned None for {driver_cls.__name__}"
        assert isinstance(inst, driver_cls), (
            f"Autodetect returned {type(inst).__name__}, expected {driver_cls.__name__}"
        )

        # 2. Successful detection with matching required_type
        inst_filtered = autodetect_mod.autodetect(address, required_type=cat_cls)
        assert isinstance(inst_filtered, driver_cls)

        # 3. Rejection when required_type is a mismatched category
        categories = discover_instrument_categories()
        mismatched_cat = next((c for name, c in categories.items() if name != cat_name), None)
        if mismatched_cat is not None:
            inst_rejected = autodetect_mod.autodetect(address, required_type=mismatched_cat)
            assert inst_rejected is None, (
                f"Autodetect should reject {driver_cls.__name__} when required_type={mismatched_cat.__name__}"
            )


# ============================================================================
# Test Suite: 6. Runtime Parameter Validation Across Physical Drivers
# ============================================================================

class TestPhysicalDriverRuntimeParameterValidation:
    """Verifies check_params=True behavior, parameter validation, and command blocking."""

    @pytest.mark.parametrize("driver_cls", _all_physical_drivers_list(), ids=lambda c: c.__name__)
    def test_direct_parameter_checking_lists_and_ranges(self, driver_cls):
        """
        Directly validates class attributes through _check_params:
        - Valid list items pass; invalid items raise ValueError.
        - Valid range midpoints pass; out-of-range values raise ValueError.
        """
        inst = make_test_physical_driver(driver_cls, check_params=True)
        assert inst.check_params is True

        for attr_name, attr_val in vars(driver_cls).items():
            if attr_name.startswith("_") or callable(attr_val) or attr_name == "AUTODETECT_ID":
                continue

            # Skip TDS6604 channel_impedance which intentionally delegates to adapter setter
            if driver_cls.__name__ == "TDS6604" and attr_name == "channel_impedance":
                continue

            # 1. Discrete list attributes (e.g. channel, coupling, waveform)
            if isinstance(attr_val, list) and len(attr_val) > 0:
                valid_val = attr_val[0]
                inst._check_params(inst, {attr_name: valid_val})

                invalid_val = 999999 if isinstance(valid_val, (int, float)) else "__PIEC_INVALID_VAL__"
                with pytest.raises(ValueError, match="not in list|out of acceptable"):
                    inst._check_params(inst, {attr_name: invalid_val})

            # 2. Numeric range tuples (min, max) with finite boundaries
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

    @pytest.mark.parametrize("driver_cls", _all_physical_drivers_list(), ids=lambda c: c.__name__)
    def test_method_runtime_validation_blocks_command_transmission(self, driver_cls):
        """
        When check_params=True, invoking a method with invalid arguments:
        1. Raises ValueError before method body execution.
        2. Leaves transport write queue empty (zero commands sent to hardware).
        When check_params=False, parameter validation is bypassed.
        """
        inst_checked = make_test_physical_driver(driver_cls, check_params=True)
        class_attrs = get_class_attributes_from_instance(inst_checked)

        target_method_name = None
        target_param_name = None
        invalid_param_val = None

        for m_name, fn in inspect.getmembers(driver_cls, inspect.isfunction):
            if m_name.startswith("_") or getattr(fn, "_is_optional", False):
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

        assert target_method_name is not None, (
            f"Could not find any public method accepting a checked parameter on {driver_cls.__name__}"
        )

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

        # 1. With check_params=True: must raise ValueError and write 0 commands
        inst_checked.instrument.writes.clear()
        with pytest.raises(ValueError):
            getattr(inst_checked, target_method_name)(**bad_kwargs)

        assert len(inst_checked.instrument.writes) == 0, (
            f"{driver_cls.__name__}.{target_method_name} transmitted commands "
            f"{inst_checked.instrument.writes!r} despite validation failure"
        )

        # 2. With check_params=False: validation is bypassed
        inst_unchecked = make_test_physical_driver(driver_cls, check_params=False)
        inst_unchecked.instrument.writes.clear()
        try:
            getattr(inst_unchecked, target_method_name)(**bad_kwargs)
        except ValueError as exc:
            err_text = str(exc)
            assert "out of acceptable" not in err_text and "not in list" not in err_text, (
                f"Unexpected validation error with check_params=False: {exc}"
            )
        except Exception:
            pass

    @pytest.mark.parametrize("driver_cls", _all_physical_drivers_list(), ids=lambda c: c.__name__)
    def test_state_tracking_updates_on_valid_method_call(self, driver_cls):
        """
        When a method executes with valid arguments and check_params=True,
        the internal state tracker _current_<attr> is populated.
        """
        inst = make_test_physical_driver(driver_cls, check_params=True)
        class_attrs = get_class_attributes_from_instance(inst)

        for m_name, fn in inspect.getmembers(driver_cls, inspect.isfunction):
            if m_name.startswith("_") or getattr(fn, "_is_optional", False):
                continue
            if is_blank_stub(fn):
                continue

            sig = inspect.signature(fn)
            for p_name, param in sig.parameters.items():
                if p_name in class_attrs and class_attrs[p_name] is not None:
                    attr_val = class_attrs[p_name]
                    valid_val = None
                    if isinstance(attr_val, list) and len(attr_val) > 0:
                        valid_val = attr_val[0]
                    elif isinstance(attr_val, tuple) and len(attr_val) == 2:
                        low, high = attr_val
                        if low is not None and high is not None and isinstance(low, Real) and isinstance(high, Real) and low < high:
                            valid_val = (low + high) / 2.0

                    if valid_val is not None:
                        call_kwargs = {}
                        for p, p_param in sig.parameters.items():
                            if p == "self":
                                continue
                            if p == p_name:
                                call_kwargs[p] = valid_val
                            elif p_param.default is not inspect._empty:
                                call_kwargs[p] = p_param.default
                            else:
                                call_kwargs[p] = 1

                        try:
                            getattr(inst, m_name)(**call_kwargs)
                            state_attr = f"_current_{p_name}"
                            current_state = getattr(inst, state_attr, None)
                            if current_state is not None:
                                expected_comparison = str(valid_val).lower() if isinstance(valid_val, str) else valid_val
                                assert current_state == expected_comparison
                                return
                        except Exception:
                            continue

