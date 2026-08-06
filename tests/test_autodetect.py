"""Tests for physical and virtual autodetect behavior."""

import importlib

import pytest

from piec.drivers.autodetect import autodetect
from piec.drivers.awg.virtual_awg import VirtualAwg
from piec.drivers.oscilloscope.virtual_oscilloscope import VirtualScope


autodetect_module = importlib.import_module("piec.drivers.autodetect")


@pytest.mark.parametrize(
    ("request", "expected_class"),
    [
        ("virtual_scope", VirtualScope),
        ("VIRTUAL_SCOPE", VirtualScope),
        ("virtual_oscilloscope", VirtualScope),
        ("virtual_awg", VirtualAwg),
    ],
)
def test_virtual_category_selects_virtual_driver(request, expected_class):
    instrument = autodetect(request)

    assert isinstance(instrument, expected_class)
    assert instrument.virtual is True


def test_virtual_autodetect_forwards_constructor_options():
    scope = autodetect("virtual_scope", check_params=True)

    assert isinstance(scope, VirtualScope)
    assert scope.check_params is True


def test_unknown_virtual_category_returns_none():
    assert autodetect("virtual_not_a_real_category") is None


def test_normal_category_request_does_not_fall_back_to_virtual(monkeypatch):
    class EmptyResourceManager:
        def list_resources(self):
            return ()

    def unexpected_virtual_lookup(device_type):
        raise AssertionError(
            f"Physical category request unexpectedly looked up virtual {device_type!r}"
        )

    monkeypatch.setattr(autodetect_module, "PiecManager", EmptyResourceManager)
    monkeypatch.setattr(
        autodetect_module,
        "_find_virtual_driver_class",
        unexpected_virtual_lookup,
    )

    assert autodetect("scope") is None
