"""Tests for the shared category virtual-driver discovery helper."""

import piec.drivers.autodetect as autodetect_module

from piec.drivers.awg.virtual_awg import VirtualAwg
from piec.drivers.oscilloscope.virtual_oscilloscope import VirtualScope
from piec.drivers.virtual_dispatch import (
    VirtualDriverAmbiguityError,
    find_virtual_driver_class,
)


def test_shared_discovery_finds_virtual_driver_by_category():
    assert find_virtual_driver_class("awg") is VirtualAwg
    assert find_virtual_driver_class("oscilloscope") is VirtualScope


def test_shared_discovery_applies_category_aliases():
    assert find_virtual_driver_class("scope") is VirtualScope


def test_shared_discovery_returns_none_for_unknown_category():
    assert find_virtual_driver_class("not_a_real_category") is None


def test_autodetect_uses_shared_discovery_function():
    assert autodetect_module._find_virtual_driver_class is find_virtual_driver_class
    assert autodetect_module.VirtualDriverAmbiguityError is VirtualDriverAmbiguityError

