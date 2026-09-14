"""Shared assertions and transport factories, with no concrete driver registry."""

from dataclasses import dataclass
import inspect
from numbers import Integral, Real
import math

from tests.support.transports import create_test_driver


def assert_channels(channels, *, name="channel", allow_empty=False, minimum=1):
    assert isinstance(channels, (list, tuple)), f"{name} must be a list or tuple"
    assert channels or allow_empty, f"{name} must not be empty"
    assert all(isinstance(ch, Integral) and not isinstance(ch, bool) for ch in channels), (
        f"{name} must contain integer channel identifiers, got {channels!r}"
    )
    assert all(ch >= minimum for ch in channels), f"{name} identifiers must be >= {minimum}"
    assert len(set(channels)) == len(channels), f"{name} contains duplicate channels"


def assert_driver_contract(driver, base):
    """Check base-declared public methods and capability shapes without I/O.

    Non-None parent attributes are requirements. Child enumerations may expand
    but cannot remove parent entries. None in the parent leaves a value optional.
    Method presence alone does not establish that a method is implemented;
    independent behavioral cases cover that separately.
    """
    cls = driver if inspect.isclass(driver) else type(driver)
    assert issubclass(cls, base)
    for name, default in vars(base).items():
        if name.startswith("_"):
            continue
        # Static inspection avoids Instrument.__getattr__ inventing missing methods.
        value = inspect.getattr_static(driver, name)
        label = f"{cls.__name__}.{name}"
        if callable(default):
            assert callable(value), f"{label} must be callable"
        elif name == "channel" or name.endswith("_channel"):
            daq_channels = name in ("ai_channel", "ao_channel", "dio_channel")
            assert_channels(value, name=label, allow_empty=daq_channels,
                            minimum=0 if daq_channels else 1)
        elif isinstance(default, list) and default and all(isinstance(v, str) for v in default):
            if value is not None:
                assert isinstance(value, (list, tuple)) and value, f"{label} must be a nonempty enumeration"
                assert all(isinstance(v, str) for v in value), f"{label} must contain strings"
        elif isinstance(default, (tuple, dict)):
            assert_capability(value, label)
        if not callable(default):
            assert_parent_requirement(value, default, label)
    # Some categories (e.g. RFSource) leave capabilities to the concrete class.
    if "channel" not in vars(base) and inspect.getattr_static(driver, "channel", None) is not None:
        assert_channels(inspect.getattr_static(driver, "channel"), name=f"{cls.__name__}.channel")


def assert_parent_requirement(value, required, label):
    """Enforce parent declarations independently of device-specific expectations.

    Inherited declarations count; a child need not repeat an unchanged attribute.
    Tuple bounds describe device limits, so their values may differ, but concrete
    parent bounds cannot become unspecified. Dict requirements apply recursively.
    """
    if required is None:
        return
    assert value is not None, f"{label} is required by the parent and cannot be None"
    if isinstance(required, list):
        assert isinstance(value, (list, tuple)), f"{label} must implement the parent enumeration"
        missing = []
        for item in required:
            if isinstance(item, (tuple, dict)):
                # E.g. DAQ ai_range=[(None, None)] declares a range schema,
                # not a requirement to advertise an unbounded hardware range.
                for candidate in value:
                    try:
                        assert_parent_requirement(candidate, item, label)
                        break
                    except AssertionError:
                        pass
                else:
                    missing.append(item)
            elif item not in value:
                missing.append(item)
        assert not missing, f"{label} is missing parent-required values: {missing!r}"
    elif isinstance(required, dict):
        assert isinstance(value, dict), f"{label} must implement the parent mapping"
        for key, requirement in required.items():
            assert key in value, f"{label} is missing parent-required key {key!r}"
            assert_parent_requirement(value[key], requirement, f"{label}[{key!r}]")
    elif isinstance(required, tuple):
        if required == (None, None):
            # (None, None) represents an open capability requirement.
            # Concrete drivers may fulfill this requirement using a continuous
            # tuple range (min, max), a discrete choices list, or a dependent
            # configuration dict.
            assert_capability(value, label)
            return
        assert isinstance(value, tuple) and len(value) == len(required), (
            f"{label} must implement the parent {len(required)}-element tuple"
        )
        for index, requirement in enumerate(required):
            assert_parent_requirement(value[index], requirement, f"{label}[{index}]")
    elif isinstance(required, Real) and not isinstance(required, bool):
        assert isinstance(value, Real) and not isinstance(value, bool), f"{label} must be numeric"
    else:
        assert isinstance(value, type(required)), f"{label} must implement parent type {type(required).__name__}"


def assert_capability(value, label):
    """Ranges may depend on another setting, as supported by Instrument validation."""
    if value is None:
        return
    if isinstance(value, dict):
        assert value and all(isinstance(key, str) for key in value), f"{label} must have named settings"
        for key, child in value.items():
            assert_capability(child, f"{label}[{key!r}]")
        return
    if isinstance(value, list) and value and all(isinstance(v, str) for v in value):
        return  # Discrete named choices are also supported by Instrument._check_params.
    assert isinstance(value, (tuple, list)), f"{label} must be a range or numeric choices"
    assert all(v is None or (isinstance(v, Real) and not isinstance(v, bool)
                            and math.isfinite(v)) for v in value), f"{label} must contain finite numbers or None"
    if isinstance(value, tuple):
        assert len(value) == 2, f"{label} must be a (minimum, maximum) pair"
        low, high = value
        assert low is None or high is None or low <= high, f"{label} bounds are reversed"
    else:
        assert value and all(v is not None for v in value), f"{label} must contain numeric choices"


def case_for(cls, cases):
    matches = [case for case in cases if case.cls is cls]
    assert len(matches) == 1, (
        f"{cls.__module__}.{cls.__name__}: expected one independent behavioral fixture, "
        f"found {len(matches)}. Add its setup and expected commands/responses beside "
        "the category test. Declaration checks run automatically without this fixture."
    )
    return matches[0]


@dataclass(frozen=True)
class DriverCase:
    cls: type
    factory: object
    operation: object
    expected: object

    def check(self, monkeypatch, base):
        instrument = self.factory(monkeypatch)
        assert type(instrument) is self.cls, "Fixture must exercise the concrete driver"
        assert_driver_contract(instrument, base)
        assert self.operation(instrument) == self.expected


def physical(cls, responses=None, **state):
    """Attach a strict fake transport; this does not exercise hardware initialization."""
    return lambda monkeypatch: create_test_driver(cls, responses=responses, strict=True, **state)


def virtual(cls, **options):
    return lambda monkeypatch: cls(**options)
