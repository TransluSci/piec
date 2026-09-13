"""
Tests for core instrument architecture, SCPI mixin, virtual dispatch, and physical autodetect.

Consolidates:
- tests/test_instrument_core.py
- tests/test_virtual_dispatch.py
- physical autodetect tests from tests/test_autodetect.py
"""

from __future__ import annotations

import importlib
import warnings
from unittest.mock import Mock
import numpy as np
import pytest

import piec.drivers.instrument as instrument_module
import piec.drivers.autodetect as autodetect_module
from piec.drivers import digilent as digilent_module
from piec.drivers.digilent import Digilent
from piec.drivers.instrument import (
    AutoCheckMeta,
    Instrument,
    convert_to_lowercase,
    is_contained,
    is_value_between,
)
from piec.drivers.scpi import Scpi
from piec.drivers.virtual_instrument import VirtualInstrument
from piec.drivers.virtual_dispatch import (
    VirtualDriverDispatchError,
    VirtualDriverNotFoundError,
)

from piec.drivers.awg.agilent_33220a import Agilent33220A
from piec.drivers.awg.k_81150a import Keysight81150a
from piec.drivers.awg.sdg2000 import SDG2000X
from piec.drivers.awg.virtual_awg import VirtualAwg
from piec.drivers.daq.usb231 import USB231
from piec.drivers.daq.virtual_daq import VirtualDaq
from piec.drivers.dc_calibrator.edc522 import EDC522
from piec.drivers.dc_calibrator.virtual_calibrator import VirtualCalibrator
from piec.drivers.oscilloscope.k_dsox3024a import KeysightDSOX3024a
from piec.drivers.oscilloscope.lecroy_sda6020 import LeCroySDA6020
from piec.drivers.oscilloscope.tektronix_tds2000 import TektronixTDS2000
from piec.drivers.oscilloscope.virtual_oscilloscope import VirtualScope
from piec.drivers.autodetect import autodetect


# ============================================================================
# Fakes and Helper Drivers
# ============================================================================

class _FakeResource:
    def __init__(self, resource_name):
        self.resource_name = resource_name
        self.queries = []
        self.writes = []
        self.closed = False
        self.timeout = 2000

    def query(self, command):
        self.queries.append(command)
        if "*IDN?" in command:
            return "PIEC,TEST_DEV,1234,1.0"
        if "*ESR?" in command:
            return "0"
        if "*TST?" in command:
            return "0"
        if "*OPC?" in command:
            return "1"
        return ""

    def write(self, command):
        self.writes.append(command)

    def close(self):
        self.closed = True


class _FakeManager:
    def __init__(self):
        self.open_calls = []

    def open_resource(self, address, **kwargs):
        self.open_calls.append((address, kwargs))
        return _FakeResource(address)


@pytest.fixture
def fake_resource_manager(monkeypatch):
    manager = _FakeManager()
    monkeypatch.setattr(instrument_module, "PiecManager", lambda: manager)
    return manager


class _DemoDriver(Instrument, metaclass=AutoCheckMeta):
    waveform = ["SIN", "SQU", "RAMP"]
    frequency = (1, 1e6)

    def set_waveform(self, waveform):
        pass

    def set_frequency(self, frequency):
        pass

    def configure(self, waveform, frequency):
        pass


class _NoneAttrDriver(Instrument, metaclass=AutoCheckMeta):
    waveform = None

    def set_waveform(self, waveform):
        pass


class _DependentDriver(Instrument, metaclass=AutoCheckMeta):
    input_configuration = ["A", "A-B"]
    sensitivity = {
        "input_configuration": {
            "A": [1e-9, 1e-8, 1e-7],
            "A-B": [1e-9, 1e-8],
        }
    }

    def set_input(self, input_configuration):
        pass

    def set_sensitivity(self, sensitivity, input_configuration=None):
        pass


class _DemoScpiDriver(Scpi):
    frequency = (1, 1e6)

    def set_frequency(self, frequency):
        pass


# ============================================================================
# 1. Helper Function Tests
# ============================================================================

class TestHelperFunctions:
    def test_is_contained(self):
        assert is_contained("AC", ["AC", "DC"]) is True
        assert is_contained("ac", ["AC", "DC"]) is True
        assert is_contained(1.0, [1, 2, 3]) is True
        assert is_contained(1e-9, [1e-9, 1e-8, 1e-7]) is True
        assert is_contained("GND", ["AC", "DC"]) is False
        assert is_contained(None, ["AC", "DC"]) is True

    def test_is_value_between(self):
        assert is_value_between(500, (0, 1e6)) is True
        assert is_value_between(0, (0, 1e6)) is True
        assert is_value_between(1e6, (0, 1e6)) is True
        assert is_value_between(-1, (0, 1e6)) is False
        assert is_value_between(2e6, (0, 1e6)) is False
        assert is_value_between("500", (0, 1e6)) is True
        assert is_value_between(None, (0, 1e6)) is True

    def test_convert_to_lowercase(self):
        assert convert_to_lowercase({"coupling": "AC"}) == {"coupling": "ac"}
        assert convert_to_lowercase({"frequency": 1000}) == {"frequency": 1000}
        assert convert_to_lowercase({"coupling": "DC", "frequency": 5000}) == {
            "coupling": "dc",
            "frequency": 5000,
        }


# ============================================================================
# 2. Core Instrument Connection and Parameter Validation
# ============================================================================

class TestInstrumentCore:
    def test_virtual_looking_addresses_opened_normally(self, fake_resource_manager):
        inst = Instrument(address="VIRTUAL")
        assert fake_resource_manager.open_calls == [("VIRTUAL", {})]
        assert inst.instrument.resource_name == "VIRTUAL"

    def test_flags_stored_and_state_initialized(self, fake_resource_manager):
        inst = Instrument(address="TEST::INSTR", check_params=True, verbose=True)
        assert inst.check_params is True
        assert inst.verbose is True
        assert isinstance(inst.idn(), str)

        driver = _DemoDriver(address="TEST::INSTR")
        assert driver._current_waveform is None
        assert driver._current_frequency is None

    def test_physical_open_failure_raises_connection_error(self, monkeypatch):
        class FailingManager:
            def open_resource(self, address, **kwargs):
                raise RuntimeError("VISA open failed")

        monkeypatch.setattr(instrument_module, "PiecManager", FailingManager)
        with pytest.raises(ConnectionError, match="GPIB0::1::INSTR") as exc_info:
            Instrument(address="GPIB0::1::INSTR")
        assert isinstance(exc_info.value.__cause__, RuntimeError)

    def test_digilent_address_validation(self, monkeypatch):
        monkeypatch.setattr(digilent_module, "mcc_ul_imported", False)
        monkeypatch.setattr(digilent_module, "ul", None)
        with pytest.raises(ImportError, match="mcculw"):
            Digilent(address="VIRTUAL")

        monkeypatch.setattr(digilent_module, "mcc_ul_imported", True)
        monkeypatch.setattr(digilent_module, "ul", object())
        with pytest.raises(ValueError, match="MCC Board Number"):
            Digilent(address="VIRTUAL")

    def test_check_params_validation(self, fake_resource_manager):
        driver = _DemoDriver(address="TEST::INSTR", check_params=True)
        driver.set_waveform("SIN")
        with pytest.raises(ValueError):
            driver.set_waveform("TRI")

        driver.set_frequency(1000)
        with pytest.raises(ValueError):
            driver.set_frequency(2e6)

        # check_params=False allows invalid values
        permissive = _DemoDriver(address="TEST::INSTR", check_params=False)
        permissive.set_waveform("TRI")

        # None attribute skips validation
        none_driver = _NoneAttrDriver(address="TEST::INSTR", check_params=True)
        none_driver.set_waveform("ANYTHING")

        # None argument passes
        driver.set_waveform(None)

    def test_dependent_check_params(self, fake_resource_manager):
        driver = _DependentDriver(address="TEST::INSTR", check_params=True)
        driver.set_input("A-B")
        driver.set_sensitivity(1e-8)
        with pytest.raises(ValueError, match="sensitivity.*not in list"):
            driver.set_sensitivity(1e-7)

    def test_state_tracking(self, fake_resource_manager):
        driver = _DemoDriver(address="TEST::INSTR", check_params=False)
        assert driver._current_waveform is None
        driver.set_waveform("SIN")
        assert driver._current_waveform == "sin"

        driver.set_frequency(5000)
        assert driver._current_frequency == 5000

        driver.configure("SQU", 1000)
        assert driver._current_waveform == "squ"
        assert driver._current_frequency == 1000

        # State not updated on validation error
        strict = _DemoDriver(address="TEST::INSTR", check_params=True)
        strict.set_frequency(500)
        with pytest.raises(ValueError):
            strict.set_frequency(2e6)
        assert strict._current_frequency == 500

        # Reset clears tracked state
        driver._initialize_state()
        assert driver._current_waveform is None
        assert driver._current_frequency is None


# ============================================================================
# 3. SCPI Protocol Mixin Tests
# ============================================================================

class TestScpiMixin:
    def test_scpi_commands_and_lifecycle(self, monkeypatch):
        fake_res = _FakeResource("GPIB0::1::INSTR")
        monkeypatch.setattr(instrument_module, "PiecManager", lambda: Mock(open_resource=lambda *a, **k: fake_res))

        driver = _DemoScpiDriver(address="GPIB0::1::INSTR")
        assert driver.idn() == "PIEC,TEST_DEV,1234,1.0"
        assert driver.error() == "0"
        assert driver.self_test() == "0"
        assert driver.operation_complete() == "1"

        driver.reset()
        assert "*RST" in fake_res.writes

        driver.clear()
        assert "*CLS" in fake_res.writes

        driver.wait()
        assert "*WAI" in fake_res.writes

        driver.initialize()
        assert "*RST" in fake_res.writes
        assert "*CLS" in fake_res.writes


# ============================================================================
# 4. Model-Style Virtual Driver Dispatch
# ============================================================================

class TestVirtualDispatch:
    def test_model_virtual_address_returns_virtual_instance(self):
        awg = Keysight81150a("VIRTUAL")
        assert isinstance(awg, VirtualAwg)
        assert not isinstance(awg, Keysight81150a)

    @pytest.mark.parametrize(
        ("model_class", "virtual_class"),
        [
            (Keysight81150a, VirtualAwg),
            (KeysightDSOX3024a, VirtualScope),
            (USB231, VirtualDaq),
            (EDC522, VirtualCalibrator),
        ],
    )
    def test_model_virtual_dispatch_representative_categories(self, model_class, virtual_class):
        inst = model_class("VIRTUAL")
        assert isinstance(inst, virtual_class)
        assert inst.emulated_driver_class is model_class

    @pytest.mark.parametrize("address", ["VIRTUAL_AWG", "VIRTUAL_SCOPE", "VIRTUAL_BAD"])
    def test_model_constructor_rejects_category_virtual_addresses(self, address):
        with pytest.raises(VirtualDriverDispatchError, match="only address='VIRTUAL'"):
            Keysight81150a(address)

    def test_model_virtual_class_preserves_model_capabilities(self):
        awg = Keysight81150a("VIRTUAL")
        assert isinstance(awg, VirtualAwg)
        assert awg.channel == Keysight81150a.channel
        assert awg.waveform == Keysight81150a.waveform
        assert awg.frequency == Keysight81150a.frequency

    def test_model_virtual_driver_validates_capabilities_by_default(self):
        awg = Keysight81150a("VIRTUAL")
        assert awg.check_params is True
        with pytest.raises(ValueError, match="amplitude.*out of acceptable Range"):
            awg.set_amplitude(1, 15)

    def test_model_virtual_driver_can_explicitly_disable_validation(self):
        awg = Keysight81150a("VIRTUAL", check_params=False)
        awg.set_amplitude(1, 15)
        assert awg.check_params is False
        assert awg.state["amplitude"][1] == 15

    def test_model_capabilities_applied_before_virtual_state_initialization(self):
        awg = Agilent33220A("VIRTUAL")
        assert awg.channel == [1]
        assert list(awg.state["output"]) == [1]

    def test_model_virtual_dispatch_skips_physical_constructor(self, monkeypatch):
        monkeypatch.setattr(
            Keysight81150a,
            "__init__",
            lambda *a, **k: (_ for _ in ()).throw(AssertionError("physical constructor invoked")),
        )
        awg = Keysight81150a("VIRTUAL")
        assert isinstance(awg, VirtualAwg)

    def test_model_virtual_dispatch_records_source_driver(self):
        awg = Keysight81150a("VIRTUAL")
        assert awg.is_profiled_virtual_driver is True
        assert awg.emulated_driver_class is Keysight81150a
        assert awg.virtual_driver_class is VirtualAwg

        direct = VirtualAwg()
        assert direct.is_profiled_virtual_driver is False

    def test_missing_category_virtual_driver_raises_contextual_error(self):
        class UnsupportedModel(Instrument):
            __module__ = "piec.drivers.unsupported.example"

        with pytest.raises(VirtualDriverNotFoundError) as exc_info:
            UnsupportedModel("VIRTUAL")
        assert exc_info.value.category == "unsupported"


# ============================================================================
# 5. Physical Autodetect Tests
# ============================================================================

class TestPhysicalAutodetect:
    def test_normal_category_request_does_not_fall_back_to_virtual(self, monkeypatch):
        class EmptyResourceManager:
            def list_resources(self):
                return ()

        monkeypatch.setattr(autodetect_module, "PiecManager", EmptyResourceManager)
        monkeypatch.setattr(
            autodetect_module,
            "_find_virtual_driver_class",
            lambda dt: (_ for _ in ()).throw(AssertionError("unexpected virtual lookup")),
        )
        assert autodetect("scope") is None

    def test_physical_idn_selects_cached_model_driver_and_closes_probe(self, monkeypatch):
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
            def __init__(self, address, **kwargs):
                self.address = address
                self.instrument = ProbeResource()
                probe_resources.append(self.instrument)

        class SelectedDriver:
            def __init__(self, address, **kwargs):
                self.address = address
                self.options = kwargs

        monkeypatch.setattr(autodetect_module, "Scpi", ProbeScpi)
        monkeypatch.setattr(autodetect_module, "_load_registry_cache", lambda: {"81150A": selected_path})
        monkeypatch.setattr(autodetect_module, "_import_class_from_path", lambda path: (imported_paths.append(path), SelectedDriver)[1])
        monkeypatch.setattr(autodetect_module, "_dynamic_driver_scan", lambda verbose=False: (_ for _ in ()).throw(AssertionError("unexpected scan")))

        instrument = autodetect(address, verbose=True, check_params=True)
        assert isinstance(instrument, SelectedDriver)
        assert instrument.address == address
        assert instrument.options == {"verbose": True, "check_params": True}
        assert imported_paths == [selected_path]
        assert len(probe_resources) == 1
        assert probe_resources[0].queries == ["*IDN?"]
        assert probe_resources[0].closed is True

    def test_physical_idn_scans_drivers_when_cache_has_no_match(self, monkeypatch):
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
            def __init__(self, address, **kwargs):
                self.instrument = ProbeResource()

        class SelectedDriver:
            def __init__(self, address, **kwargs):
                self.address = address

        monkeypatch.setattr(autodetect_module, "Scpi", ProbeScpi)
        monkeypatch.setattr(autodetect_module, "_load_registry_cache", lambda: {})
        monkeypatch.setattr(autodetect_module, "_dynamic_driver_scan", lambda verbose=False: {"81150A": selected_path})
        monkeypatch.setattr(autodetect_module, "_save_registry_cache", lambda reg: saved_registries.append(reg.copy()))
        monkeypatch.setattr(autodetect_module, "_import_class_from_path", lambda path: SelectedDriver)

        instrument = autodetect(address)
        assert isinstance(instrument, SelectedDriver)
        assert instrument.address == address
        assert saved_registries == [{"81150A": selected_path}]
