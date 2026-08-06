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


def test_physical_idn_selects_cached_model_driver_and_closes_probe(monkeypatch):
    address = "USB0::0x0957::0x0000::MY12345678::INSTR"
    selected_path = "piec.drivers.awg.k_81150a.Keysight81150a"
    probe_resources = []
    imported_paths = []

    class ProbeResource:
        def __init__(self):
            self.closed = False
            self.queries = []

        def query(self, command):
            self.queries.append(command)
            return "KEYSIGHT TECHNOLOGIES,81150A,MY12345678,1.0"

        def read(self):
            return ""

        def close(self):
            self.closed = True

    class ProbeScpi:
        def __init__(self, address):
            self.address = address
            self.instrument = ProbeResource()
            probe_resources.append(self.instrument)

    class SelectedDriver:
        def __init__(self, address, **kwargs):
            self.address = address
            self.options = kwargs

    def import_selected_driver(class_path):
        imported_paths.append(class_path)
        return SelectedDriver

    def unexpected_dynamic_scan(verbose=False):
        raise AssertionError("A cached IDN match should not rescan driver modules")

    monkeypatch.setattr(autodetect_module, "Scpi", ProbeScpi)
    monkeypatch.setattr(
        autodetect_module,
        "_load_registry_cache",
        lambda: {"81150A": selected_path},
    )
    monkeypatch.setattr(
        autodetect_module,
        "_import_class_from_path",
        import_selected_driver,
    )
    monkeypatch.setattr(
        autodetect_module,
        "_dynamic_driver_scan",
        unexpected_dynamic_scan,
    )

    instrument = autodetect(address, verbose=True, check_params=True)

    assert isinstance(instrument, SelectedDriver)
    assert instrument.address == address
    assert instrument.options == {"verbose": True, "check_params": True}
    assert imported_paths == [selected_path]
    assert len(probe_resources) == 1
    assert probe_resources[0].queries == ["*IDN?"]
    assert probe_resources[0].closed is True


def test_physical_idn_scans_drivers_when_cache_has_no_match(monkeypatch):
    address = "GPIB0::8::INSTR"
    selected_path = "piec.drivers.awg.k_81150a.Keysight81150a"
    saved_registries = []

    class ProbeResource:
        def query(self, command):
            return "KEYSIGHT,81150A,MY12345678,1.0"

        def read(self):
            return ""

        def close(self):
            pass

    class ProbeScpi:
        def __init__(self, address):
            self.instrument = ProbeResource()

    class SelectedDriver:
        def __init__(self, address, **kwargs):
            self.address = address

    monkeypatch.setattr(autodetect_module, "Scpi", ProbeScpi)
    monkeypatch.setattr(autodetect_module, "_load_registry_cache", lambda: {})
    monkeypatch.setattr(
        autodetect_module,
        "_dynamic_driver_scan",
        lambda verbose=False: {"81150A": selected_path},
    )
    monkeypatch.setattr(
        autodetect_module,
        "_save_registry_cache",
        lambda registry: saved_registries.append(registry.copy()),
    )
    monkeypatch.setattr(
        autodetect_module,
        "_import_class_from_path",
        lambda class_path: SelectedDriver,
    )

    instrument = autodetect(address)

    assert isinstance(instrument, SelectedDriver)
    assert instrument.address == address
    assert saved_registries == [{"81150A": selected_path}]
