# PIEC Measurement Developer Guide

This guide is the normative reference and implementation guide for authoring
measurement classes, setup adapters, background runners, persistence pipelines,
and GUI integrations in the `piec` library.

New and migrated measurements use `piec.measurement.BaseMeasurement` for lifecycle,
execution ownership, persistence, and display/control events. Existing measurement
families are being migrated in the checkpoints listed in
`MEASUREMENT_STANDARDIZATION_PLAN.md`; this guide defines their target contract.

---

## 1. The Architectural Layering

A PIEC experiment is structured in five cooperating layers with strict boundaries:

```
┌─────────────────────────────────────────────────────────────┐
│                       UI / Notebook                         │
│  (Collects user settings, visualizes snapshots, sends stops) │
└──────────────────────────────┬──────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────┐
│                      MeasurementRunner                      │
│  (Synchronous reservation, non-daemon thread, close control) │
└──────────────────────────────┬──────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────┐
│              Concrete Measurement Subclass                  │
│  (Inherits BaseMeasurement: sequence hooks, safing policy)  │
└──────────────────────────────┬──────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────┐
│                 Setup Adapters & Calibration                │
│  (e.g., WaveformReader, role adapters, coordinate transforms)│
└──────────────────────────────┬──────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────┐
│                      Level 2 Drivers                        │
│  (Sourcemeter, DMM, AWG, Oscilloscope, Stepper, Lock-in)    │
└─────────────────────────────────────────────────────────────┘
```

### Layer Responsibilities

1. **Measurement Class (`src/piec/measurement/`)**:
   Inherits from `BaseMeasurement`. Coordinates the experimental sequence through
   protected hooks (`_configure_instruments`, `_capture_data`, `_safe_shutdown`,
   `_analyze_data`, `_stage_side_artifacts`). It owns **no UI widgets**, opens no
   hard-coded VISA connections, and never overrides the public lifecycle wrappers.
2. **Analysis Functions (`src/piec/analysis/`)**:
   Pure mathematical, physical, or fitting routines. Analysis functions accept
   tabular data (`pd.DataFrame`) and explicit parameters; they return computed
   results. They have no instrument or GUI dependencies and can be run completely
   offline.
3. **Setup Adapters (`src/piec/measurement/adapters/`)**:
   Bridge instrument-level driver dialects to measurement-level contracts (for
   example, `WaveformReader` normalizes various oscilloscope table dialects into
   standard lowercase `time` and `voltage` columns with declared units).
4. **Instrument Drivers (`src/piec/drivers/`)**:
   Implement concrete instrument communication protocols (SCPI, DDC, vendor SDKs)
   or simulation mocks (`VirtualSourcemeter`, `VirtualDMM`, `VirtualAwg`, `VirtualScope`).
   Drivers own communication sessions and channel-first method signatures.
5. **Background Runner (`MeasurementRunner`)**:
   Coordinates asynchronous execution, worker thread lifecycle, reservation tokens,
   and window-close safety. The runner owns **no hardware I/O** and **no scientific code**.

---

## 2. Base Class and Subclassing Rules

Every concrete measurement MUST inherit from `piec.measurement.BaseMeasurement`.

### 2.1 Constructor Rules

1. **Dependency Injection**:
   Instruments and setup adapters are injected into `__init__` as arguments.
   Never open hardware connections, detect addresses, or create output directories
   inside the constructor.
2. **Keyword-Only Settings**:
   Experimental parameters (ranges, step counts, compliance, frequencies) MUST be
   explicit keyword arguments with clear type hints, default values, and docstrings.
3. **No Hardware I/O in Constructor**:
   Instantiating a measurement object must be completely side-effect free.
   No communication packets may be sent to instruments during `__init__`.
4. **Explicit Persistence Configuration**:
   When data saving is intended (`save=True`), pass `output_dir`, `measurement_schema`,
   and `column_units` to `super().__init__()`.
   - `output_dir`: Target directory for saved CSV files and side artifacts.
   - `measurement_schema`: Standard schema identifier (e.g. `"iv_sweep"`, `"moke"`,
     `"discrete_waveform"`, `"hysteresis"`, `"three_pulse_pund"`, `"amr"`).
   - `column_units`: Dictionary mapping analyzed column names to canonical unit strings
     (e.g. `{"voltage": "V", "current": "A"}`). Use `None` for unitless quantities.
   - `raw_column_units` (optional): Dictionary mapping raw acquisition columns when
     they differ from the analyzed output (e.g., raw scope traces versus derived hysteresis).
   - `metadata` (optional): Free-form dictionary of scalar run metadata (e.g. sample
     name, operator, batch ID).
5. **Transient / In-Memory Runs**:
   If `save=False` is used, persistence arguments are optional (`output_dir=None`).
   The engine will not create directories or attempt to write files. The engine
   never reports a virtual path as a successful save.
6. **Capability Flags**:
   Set `supports_pause = True` on the subclass only if the measurement family implements
   cooperative pause/resume (e.g. AMR angle sweeps). By default, `supports_pause` is `False`.

```python
from pathlib import Path
from typing import Any, Mapping, Optional, Union
from piec.measurement import BaseMeasurement

class MyMeasurement(BaseMeasurement):
    supports_pause: bool = False

    def __init__(
        self,
        sourcemeter,
        *,
        voltage_start: float = 0.0,
        voltage_stop: float = 1.0,
        points: int = 101,
        output_dir: Optional[Union[str, Path]] = None,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> None:
        self.sourcemeter = sourcemeter
        self.voltage_start = float(voltage_start)
        self.voltage_stop = float(voltage_stop)
        self.points = int(points)

        super().__init__(
            output_dir=output_dir,
            measurement_schema="iv_sweep",
            column_units={"voltage": "V", "current": "A"},
            metadata=metadata,
        )
```

---

## 3. The Standard Lifecycle

`BaseMeasurement` manages the complete lifecycle state machine:

```
 IDLE
   │ (reserve)
   ▼
STARTING ────────(stop before start)───────► ABORTED
   │
   ▼
CONFIGURING ──(error)──► SAFING ──────────► FAILED
   │                       ▲
   ▼                       │
RUNNING ────(stop/error)───┤
   │                       │
   ▼                       │
SAFING ────────────────────┘
   │ (safing ok)
   ▼
ANALYZING ──(error)────────────────────────► FAILED
   │
   ▼
SAVING ─────(error)────────────────────────► FAILED
   │
   ▼
COMPLETED
```

### 3.1 Public Lifecycle Wrappers (DO NOT OVERRIDE)

`BaseMeasurement` provides the public API. **Subclasses MUST NOT override these methods:**

- `run_experiment(*, on_update=None, save=True, save_partial=None, options=None) -> pd.DataFrame`
  Executes the canonical full run: reservation -> Stop-before-start check ->
  configuration -> acquisition -> safing -> analysis -> publication -> terminal record.
  Returns the analyzed DataFrame, or raw partial data on cooperative abort.
  Failures re-raise the original error; retained data remains available on the measurement.
- `session(*, save=False, save_partial=None, options=None) -> MeasurementSession`
  Context manager for piecewise notebook workflows. Holds a single execution lease
  and guarantees safe shutdown on block exit.
- `configure_instruments(*, options=None) -> None`
  Prepares instruments. If called inside an active session, configures within the session lease;
  if called standalone, executes a transient configuration and safing cycle.
- `capture_data(*, on_update=None, options=None) -> pd.DataFrame`
  Acquires data within an active session.
- `safe_shutdown() -> SafetyReport`
  Executes shutdown as the owner or under an idle lease. A call from another thread
  during an active run requests Stop and raises a deferred-shutdown RuntimeError;
  that caller does not issue hardware commands.
- `request_stop() -> None`
  Signals cooperative stop. Acquisition loops checking `self._coordinator.is_stop_requested`
  break cleanly and transition to safing and partial preservation.
- `request_pause(paused=True) -> None`
  Signals cooperative pause if `supports_pause` is enabled; otherwise raises `NotImplementedError`.
- `snapshot() -> MeasurementSnapshot`
  Returns a thread-safe, mutation-isolated copy of the current measurement state and views.
- `publish_snapshot(views, *, message="", completed_steps=0, total_steps=None, **extra) -> MeasurementSnapshot`
  Dispatches a fresh snapshot to registered bounded display queues and listeners.

### 3.2 Protected Subclass Hooks (OVERRIDE THESE)

Subclasses implement their experimental logic by overriding the following protected hooks:

#### `_validate_options(self, options: Optional[Mapping[str, Any]]) -> None`
Validates run-specific options passed via `options={...}`. Reject unknown keys or
illegal types early before acquiring a reservation or touching hardware.

#### `_configure_instruments(self, request: RunRequest) -> None`
Configure instrument operating modes, ranges, timings, and trigger routes.
**Hardware outputs MUST remain disabled during this phase.**

#### `_capture_data(self, request: RunRequest, on_update: Optional[Callable[[Any], None]]) -> pd.DataFrame`
Executes the main acquisition loop and returns the raw captured data as a `pd.DataFrame`.
- Check `self._coordinator.is_stop_requested` periodically to support cooperative cancellation.
- If streaming to a UI, call `self.publish_snapshot(...)` or invoke `on_update(...)`.
- Preserve collected raw rows in `self._raw_data` in a `finally` block, including
  when instrument reads or callbacks raise. The engine invokes `_safe_shutdown`
  afterward; keep hardware cleanup there so a cleanup error cannot replace the
  original acquisition error.

#### `_safe_shutdown(self, recorder: Optional[ShutdownAttemptRecorder] = None) -> Union[SafetyReport, Sequence[Any]]`
De-energizes stimuli, disables power outputs, ramps magnets to zero, and stops motion.
- **Guarantee**: After configuration/acquisition is entered, the engine invokes this
  hook on completion, stop, fault, and Python interrupts. Stop-before-start and
  rejected preflight perform zero hardware I/O and do not invoke the hook.
- **Safety Policy**: Record each shutdown action using `recorder.record_action(name, fn, readback_fn)`
  or `self.record_shutdown_action(name, fn, readback_fn)`.
- **Never Close Connections**: Safing de-energizes hardware; it must never close VISA
  sessions or network transports. Communications must remain open for diagnostics.

#### `_analyze_data(self, raw_data: pd.DataFrame, request: RunRequest) -> pd.DataFrame`
Performs post-acquisition scientific calculations on raw data (e.g. background subtraction,
averaging, polarization calculation). Returns the final analyzed `pd.DataFrame`.

#### `_stage_side_artifacts(self, data: pd.DataFrame, request: RunRequest, reservation: CandidateReservation) -> Sequence[Tuple[Path, Path]]`
Optional hook for measurements that produce companion files (such as PNG plots or summary logs).
- Returns a sequence of `(staged_path, target_path)` tuples.
- Targets must reside in `reservation.candidate_path.parent` and start with
  `f"{reservation.candidate_basename}_"`.
- Stage companion files to hidden temporary files using `create_staging_file`.
- Side artifacts are published atomically *before* the primary CSV file.

---

## 4. Hardware Safety and Cleanup Guarantees

Hardware safety is non-negotiable. Software safing operates under these strict rules:

1. **Guaranteed Execution**:
   Safing always runs after configuration or acquisition, regardless of whether
   the run succeeded, was stopped, failed with an exception, or received a `KeyboardInterrupt`.
2. **Attempt-All Recording**:
   Using `ShutdownAttemptRecorder`, every registered shutdown action is attempted.
   If instrument 1 fails to respond or raises an error, instrument 2 and 3 are still
   safed.
3. **Readback Verification**:
   When supported by the driver, provide a `readback_fn` to confirm that output state
   is verified zero/off.
4. **Safety Status Propagation**:
   - If all safing actions succeed: `SafetyStatus.SAFE`.
   - If no hardware was configured before an abort: `SafetyStatus.NOT_NEEDED`.
   - If any safing action fails: `SafetyStatus.UNSAFE`.
5. **Alert Emission and Error Precedence**:
   If a shutdown action fails, `BaseMeasurement` immediately emits a `SafetyAlertEvent`
   to all control queues and listeners.
   - If safing fails after an acquisition error, the primary error is preserved and the
     safing error is appended to `secondary_errors`.
   - If acquisition was clean but safing failed, `HardwareSafetyError` is raised.

### Implementing `_safe_shutdown`

Only supply `readback_fn` when a setup provides a verified, supported readback API.
Do not infer support with `hasattr`: a driver may supply optional no-op methods.
A missing/unknown reading must never be coerced into successful verification.
The example below records command success without claiming readback verification.

```python
from typing import Optional
from piec.measurement import SafetyReport, SafetyStatus, ShutdownAttemptRecorder

def _safe_shutdown(self, recorder: Optional[ShutdownAttemptRecorder] = None) -> SafetyReport:
    if recorder is None:
        recorder = ShutdownAttemptRecorder()

    # Attempt 1: Disable output. The shared sourcemeter API has no output readback.
    recorder.record_action(
        name="sourcemeter_disable",
        action_fn=lambda: self.sourcemeter.output(channel=1, on=False),
    )

    # Attempt 2: Reset voltage to zero
    recorder.record_action(
        name="sourcemeter_zero_volts",
        action_fn=lambda: self.sourcemeter.set_source_voltage(channel=1, voltage=0.0),
    )

    return recorder.build_report()
```

---

## 5. DataFrame and Units Contract

PIEC enforces strict data column naming and unit metadata rules across all measurement families:

### 5.1 Plain Lowercase Column Names
Column names MUST be plain, lowercase, descriptive identifiers without unit decorations:
- **Correct**: `voltage`, `current`, `time`, `field`, `polarization`, `angle`, `x`, `y`
- **Forbidden**: `Voltage (V)`, `voltage_V`, `I (mA)`, `time_s`, `Current [A]`

### 5.2 Units in Metadata (`column_units_json`)
Units are declared via the `column_units` dictionary and serialized in metadata as
sorted compact JSON in the `column_units_json` field:

```python
column_units = {
    "voltage": "V",
    "current": "A",
    "cycle": None,  # Unitless quantity serialized as JSON null
}
```

Serialization produces:
`{"current":"A","cycle":null,"voltage":"V"}`

### 5.3 Raw vs. Analyzed Data
- `self.raw_data`: Stores the complete, un-decimated raw DataFrame returned by `_capture_data`.
- `self.data`: Stores the analyzed DataFrame produced by `_analyze_data`. On aborted
  or failed runs, `self.data` holds the raw partial data captured up to the interruption.

---

## 6. Execution Ownership and Concurrency

To protect physical hardware from competing or corrupted commands:

1. **Single Execution Owner**:
   Only one thread may hold the execution lease at any time. Any concurrent attempt
   to call `run_experiment()`, enter a `session()`, or invoke hardware methods raises
   `ConcurrentRunError`.
2. **Synchronous Reservation**:
   Every run begins by synchronously generating a unique `run_id` (UUID) and monotonic
   `generation` counter wrapped in a `ReservationToken`.
3. **Stop-Before-Start**:
   If a user requests cancellation before configuration begins, the engine transitions
   immediately to `ABORTED` with zero hardware I/O and safety `NOT_NEEDED`.
4. **Piecewise Sessions**:
   Notebook users can step through experiment phases while holding a single lease:

```python
with measurement.session(save=False) as sess:
    sess.configure_instruments()
    data = sess.capture_data()
    # On exiting the with block, safe_shutdown() runs automatically
```

---

## 7. Background Execution and GUI Integration

Desktop applications and GUIs must never run hardware loops on the main UI thread.
Use `MeasurementRunner` to manage worker threads safely.

### 7.1 `MeasurementRunner` Architecture

- **Synchronous Caller-Thread Reservation**: `runner.start(...)` validates options
  and claims the reservation token *before* spawning the thread. If options are invalid
  or another run is active, `start()` raises immediately in the caller thread.
- **Non-Daemon Worker Thread**: The worker is spawned with `daemon=False`. This ensures
  the Python process cannot terminate abruptly while hardware outputs are energized.
- **Worker Start Failure Recovery**: If the OS fails to spawn the thread, the runner
  cleanly finalizes the reservation as `FAILED` with safety `NOT_NEEDED`.

### 7.2 Two Distinct Event Paths

To avoid UI stutter and prevent unbounded memory growth during high-rate acquisition:

1. **`DisplayQueue` (Bounded, Coalescing)**:
   - Fixed capacity (default `maxsize=1`).
   - Uses a **drop-oldest** policy on saturation: if the UI thread is busy painting,
     intermediate frames are dropped, and the UI always receives the latest snapshot.
   - Carries `MeasurementSnapshot` instances.
2. **`ControlQueue` (Unbounded, Lossless FIFO)**:
   - Delivers every state change, safety alert, and completion event in strict sequence.
   - Carries `StateChangeEvent`, `SafetyAlertEvent`, and `TerminalEvent`.
   - Never drops events.

### 7.3 Application and Window Close Coordination

When the user clicks the window close box ("X"), the UI MUST coordinate with the runner
before exiting:

```python
def on_window_close():
    # Signal shutdown
    runner.request_close()

    # Poll or wait for worker exit and safety confirmation
    status = runner.check_close_status()
    if status.can_close:
        root.destroy()
    else:
        # Check if hardware is unsafe
        if status.safety_status == SafetyStatus.UNSAFE:
            show_error_dialog("HARDWARE UNSAFE: " + status.reason)
        # Re-check via root.after
        root.after(100, on_window_close)
```

`runner.can_close()` returns `True` only when:
1. The background worker thread has completely terminated.
2. The measurement is idle or terminal (`COMPLETED`, `ABORTED`, `FAILED`).
3. Hardware safety is confirmed (`SAFE` or `NOT_NEEDED`).
If safety is `UNSAFE`, closing remains blocked. There is no acknowledgment override
in `MeasurementRunner`; after resolving the hardware issue, an owner/idle shutdown
retry must establish `SAFE` or `NOT_NEEDED` before normal close is permitted.

---

## 8. Persistence, File Format, and Artifact Bundles

### 8.1 File Format
PIEC measurement files use a standardized CSV layout:
- **Row 1**: Metadata column headers.
- **Row 2**: Metadata values (including `measurement_schema`, `run_id`, `outcome`, `partial`, `column_units_json`).
- **Row 3**: Single empty line (separator).
- **Row 4**: Data table headers (plain lowercase names).
- **Rows 5+**: Numerical data rows.

All files are written through a single UTF-8 file handle with explicit `flush()` and `os.fsync()`.

### 8.2 Candidate Reservation and Atomic Publication
To prevent data loss and accidental overwrite:
1. **Candidate Reservation (`reserve_candidate_filename`)**:
   Claims `{index:04d}_{schema}.csv` by creating an exclusive hidden reservation marker
   (`.{index:04d}_{schema}.csv.res`) containing the owner UUID. It **never** reserves
   by creating an empty completed-looking CSV.
2. **Atomic Staging and Publication (`atomic_publish_no_replace`)**:
   Data is written to a hidden staging file in the target directory (`tempfile.mkstemp()`).
   Upon successful write and fsync, the staging file is published atomically to the target
   path using Windows `os.rename` without replacement, or POSIX
   `renameat2(RENAME_NOREPLACE)` / hard-link fallback. The implementation does not
   request `MOVEFILE_WRITE_THROUGH` or promise power-loss durability on every filesystem.
3. **No-Replace Invariant**:
   If the target file already exists, publication raises `FileExistsError` and preserves
   the staging file for manual data recovery. Existing datasets are never silently overwritten.
4. **Artifact Bundles (`publish_artifact_bundle`)**:
   For measurements producing side artifacts (e.g. plot images):
   - Side artifacts are published **first**.
   - The completed CSV is published **last** as the completion marker.
   - If publication fails halfway, only owned published artifacts are rolled back, and
     all staging files are preserved for recovery.

### 8.3 Incomplete Runs and Partial Checkpoints
- Completed runs assign `self.filename` **only after** the final CSV is published.
- Aborted or failed runs set `self.partial_filename` only if partial saving is requested,
  nonempty raw data exists, and publication succeeds. They never assign `self.filename`.
  Abort defaults to partial saving when `save=True`; failure requires `save_partial=True`.
- Checkpoints use the grammar: `{candidate_basename}.{run_id}.partial.csv`.
- The helper `write_partial_csv` allows intentional updates to an owned checkpoint during
  long runs. Automatic periodic checkpoint scheduling is not built into the base engine;
  checkpoints are written intentionally by the measurement procedure.

### 8.4 Failure Recovery
If publication or disk sync fails:
- In-memory data is preserved on `self.raw_data` and `self.data`.
- Intact staging file paths are attached to the exception and exposed via
  `self.recoverable_staging_paths` and `RunRecord.metadata["recoverable_staging_paths"]`.

---

## 9. Virtual Operation and Simulation

Every measurement workflow should be fully testable without physical instruments.

- **Identical Interface**: Virtual drivers (`VirtualSourcemeter`, `VirtualDMM`,
  `VirtualAwg`, `VirtualScope`) must satisfy the exact Level 2 driver interface.
- **Dependency Injection**: Pass the virtual driver to the measurement constructor:

```python
from piec.drivers.sourcemeter.virtual_sourcemeter import VirtualSourcemeter

sourcemeter = VirtualSourcemeter()
measurement = MyMeasurement(sourcemeter, output_dir="data")
```

- **No Simulation Branches in Measurement Code**: Never write `if self.is_virtual:`
  inside measurement procedures. The measurement code simply commands the instrument.

---

## 10. Complete Executable Example

Below is a complete, runnable example demonstrating a standardized IV sweep measurement,
including full runs, piecewise sessions, background runner execution, side artifact bundles,
and file reading.

```python
"""
Executable example of a standardized PIEC measurement class and workflows.
"""

from __future__ import annotations

import os
import math
from numbers import Real
from queue import Empty
from pathlib import Path
import tempfile
import time
from typing import Any, Mapping, Optional, Sequence, Tuple, Union
import pandas as pd

from piec.drivers.sourcemeter.virtual_sourcemeter import VirtualSourcemeter
from piec.measurement import (
    BaseMeasurement,
    MeasurementRunner,
    SafetyReport,
    SafetyStatus,
    ShutdownAttemptRecorder,
    read_measurement_csv,
)
from piec.measurement.contracts import RunRequest
from piec.measurement.persistence import CandidateReservation, create_staging_file


class StandardizedIvSweep(BaseMeasurement):
    """
    Standardized IV sweep measurement class.
    """

    supports_pause: bool = False

    def __init__(
        self,
        sourcemeter: VirtualSourcemeter,
        *,
        voltage_start: float = 0.0,
        voltage_stop: float = 1.0,
        points: int = 11,
        output_dir: Optional[Union[str, Path]] = None,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> None:
        self.sourcemeter = sourcemeter
        self.voltage_start = float(voltage_start)
        self.voltage_stop = float(voltage_stop)
        self.points = int(points)

        super().__init__(
            output_dir=output_dir,
            measurement_schema="iv_sweep",
            column_units={"voltage": "V", "current": "A"},
            metadata=metadata,
        )

    def _validate_options(self, options: Optional[Mapping[str, Any]]) -> None:
        super()._validate_options(options)
        if options is not None:
            allowed = {"compliance_current"}
            unknown = set(options.keys()) - allowed
            if unknown:
                raise ValueError(f"Unknown run options: {unknown}")
            compliance = options.get("compliance_current", 0.01)
            if (isinstance(compliance, bool) or not isinstance(compliance, Real)
                    or not math.isfinite(compliance) or compliance <= 0):
                raise ValueError("compliance_current must be a finite positive number in A")

    def _configure_instruments(self, request: RunRequest) -> None:
        # Prepare hardware with outputs strictly off
        self.sourcemeter.output(channel=1, on=False)
        self.sourcemeter.configure_voltage_source(
            channel=1, voltage=self.voltage_start,
            current_compliance=(request.options or {}).get("compliance_current", 0.01),
        )

    def _capture_data(
        self,
        request: RunRequest,
        on_update: Optional[Any] = None,
    ) -> pd.DataFrame:
        voltages = []
        currents = []

        try:
            self.sourcemeter.output(channel=1, on=True)
            step = (self.voltage_stop - self.voltage_start) / max(1, self.points - 1)
            for i in range(self.points):
                # Check for cooperative cancellation
                if self._coordinator.is_stop_requested:
                    break

                v = self.voltage_start + i * step
                self.sourcemeter.set_source_voltage(channel=1, voltage=v)
                curr = self.sourcemeter.get_current(channel=1)

                voltages.append(v)
                currents.append(curr)

                # Publish bounded live snapshot for GUI
                live_df = pd.DataFrame({"voltage": voltages, "current": currents})
                snapshot = self.publish_snapshot(
                    views={"raw_window": live_df.tail(100)},
                    completed_steps=i + 1,
                    total_steps=self.points,
                )

                if on_update is not None:
                    on_update(snapshot)
        finally:
            # Keep completed samples even when a read, callback, or interrupt fails.
            # The engine performs attempt-all safing and preserves the primary error.
            self._raw_data = pd.DataFrame({"voltage": voltages, "current": currents})

        return self._raw_data.copy()

    def _safe_shutdown(
        self, recorder: Optional[ShutdownAttemptRecorder] = None
    ) -> SafetyReport:
        if recorder is None:
            recorder = ShutdownAttemptRecorder()

        # Action 1: Turn off sourcemeter output
        recorder.record_action(
            name="sourcemeter_output_off",
            action_fn=lambda: self.sourcemeter.output(channel=1, on=False),
        )

        # Action 2: Reset voltage to 0 V
        recorder.record_action(
            name="sourcemeter_zero_voltage",
            action_fn=lambda: self.sourcemeter.set_source_voltage(channel=1, voltage=0.0),
        )

        return recorder.build_report()

    def _analyze_data(
        self, raw_data: pd.DataFrame, request: RunRequest
    ) -> pd.DataFrame:
        # Example analysis: compute resistance or preserve clean numeric table
        analyzed = raw_data.copy()
        return analyzed

    def _stage_side_artifacts(
        self,
        data: pd.DataFrame,
        request: RunRequest,
        reservation: CandidateReservation,
    ) -> Sequence[Tuple[Path, Path]]:
        if not request.save:
            return ()

        # Companion artifact staged under reserved basename prefix
        dest_dir = reservation.candidate_path.parent
        target_path = dest_dir / f"{reservation.candidate_basename}_summary.txt"

        fd, staging_path = create_staging_file(
            dest_dir, prefix=f".{reservation.run_id}-summary-"
        )
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(f"Points captured: {len(data)}\n")

        return [(staging_path, target_path)]


def consume_live_display(runner):
    while runner.is_worker_alive:
        try:
            snap = runner.display_queue.get(timeout=0.1)
        except Empty:
            continue
        print(f"Progress: {snap.completed_steps}/{snap.total_steps}")
        time.sleep(0.02)


# ============================================================================
# Execution Demonstrations
# ============================================================================

if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as output_directory:
        sm = VirtualSourcemeter()
        meas = StandardizedIvSweep(
            sm,
            voltage_start=-1.0,
            voltage_stop=1.0,
            points=11,
            output_dir=output_directory,
            metadata={"sample": "Sample-G12", "operator": "Scientist"},
        )

        # --------------------------------------------------------------------
        # 1. Synchronous Full Run
        # --------------------------------------------------------------------
        print("--- 1. Synchronous Run ---")
        df = meas.run_experiment(save=True)
        print(f"Run completed. Rows: {len(df)}")
        print(f"Authoritative published file: {meas.filename}")

        # Read back saved file
        metadata, loaded_df, units = read_measurement_csv(meas.filename)
        print(f"Loaded schema: {metadata['measurement_schema']}")
        print(f"Units mapping: {units}")

        # --------------------------------------------------------------------
        # 2. Piecewise Execution Session
        # --------------------------------------------------------------------
        print("\n--- 2. Piecewise Session ---")
        with meas.session(save=False) as sess:
            sess.configure_instruments()
            sess_df = sess.capture_data()
            print(f"Session captured rows: {len(sess_df)}")
        # Safe shutdown executed automatically on exiting the context manager

        # --------------------------------------------------------------------
        # 3. Asynchronous Execution via MeasurementRunner
        # --------------------------------------------------------------------
        print("\n--- 3. Background MeasurementRunner ---")
        runner = MeasurementRunner(meas)
        token = runner.start(save=False)
        print(f"Worker launched with run ID: {token.run_id}")

        # Queue timeout means no new frame yet, not a measurement failure.
        consume_live_display(runner)

        # Coordinate close safely
        runner.request_close()
        status = runner.check_close_status()
        assert status.can_close, f"Cannot close: {status.reason}"
        print(f"Close coordination confirmed: {status.reason}")
        print("All workflows executed successfully!")
```

---

## 11. Developer Review Checklist

Before opening a pull request for a new or updated measurement family, verify:

- [ ] **Inheritance**: Subclass inherits directly from `BaseMeasurement`.
- [ ] **Public Wrappers**: Does not override `run_experiment`, `session`, `configure_instruments`, `capture_data`, `safe_shutdown`, `request_stop`, `request_pause`, or `snapshot`.
- [ ] **Constructor**: Performs NO hardware I/O, VISA queries, or filesystem creation. Instruments are injected; settings are keyword-only.
- [ ] **Columns and Units**: Column names are plain lowercase strings without units. All units are declared in `column_units` dictionary (or `None` for unitless fields).
- [ ] **Hardware Safing**: `_safe_shutdown` attempts ALL cleanup actions via `ShutdownAttemptRecorder` or `record_shutdown_action`. Outputs are de-energized; connections are NOT closed.
- [ ] **Cancellation**: `_capture_data` checks `self._coordinator.is_stop_requested` and retains partial raw data in a `finally` block. The engine owns attempt-all safing.
- [ ] **Side Artifacts**: If plots are produced, they are staged via `_stage_side_artifacts` with targets matching `f"{reservation.candidate_basename}_*"` and staged to hidden temporary files.
- [ ] **Persistence**: Successful runs set `self.filename`; incomplete runs set `self.partial_filename`. The standard CSV reads back cleanly via `read_measurement_csv`.
- [ ] **Virtual Operation**: Works with virtual drivers (`VirtualSourcemeter`, `VirtualDMM`, etc.) without branching on `if virtual:` in measurement methods.
- [ ] **Runner & GUI**: Desktop GUIs use `MeasurementRunner`, consume snapshots from `display_queue`, and coordinate window closing via `can_close()`.
- [ ] **Tests**: Includes unit tests covering constructor validation, configuration order, acquisition, safing on failure, stop-before-start, and golden output comparison.
