"""
Tests for core Instrument base class error handling and AutoCheckMeta edge cases.
"""

from __future__ import annotations

import pytest

from piec.drivers import digilent as digilent_module
from piec.drivers import mcc as mcc_module
from piec.drivers.mcc import MCC
import piec.drivers.instrument as instrument_module
from piec.drivers.instrument import AutoCheckMeta, Instrument


class _FakeResource:
    def __init__(self, resource_name):
        self.resource_name = resource_name


class _FakeManager:
    def open_resource(self, address, **kwargs):
        return _FakeResource(address)


@pytest.fixture
def fake_resource_manager(monkeypatch):
    monkeypatch.setattr(instrument_module, "PiecManager", _FakeManager)


class _DependentDriver(Instrument, metaclass=AutoCheckMeta):
    input_configuration = ["A", "B"]
    sensitivity = {
        "input_configuration": {
            "A": [1e-9, 1e-8, 1e-7],
            "B": [1e-9, 1e-8],
        }
    }

    def set_input(self, input_configuration):
        pass

    def set_sensitivity(self, sensitivity, input_configuration=None):
        pass


def test_dependent_check_params(fake_resource_manager):
    """Ensure AutoCheckMeta correctly validates dependent parameter dictionaries."""
    driver = _DependentDriver(address="TEST::INSTR", check_params=True)
    driver.set_input("B")
    driver.set_sensitivity(1e-8)
    with pytest.raises(ValueError, match="sensitivity.*not in list"):
        driver.set_sensitivity(1e-7)


def test_physical_open_failure_raises_connection_error(monkeypatch):
    """Ensure hardware connection failures are wrapped in standard ConnectionError."""
    class FailingManager:
        def open_resource(self, address, **kwargs):
            raise RuntimeError("VISA open failed")

    monkeypatch.setattr(instrument_module, "PiecManager", FailingManager)
    with pytest.raises(ConnectionError, match="GPIB0::1::INSTR") as exc_info:
        Instrument(address="GPIB0::1::INSTR")
    assert isinstance(exc_info.value.__cause__, RuntimeError)


def test_mcc_address_validation(monkeypatch):
    """Ensure MCC drivers validate MCC board numbers and handle missing dependencies."""
    monkeypatch.setattr(mcc_module, "mcc_ul_imported", False)
    monkeypatch.setattr(mcc_module, "ul", None)
    with pytest.raises(ImportError, match="mcculw"):
        MCC(address="VIRTUAL")

    monkeypatch.setattr(mcc_module, "mcc_ul_imported", True)
    monkeypatch.setattr(mcc_module, "ul", object())
    with pytest.raises(ValueError, match="MCC Board Number"):
        MCC(address="VIRTUAL")


def test_digilent_deprecation_alias():
    """Ensure piec.drivers.digilent.Digilent emits a DeprecationWarning and aliases MCC."""
    with pytest.deprecated_call(match="piec.drivers.digilent.Digilent"):
        alias_cls = getattr(digilent_module, "Digilent")
    assert alias_cls is MCC
