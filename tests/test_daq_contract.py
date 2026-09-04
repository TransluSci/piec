"""Regression tests for the model-aware DAQ interface and notebook."""

import json
import inspect
from pathlib import Path

import pytest

from piec.drivers.daq.daq import Daq
from piec.drivers.daq.usb231 import USB231
from piec.drivers.daq.usb1208hs import USB1208HS


ROOT = Path(__file__).resolve().parents[1]


NOTEBOOK_DRIVER_METHODS = [
    "idn",
    "reset",
    "clear",
    "error",
    "wait",
    "self_test",
    "operation_complete",
    "initialize",
    "set_AI_channel",
    "set_AI_range",
    "set_AI_sample_rate",
    "configure_AI_channel",
    "read_AI",
    "read_AI_scan",
    "quick_read",
    "read_data",
    "set_AO_channel",
    "set_AO_range",
    "set_AO_sample_rate",
    "configure_AO_channel",
    "write_AO",
    "write_waveform_scan",
    "stop_output",
    "set_DIO_channel",
    "set_DIO_mode",
    "configure_DO_channel",
    "configure_DI_channel",
    "write_DO",
    "read_DI",
    "set_input_mode",
    "close",
]


def test_base_daq_ranges_use_the_standard_list_of_tuples_shape():
    assert Daq.ai_range == [(None, None)]
    assert Daq.ao_range == [(None, None)]


def test_usb1208hs_one_driver_registers_all_three_models():
    assert USB1208HS.AUTODETECT_ID == [
        "USB-1208HS",
        "USB-1208HS-2AO",
        "USB-1208HS-4AO",
    ]


def test_usb1208hs_configures_ao_channels_from_idn():
    expected_channels = {
        "Measurement_Computing,USB-1208HS,s/n_unknown,ver_UL": [],
        "Measurement_Computing,USB-1208HS-2AO,s/n_unknown,ver_UL": [0, 1],
        "Measurement_Computing,USB-1208HS-4AO,s/n_unknown,ver_UL": [0, 1, 2, 3],
    }

    for identity, channels in expected_channels.items():
        daq = object.__new__(USB1208HS)
        daq._configure_model_capabilities(identity)
        assert daq.ao_channel == channels
        assert daq.ao_range == ([(-10.0, 10.0)] if channels else [])


@pytest.mark.parametrize("driver_class", [USB231, USB1208HS])
def test_daq_notebook_methods_are_implemented_by_both_drivers(driver_class):
    """The generic notebook must not resolve a required call to a Daq stub."""
    base_methods = {
        inspect.unwrap(getattr(Daq, method))
        for method in NOTEBOOK_DRIVER_METHODS
        if hasattr(Daq, method)
    }

    for method in NOTEBOOK_DRIVER_METHODS:
        implementation = inspect.unwrap(getattr(driver_class, method))
        assert implementation not in base_methods, (
            f"{driver_class.__name__}.{method} still resolves to a Daq stub"
        )


@pytest.mark.parametrize("driver_class", [USB231, USB1208HS])
def test_daq_range_normalization_uses_minimum_maximum_pairs(driver_class):
    assert driver_class._normalize_range((-10, 10)) == (-10.0, 10.0)
    with pytest.raises(
        ValueError, match=r"two-value \(minimum, maximum\) pair"
    ):
        driver_class._normalize_range(10)


@pytest.mark.parametrize(
    ("driver_class", "identity"),
    [
        (USB231, None),
        (USB1208HS, "Measurement_Computing,USB-1208HS,s/n_unknown,ver_UL"),
        (USB1208HS, "Measurement_Computing,USB-1208HS-2AO,s/n_unknown,ver_UL"),
        (USB1208HS, "Measurement_Computing,USB-1208HS-4AO,s/n_unknown,ver_UL"),
    ],
)
def test_notebook_range_configuration_is_shared_by_both_drivers(
    driver_class, identity
):
    """Exercise the notebook's range-selection/configuration pattern offline."""
    daq = object.__new__(driver_class)
    daq._ai_sample_rates = {}
    daq._ao_sample_rates = {}

    if driver_class is USB1208HS:
        daq._configure_model_capabilities(identity)
        daq._ai_mode = "se"
        daq.ai_channel = list(range(8))
        daq.ai_range = list(daq._AI_RANGES_BY_MODE["se"])
        daq._ai_ranges = {}

    ai_channel = daq.ai_channel[0] if daq.ai_channel else None
    if ai_channel is not None:
        ai_range = daq.ai_range[0]
        daq.configure_AI_channel(ai_channel, range=ai_range, sample_rate=1000)

    ao_channel = daq.ao_channel[0] if daq.ao_channel else None
    if ao_channel is not None:
        ao_range = daq.ao_range[0]
        daq.configure_AO_channel(ao_channel, range=ao_range, sample_rate=1000)


def test_generic_daq_notebook_is_model_independent_and_output_safe():
    notebook_path = ROOT / "src" / "piec" / "drivers" / "daq" / "daq_test.ipynb"
    notebook = json.loads(notebook_path.read_text(encoding="utf-8"))
    source = "\n".join(
        "".join(cell.get("source", [])) for cell in notebook["cells"]
    )

    assert "autodetect(verbose=True)" in source
    assert "USB231" not in source
    assert "daq.set_AI_channel(AI_CHANNEL)" in source
    assert "daq.configure_AI_channel(" in source
    assert "daq.read_AI_scan(" in source
    assert "daq.configure_AO_channel(" in source
    assert "daq.write_AO(AO_CHANNEL, 0.0)" in source
    assert "daq.output(" not in source
    assert "range=10" not in source
    assert "AI_RANGE = daq.ai_range[0]" in source
    assert "AO_RANGE = daq.ao_range[0]" in source
