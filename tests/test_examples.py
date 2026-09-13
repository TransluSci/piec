"""
Consolidated Tests for Package Imports and Published Developer Guide Examples.

Consolidates:
- Package and sub-module imports verification (test_imports.py)
- Measurement developer guide and documentation code-blocks (test_measurement_developer_guide.py)

Verifies:
- Top-level and driver/analysis/simulation submodules can be imported.
- Package version string is defined and non-empty.
- Published code examples in MEASUREMENT_DEVELOPER_GUIDE.md and adding_measurement.rst
  compile, execute, and remain synchronized with the measurement engine.
"""

from __future__ import annotations

from pathlib import Path
from queue import Empty
import re
import textwrap

import pytest

from piec.drivers.sourcemeter.virtual_sourcemeter import VirtualSourcemeter
from piec.measurement import SafetyStatus, read_measurement_csv

REPO_ROOT = Path(__file__).resolve().parents[1]
GUIDE = REPO_ROOT / "src/piec/measurement/MEASUREMENT_DEVELOPER_GUIDE.md"
BLOCKS = re.findall(r"```python\n(.*?)```", GUIDE.read_text(encoding="utf-8"), re.S)
EXAMPLE = next(block for block in BLOCKS if "__main__" in block)


# ==============================================================================
# Part 1: Package Imports and Sub-module Verification
# ==============================================================================

def test_import_piec():
    import piec


def test_version_string():
    """The package must have a non-empty version string."""
    import piec
    assert hasattr(piec, "__version__"), "piec.__version__ is missing"
    assert isinstance(piec.__version__, str)
    assert len(piec.__version__) > 0


def test_import_drivers():
    import piec.drivers


def test_import_analysis():
    import piec.analysis


def test_import_simulation():
    import piec.simulation


def test_import_virtual_awg():
    from piec.drivers.awg.virtual_awg import VirtualAwg


def test_import_virtual_scope():
    from piec.drivers.oscilloscope.virtual_oscilloscope import VirtualScope


def test_import_analysis_utilities():
    from piec.analysis.utilities import (
        create_measurement_filename,
        interpolate_sparse_to_dense,
        metadata_and_data_to_csv,
        standard_csv_to_metadata_and_data,
    )


def test_import_simulation_classes():
    from piec.simulation.fe_material import Dielectric, Ferroelectric, Resistor


# ==============================================================================
# Part 2: Measurement Developer Guide and Documentation Examples
# ==============================================================================

@pytest.fixture
def example():
    namespace = {"__name__": "guide_example"}
    exec(compile(EXAMPLE, str(GUIDE), "exec"), namespace)
    return namespace


def test_documented_blocks_compile_and_complete_example_runs():
    for block in BLOCKS:
        compile(block, str(GUIDE), "exec")
    rst = (REPO_ROOT / "docs/source/contributing/adding_measurement.rst").read_text(encoding="utf-8")
    for block in re.findall(r"\.\. code-block:: python\n\n(.*?)(?=\n\S|\Z)", rst, re.S):
        compile(textwrap.dedent(block), "adding_measurement.rst", "exec")
    exec(compile(EXAMPLE, str(GUIDE), "exec"), {"__name__": "__main__"})


@pytest.mark.parametrize("invalid", ["INVALID", None, True, 0, -1, float("nan"), float("inf")])
def test_invalid_compliance_rejected_before_hardware(example, monkeypatch, invalid):
    source = VirtualSourcemeter()
    measurement = example["StandardizedIvSweep"](source)

    def unexpected(*args, **kwargs):
        pytest.fail("Invalid options reached hardware")

    monkeypatch.setattr(source, "output", unexpected)
    with pytest.raises(ValueError, match="compliance_current"):
        measurement.run_experiment(save=False, options={"compliance_current": invalid})


def test_compliance_is_programmed(example):
    source = VirtualSourcemeter()
    measurement = example["StandardizedIvSweep"](source)
    measurement.run_experiment(save=False, options={"compliance_current": 0.005})
    assert source.state["current_compliance"] == 0.005


@pytest.mark.parametrize("session", [False, True])
@pytest.mark.parametrize("failure", ["read", "callback"])
def test_failed_capture_retains_partial_csv(example, tmp_path, monkeypatch, session, failure):
    source = VirtualSourcemeter()
    measurement = example["StandardizedIvSweep"](source, output_dir=tmp_path)
    original = source.get_current
    calls = []

    def read(*args, **kwargs):
        calls.append(1)
        if failure == "read" and len(calls) == 3:
            raise RuntimeError("read failed")
        return original(*args, **kwargs)

    monkeypatch.setattr(source, "get_current", read)

    def callback(snapshot):
        if failure == "callback" and snapshot.completed_steps == 2:
            raise RuntimeError("callback failed")

    with pytest.raises(RuntimeError, match=f"{failure} failed"):
        if session:
            with measurement.session(save=True, save_partial=True) as scope:
                scope.configure_instruments()
                scope.capture_data(on_update=callback)
        else:
            measurement.run_experiment(save=True, save_partial=True, on_update=callback)
    assert len(measurement.raw_data) == 2
    assert measurement.filename is None
    metadata, data, _ = read_measurement_csv(measurement.partial_filename)
    assert len(data) == 2
    assert metadata["outcome"] == "FAILED"
    assert measurement.safety_status == SafetyStatus.SAFE


def test_standalone_safing_does_not_claim_unavailable_readback():
    block = next(block for block in BLOCKS if 'name="sourcemeter_disable"' in block)
    namespace = {}
    exec(compile(block, str(GUIDE), "exec"), namespace)

    class Holder:
        sourcemeter = VirtualSourcemeter()

    report = namespace["_safe_shutdown"](Holder())
    assert report.status == SafetyStatus.SAFE
    assert not report.readback_verified
    assert all(not action.readback_verified for action in report.actions)


def test_display_consumer_handles_timeout(example):
    class Queue:
        def get(self, **kwargs):
            runner.is_worker_alive = False
            raise Empty

    class Runner:
        is_worker_alive = True
        display_queue = Queue()

    runner = Runner()
    example["consume_live_display"](runner)


def test_acquisition_error_remains_primary_if_shutdown_fails(example, monkeypatch):
    source = VirtualSourcemeter()
    measurement = example["StandardizedIvSweep"](source)
    original_output = source.output
    disables = []

    def output(channel=1, on=True):
        if not on:
            disables.append(1)
            if len(disables) == 2:
                raise OSError("shutdown failed")
        return original_output(channel=channel, on=on)

    monkeypatch.setattr(source, "output", output)

    def fail(snapshot):
        raise RuntimeError("callback failed")

    with pytest.raises(RuntimeError, match="callback failed"):
        measurement.run_experiment(save=False, on_update=fail)
    assert len(measurement.raw_data) == 1
    assert measurement.safety_status == SafetyStatus.UNSAFE
    assert source.state["source_voltage"] == 0.0
