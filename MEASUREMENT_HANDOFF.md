# Measurement standardization handoff

Continue on `measuremnt-standarization`. Checkpoint 20b is complete. Checkpoint 17
physical validation remains explicitly **PENDING**. Next is
**checkpoint 20c only: PUND integration and consumers**, following the
measurement standardization plan. Validate and commit checkpoint 20c separately.

## Checkpoint 20b Hysteresis integration and consumers

- **BaseMeasurement Lifecycle**: `HysteresisLoop` in `piec.measurement.discrete_waveform` subclasses `DiscreteWaveform` and `BaseMeasurement`, implementing the shared lifecycle hooks: `_validate_options`, `configure_awg` (arbitrary waveform generation), `_analyze_data` (in-memory `process_hysteresis`), and `_stage_side_artifacts`.
- **Target Schema & Units**: Adheres to schema `hysteresis` v1 with plain lowercase columns `['time', 'voltage', 'current', 'polarization', 'applied_voltage']` and canonical JSON metadata units `{'time': 's', 'voltage': 'V', 'current': 'A', 'polarization': 'uC/cm^2', 'applied_voltage': 'V'}`.
- **In-Memory Scientific Processing**: Replaced file-based post-processing with in-memory execution via `process_hysteresis(raw_df, metadata, ...)`. Returns enriched DataFrame and schema v1 metadata directly.
- **Multi-Artifact Publication**: Staged side artifacts (`_PV.png`, `_IV.png`, `_trace.png`) are generated via `create_staging_file` and published atomically alongside the CSV when `save=True` and `save_plots=True`. Plots are strictly suppressed when `save=False` or `save_plots=False`.
- **Legacy Paths Removed**: Fully removed HysteresisLoop bypass paths (`apply_and_capture_waveform`, `save_waveform`, `analyze`, `save_dir`, `_update_notes`).
- **File Bridge Retired**: Removed private file bridge `_process_raw_hyst_file` from `piec.analysis.hysteresis`. Kept only the PUND bridge (`_process_raw_3pp_file`) needed until 20c.
- **Consumer Updates**: Updated `FE_testing_GUI.py`, `tests/test_measurement_pipeline.py`, `tests/test_measurement_fe_pund_compatibility.py`, `README.md`, docs, and notebooks (`example_hysteresis.ipynb`, `FE_testing.ipynb`) to use `output_dir` and handle plain target column names.
- **Validation**: Dedicated test suite `tests/test_measurement_hysteresis.py` added with 12 tests covering lifecycle, zero constructor I/O, parameter validation, plot artifact generation and suppression, cooperative cancellation, safe shutdown, and runner integration.
- **Physical Validation**: Hardware testing was not performed; Checkpoint 17 physical validation remains explicitly **PENDING**.
- **Next Step**: Stop after checkpoint 20b. Proceed with **checkpoint 20c only: PUND integration and consumers** once authorized.

## Checkpoint 20a DiscreteWaveform base acquisition and consumers

- **BaseMeasurement Lifecycle**: `DiscreteWaveform` in `piec.measurement.discrete_waveform` subclasses `BaseMeasurement`, implementing `run_experiment(*, on_update=None, save=True, save_partial=None, options=None) -> pd.DataFrame`, `configure_instruments()`, `capture_data(*, on_update=None)`, `session()`, `safe_shutdown()`, `request_stop()`, `snapshot()`, and `request_pause()`.
- **Target Schema & Units**: Adheres to schema `discrete_waveform` v1 with strictly plain columns `['time', 'voltage']` and canonical declared units `{'time': 's', 'voltage': 'V'}`. Metadata fields include standard provenance, run ID, and instrument identity strings.
- **Zero Constructor I/O**: Positional dependencies `awg`, `osc`; all settings (`v_div`, `voltage_channel`, `length`, `osc_channel`, `output_dir`, `metadata`) are keyword-only. No hardware communication occurs in `__init__`; identification and parameter writes occur on the worker thread in `_configure_instruments`.
- **Strict Trigger Sequence**: `_capture_data` enforces hardware trigger order: (1) arm oscilloscope (`osc.arm()`), (2) enable AWG output on configured channel (`awg.output(channel=..., on=True)`), (3) fire AWG trigger (`awg.output_trigger()`).
- **WaveformReader Adapter**: Uses `WaveformReader` setup adapter to retrieve and validate oscilloscope records into normalized 1D float arrays.
- **Attempt-All Safe Shutdown**: `_safe_shutdown` guarantees that all known active AWG channels are disabled and amplitude zeroed, reporting actions through `ShutdownAttemptRecorder`.
- **Unmigrated Subclass Compatibility**: `HysteresisLoop` (Checkpoint 20b) and `ThreePulsePund` (Checkpoint 20c) retain their unmigrated execution paths (`run_experiment`, `save_waveform`, `analyze`, DataFrame metadata, `history`), passing all existing characterization and golden regression suites without alteration.
- **Validation**: Targeted suites (manifest, harness, waveform reader, discrete waveform lifecycle, FE/PUND compatibility, hysteresis/PUND analysis) **294 passed**; full test suite with Agg **1367 passed, 1 skipped, 2 xfailed** in 23.86s. No physical hardware execution; Checkpoint 17 physical validation remains explicitly **PENDING**.
- **Next Step**: Proceed with **checkpoint 20b only: Hysteresis integration and consumers**. Validate and commit separately, then stop for review. Checkpoint 17 physical validation remains PENDING.

## Checkpoint 19 review corrections

- Manual time_offset now aligns polarization windows as well as the nominal
  voltage delay. Automatic detection retains the established sample-onset math;
  no-peak fallback now uses the validated manual alignment consistently.
- AWG DC offset is added to reconstructed applied_voltage, including idle levels.
  Detector voltage, current and polarization are not shifted by this parameter.
- Require coverage of the full aligned pulse train, including the last remanent
  interval. Reject incomplete captures rather than hiding them through paired
  segment trimming and table padding. Existing complete-capture goldens pass.
- auto_timeshift accepts actual booleans only. Out-of-range manual offsets raise
  ValueError before detection/fallback; broad exception suppression was removed.
- Validation: targeted PUND/FE suites **83 passed**; full suite with Agg
  **1355 passed, 1 skipped, 2 xfailed** in 26.70s. No hardware execution.
- Continue with **checkpoint 20a only**, preserving these analysis contracts and
  the numerical regressions. Keep bridges private until their callers migrate
  (hysteresis 20b, PUND 20c). Commit 20a separately and stop for review.
  Checkpoint 17 physical validation remains PENDING.

## Checkpoint 19 in-memory PUND processing

Validation: focused FE/PUND suites **114 passed** (including 49 new unit, schema, numerical, and fault tests in `tests/test_analysis_pund.py`); full suite with Agg **1342 passed, 1 skipped, 2 xfailed** in 24.72s on Python 3.13.2. Physical hardware was not tested; Checkpoint 17 physical validation remains explicitly **PENDING**.

- In-memory scientific processing: `process_pund` in `piec.analysis.pund` operates purely in-memory on DataFrame or Mapping inputs with explicit metadata.
- Plain target schema: Output DataFrame columns are strictly `['time', 'voltage', 'current', 'polarization', 'polarization_p_hat', 'polarization_p_star', 'polarization_p_hat_r', 'polarization_p_star_r', 'delta_polarization', 'applied_voltage']` with declared units `{'time': 's', 'voltage': 'V', 'current': 'A', 'polarization': 'uC/cm^2', 'polarization_p_hat': 'uC/cm^2', 'polarization_p_star': 'uC/cm^2', 'polarization_p_hat_r': 'uC/cm^2', 'polarization_p_star_r': 'uC/cm^2', 'delta_polarization': 'uC/cm^2', 'applied_voltage': 'V'}`.
- Parameter extraction & validation: Parameter precedence is explicit kwarg > metadata > default (including `r_shunt`, default 50.0 ohms; `auto_timeshift`, default True; `length`, default pulse train duration). `reset_width`, `reset_delay`, `p_u_width`, `p_u_delay`, `area`, `length`, and `r_shunt` must be finite and positive. `reset_amp`, `p_u_amp`, `offset`, and `time_offset` must be finite numbers. Metadata must be a Mapping or exactly 1-row DataFrame.
- Public processing and plotting accept plain columns only: Input units are seconds and volts; when `column_units` is declared (as mapping or JSON string), incompatible/missing time or voltage declarations are rejected. Time must be strictly increasing. Negative explicit or auto-detected time offsets raise `ValueError` because the nominal delayed-waveform algorithm cannot represent them.
- Numerical and trace equivalence: Confirmed exact numerical reproduction of golden data from `three_pulse_pund_golden.csv` with zero regression across all 10 quantities (residuals <= 1.33e-16).
- Result protocol: Returns `PundAnalysisResult(data, metadata, time_offset)` supporting tuple unpacking (`data, metadata = result`), indexing, and length.
- In-memory visualization helpers: Added `plot_pund_delta_p`, `plot_pund_traces`, and `plot_pund_components` operating on in-memory DataFrames with optional user axes.
- Unmigrated consumer bridge: Retained private `_process_raw_3pp_file` (not exported in `__all__`) as a temporary backward-compatible file bridge that delegates to `process_pund` and writes legacy column headers to CSV for unmigrated `ThreePulsePund.analyze` until Checkpoint 20c. Removed obsolete public `process_raw_3pp`.
- Checkpoint 17 physical validation status: Remains explicitly **PENDING**.
- Checkpoint 20a only is next: DiscreteWaveform base acquisition and consumers.


## Checkpoint 18 review corrections

Validation: targeted suites **99 passed**; full suite with Agg **1293 passed,
1 skipped, 2 xfailed** in 25.18s. Physical hardware was not tested.

- Parameter precedence is explicit argument, metadata, then default (including
  r_shunt, default 50 ohms). Frequency, area and shunt must be finite and positive;
  cycle and baseline counts must be valid integers. Metadata must be a mapping
  or exactly one DataFrame row.
- Public processing and plotting accept plain columns only. Input units are seconds
  and volts; when column_units is declared (mapping or JSON), incompatible/missing
  time or voltage declarations are rejected rather than silently relabeled.
- Time must be strictly increasing. Negative explicit or automatically detected
  offsets raise ValueError because the existing nominal delayed-waveform algorithm
  cannot represent them. Nonnegative-offset golden mathematics is preserved.
- The only file/legacy-column bridge is private `_process_raw_hyst_file`, explicitly
  imported by the unmigrated HysteresisLoop consumer. Remove it when that caller
  migrates at checkpoint 20b; do not reintroduce public legacy aliases.
- Checkpoint 19 only is next: apply these validation and explicit-unit conventions
  to in-memory PUND processing, preserve each numerical quantity, update consumers,
  validate and commit separately, then stop for review. Physical checkpoint 17
  remains PENDING.

## Checkpoint 18 in-memory hysteresis processing

- In-memory scientific processing: `process_hysteresis` in `piec.analysis.hysteresis`
  operates purely in-memory on DataFrame or Mapping inputs with explicit metadata.
- Plain target schema: Output DataFrame columns are strictly `['time', 'voltage', 'current', 'polarization', 'applied_voltage']`
  with declared units `{'time': 's', 'voltage': 'V', 'current': 'A', 'polarization': 'uC/cm^2', 'applied_voltage': 'V'}`.
- Flexible parameter extraction & validation: Supports metadata dictionaries, 1-row
  DataFrames, and explicit kwargs (which override metadata). Validates positivity of
  frequency, area, r_shunt, n_cycles >= 1, and finiteness of amplitude and time_offset.
- Result protocol: Returns `HysteresisAnalysisResult(data, metadata, time_offset)`
  supporting tuple unpacking (`data, metadata = result`), indexing, and frozen attribute bindings (the contained DataFrame and dict remain mutable).
- Numerical and trace equivalence: Confirmed exact numerical reproduction of golden
  data from `hysteresis_loop_golden.csv` with zero regression (residuals <= 9.5e-17).
- In-memory visualization helpers: Added `plot_hysteresis_pv`, `plot_hysteresis_iv`,
  and `plot_hysteresis_traces` operating on in-memory DataFrames with optional user axes.
- Unmigrated consumer bridge: Retained private `_process_raw_hyst_file` as a temporary backward-compatible
  file bridge that delegates to `process_hysteresis` and writes legacy column headers to
  CSV for unmigrated callers until Checkpoint 20b.
- Checkpoint 17 physical validation status: Remains explicitly **PENDING**.
- Tests: Added 15 comprehensive unit, schema, numerical, and fault tests in
  `tests/test_analysis_hysteresis.py` (15 passed).
- Test suites: Combined FE/hysteresis suites (70 passed); full test suite with Agg:
  **1264 passed, 1 skipped, 2 xfailed** in 24.44s on Python 3.13.2.

## Checkpoint 17 documentation review corrections

- Require actual bench-specific calibration for physical field validation;
  `example_calibration.csv` is illustrative only.
- Removed invented numerical acceptance limits and fixed hardware prescriptions.
  The operator records supported instruments, setup limits, tolerances and their
  basis before execution. Stop timing accounts for ramp settings and I/O timeouts.
- Separate acquisition failure with successful SAFE shutdown from UNSAFE shutdown.
  Only the latter requires connections to remain available for safety recovery.
- Do not assume interlock state is reported to software, output-disable commands
  prove relay position, or failed staging always leaves recoverable data.
- Section 13.1 links to the single detailed record template in
  `docs/physical_validation_iv_moke.md`, avoiding conflicting protocol copies.
- Gemini's empty VISA discovery result is recorded as reported, not as proof that
  no physical instruments exist. Actual hardware execution and sign-off are PENDING.
- Documentation-only review: checked the diff and consistency with the current
  shutdown and GUI ownership implementation. No new test suite or hardware run.
  Prior software validation at `6b8cd96`: 1249 passed, 1 skipped, 2 xfailed with Agg.

## Checkpoint 16 review corrections

- Geometry choices retain separate editable setups for this GUI session: instrument
  addresses, source channel, calibration, output range, compliance, timing, and
  field-reader conversion. A newly selected geometry starts with virtual demo
  defaults; no physical laboratory wiring or calibration is assumed. Settings
  are not persisted across application restarts. Configure and verify physical
  settings explicitly before running.
- Run creation captures and validates a `MokeSetupProfile` before connections.
  Custom source shutdown callbacks can be supplied per geometry through
  `MokeMeasurementApp(root, shutdown_handlers={...})`; otherwise the standard
  ramp-to-zero/output-off policy applies. Geometry switching is blocked during
  active runs and unsafe recovery.
- Snapshots retain acquisition geometry, so selecting the next setup cannot
  relabel acquired data. Plot toggles retain the snapshot's original geometry.
- Polling handles control events first, renders at most one live frame per tick,
  and discards pending live data when a terminal snapshot is received.
- Added regressions for profile restoration, active/unsafe selection rejection,
  validation before connection, actual virtual acquisition with custom shutdown,
  original plot geometry, bounded polling, and terminal-frame precedence.
- Removed a scheduler race in the existing Stop-before-start test: Stop is now
  requested after reservation and before execution, requiring `NOT_NEEDED` safety.
- Full suite with the Agg command below: **1249 passed, 1 skipped, 2 xfailed**
  in 26.53s. This covers headless GUI logic; physical hardware remains unverified.
- Checkpoint 17 requires a dated record of actual physical IV/MOKE execution.
  Without hardware execution, mark it **PENDING** and describe the missing checks;
  virtual tests are not physical validation. Do not proceed to checkpoint 18 yet.

## Checkpoint 16 MOKE GUI interaction and ownership hardening

- Single hardware writer rule: callbacks (`refresh_instruments`, `browse_calibration`,
  `run_measurement`) reject hardware commands/queries or calibration modifications
  while a measurement is active (`is_measuring`).
- Connection ownership & deferred teardown: GUI-created instruments are tracked in
  `_instruments` and closed strictly after worker thread termination, terminal event
  delivery, and confirmed hardware safety (`SAFE` or `NOT_NEEDED`).
- Unsafe shutdown retention: If shutdown fails (`UNSAFE`), instrument connections are
  retained open for diagnosis/recovery, normal window closing is deferred, and connections
  are only released if a subsequent safe retry succeeds before window destruction.
- Window close coordination: `WM_DELETE_WINDOW` requests cooperative stop via
  `runner.request_close()`, defers window destruction, and polls until the worker
  has cleanly terminated with confirmed safety.
- Stop-before-start zero-I/O abort: Immediate stop requests transition cleanly to
  `ABORTED` with `NOT_NEEDED` safety without executing any hardware commands, releasing
  connections cleanly.
- Terminal recovery paths: On save failure, recoverable staging paths are extracted
  from `TerminalEvent.record.metadata["recoverable_staging_paths"]` and reported to
  the console.
- Pre-run control safety: Controls like trace toggles, geometry combobox, STOP, and
  redraw safely handle `_last_snapshot` and `runner` being None/unset before the first run.
- Geometry selection and titles: corrected by the review above; titles describe
  acquisition geometry and choices select the next run's setup.
- Setup validation errors: Invalid inputs (e.g. inverted min/max output) display an error
  dialog and abort before creating a runner or leaving dangling instruments.
- Added 8 comprehensive regression tests in `tests/test_moke_gui.py` (13 passed).
  Focused MOKE suites: **96 passed**. Full test suite (with Agg backend):
  **1239 passed, 1 skipped, 2 xfailed** in 24.30s on Python 3.13.2.
  Physical hardware and the opt-in SMB path remain unverified.


## Checkpoint 15 review corrections

- Deferred close now releases GUI-owned connections after a successful safety retry,
  before destroying the window. Unsafe shutdown still retains connections.
- Recovery paths come from `TerminalEvent.record.metadata["recoverable_staging_paths"]`;
  `TerminalEvent` has no direct recovery-path field.
- Plot-axis changes before creating an experiment are harmless no-ops.
- Added three regressions to `tests/test_measurement_iv_gui.py`, including a real
  failed publication that retains staging and a failed shutdown followed by retry.
- Focused IV GUI/review tests: **26 passed**. The default full-suite run hit a host
  Tk installation failure in the unrelated PUND plot-artifact test (missing
  `icons.tcl`). Full suite with Matplotlib Agg: **1231 passed, 1 skipped, 2 xfailed**.
  Command: `.\.venv\Scripts\python.exe -c "import piec.measurement.gui_utils; import matplotlib; matplotlib.use('Agg'); import pytest; raise SystemExit(pytest.main(['-q', '-p', 'no:cacheprovider']))"`.
  This validates headless logic and artifacts, not a physical Tk window or hardware.

## Checkpoint 15 IV GUI interaction and ownership hardening

- Single hardware writer rule: callbacks (`run_measurement`, `refresh_instruments`)
  reject hardware commands/queries while a run is active (`is_measuring`).
- Connection ownership: GUI-created instruments are tracked in `_instruments` and
  closed strictly after the worker thread terminates, terminal event is delivered,
  and hardware safety is verified (`SAFE` or `NOT_NEEDED`).
- Unsafe shutdown retention: If shutdown fails (`UNSAFE`), instrument connections
  are retained open for diagnosis/recovery, normal window closing is blocked, and
  an alert is surfaced to the operator.
- Window close coordination: `WM_DELETE_WINDOW` requests cooperative stop via
  `runner.request_close()`, defers window destruction, and polls until the worker
  has cleanly terminated with confirmed safety.
- Stop-before-start zero-I/O abort: Immediate stop requests transition cleanly to
  `ABORTED` with `NOT_NEEDED` safety without executing any hardware commands.
- Dual event queues and terminal display: Drains bounded display queue for real-time
  updates and non-droppable control queue for `SafetyAlertEvent` and `TerminalEvent`.
  Terminal plots use full `TerminalEvent.data` or `experiment.data`.
- Fault injection and recovery: Comprehensive error reporting for invalid numeric
  inputs, instrument connection errors, and mid-sweep acquisition timeouts.
- Added 8 comprehensive regression tests in `tests/test_measurement_iv_gui.py` (10 passed).
  Focused IV suites: **53 passed**. Full suite: **1228 passed, 1 skipped, 2 xfailed**
  in 26.38s on Python 3.13.2. Physical hardware and SMB remain unverified.

## Checkpoint 14 review corrections

- Public `raw_data` now uses the base contract and retains every acquired point.
  Only live raw views are bounded; complete raw data is materialized in finally.
- MOKE inherits `snapshot()` and `publish_snapshot()` unchanged. The shared engine
  uses `snapshot_type = MokeSnapshot` for live, queried, and terminal snapshots,
  preserving real run ID, generation, sequence, state, safety, and defensive copies.
- The engine invokes `_reset_run_views()` after successful reservation and before
  configuration or early abort. MOKE resets windows, averages, cycles, and per-run
  metadata there so failed repeat runs cannot expose old data.
- Removed `configure_sourcemeter`, `configure_dmm`, `shut_off`, `analyze`, `save_data`,
  and legacy `history`. Use shared configure/capture/session/safe_shutdown wrappers
  and `run_records`. Retained manual `set_output`/`set_field` helpers enforce the
  execution owner or an idle command lease.
- Constructor uses only `output_dir` and `shutdown_handler`; no `save_dir` or
  `safe_shutdown` keyword aliases. Unknown run options are rejected before I/O.
  Tests, notebook code, documentation and the GUI now use this interface.
- GUI uses MeasurementRunner, non-daemon execution, separate display/control queues,
  terminal snapshots, and worker-exit plus safety checks before releasing connections.
  Unsafe shutdown retains connections and blocks normal close. Further MOKE GUI
  interaction, geometry and recovery UX hardening remains checkpoint 16.
- Added tests/test_measurement_moke_review.py (10 regression cases). Focused MOKE
  suites: **94 passed**. Full suite: **1220 passed, 1 skipped, 2 xfailed**.
  Physical hardware and the opt-in SMB path remain unverified.

## Checkpoint 14 MOKE vertical slice migration

- `MokeMeasurement` migrated to `BaseMeasurement`:
  - Zero hardware I/O in constructor (`sourcemeter.idn` and `dmm.idn` deferred to configuration hook).
  - Positional instruments `sourcemeter`, `dmm`; all measurement settings keyword-only.
  - Plain lowercase columns (`time`, `cycle`, `point`, `direction`, `source_output`,
    `field_calibrated`, `detector_voltage`, and optional `field_measured`, `field_time`)
    with JSON metadata units.
  - Dual field modes: calibrated field mode and sequential measured field mode via `field_reader`.
  - Paced, cancellable ramps for initial setpoint, point transitions, and safing ramp
    using `max_output_step` and `ramp_delay`. Transitions do not add intermediate measurement rows.
  - Guaranteed attempt-all software safing: output disable is attempted even if zero-ramp fails,
    and custom shutdown handler is supported.
  - Bounded live snapshots (`raw_window_points`, default 1000) returning `MokeSnapshot`.
  - Cycle averaging excluding partial/aborted cycles. Full raw data preserved in `finally`
    across read errors, callback crashes, or cooperative stops.
- Golden CSVs (`moke_calibrated_golden.csv`, `moke_measured_golden.csv`) updated to standard
  1-row metadata layout with `run_id`, `outcome`, `partial`, and `save_requested`.
- `manifest.json` updated with `MokeMeasurement` and `MokeSnapshot` in `migrated_families`.
- Added unit, lifecycle, and fault injection test suite `tests/test_measurement_moke.py` (16 passed).
- Updated compatibility test suite `tests/test_measurement_iv_moke_compatibility.py` (14 passed).
- Existing test suites: `tests/test_moke.py` (49 passed), `tests/test_moke_gui.py` (5 passed),
  `tests/test_dmm_contract.py` (34 passed).
- Full repository test suite: **1210 passed, 1 skipped, 2 xfailed** in 23.87s on Python 3.13.2.

## Checkpoint 13 review corrections

- IV configuration disables output before identity queries, source programming,
  or sense changes. Voltage endpoints reject NaN and infinity before hardware I/O.
- Every sweep transition uses the paced, cancellable ramp helper. `ramp_step` now
  limits initial, between-point, and safing transitions; intermediate ramp commands
  do not add measurement rows. Stop during a transition skips its pending read.
  Dwell timing uses the monotonic clock.
- Session configure/capture use the already validated request. They no longer reread
  the caller's mutable options dictionary after entering the session.
- Live IV raw views contain at most the latest 100 points; full raw data is built
  from the acquisition buffer in finally, including on read/callback failure.
  The existing authoritative terminal result remains complete. The GUI uses
  `TerminalEvent.data` for its final plot rather than the bounded raw window.
- The abort regression now stops after two acquired samples rather than counting
  voltage writes, because ramp writes are not acquired samples.
- Added `tests/test_measurement_iv_review.py`: endpoint validation, output order,
  frozen session options, ascending/descending ramp limits, cancellation during
  a sweep transition, bounded raw views/full retained data, and full GUI final plots.
- Focused IV/session tests: **71 passed**. Full suite: **1194 passed, 1 skipped,
  2 xfailed**. Real hardware and SMB validation remain
  pending; these checks use virtual hardware and headless GUI logic.

## Checkpoint 12 corrections

- `compliance_current` is validated before reservation/I/O and applied through
  `configure_voltage_source`; its default in the example is 0.01 A.
- Acquisition preserves completed samples in `self._raw_data` in `finally`, including
  read and callback failures. Hardware cleanup belongs to the engine-invoked
  `_safe_shutdown`, keeping acquisition errors primary if shutdown also fails.
- Display snapshots are bounded, callbacks receive snapshots, and the command-line
  queue consumer handles `queue.Empty`. GUI consumers still use UI timer polling.
- The safing example records command success without inventing readback support.
  A driver's optional no-op must never be converted into successful verification.
- Documentation now describes actual Windows publication and close gating. There
  is no unsafe-close acknowledgment override. Stop-before-start skips hardware
  safing, and partial filenames depend on save policy and successful publication.
- `tests/test_measurement_developer_guide.py` executes the published code blocks,
  covering successful workflows, invalid/applied compliance, read/callback partial
  recovery in runs and sessions, queue timeout, and simultaneous acquisition and
  shutdown errors. All 16 tests passed.
- Full repository verification: **1163 passed, 1 skipped, 2 xfailed**. Real SMB and
  physical hardware remain unverified. Production measurement files were unchanged
  in the checkpoint 12 correction.

## Corrections already implemented

- Bundle publication keeps original side-artifact staging files until the completed
  CSV succeeds. A failed CSV publication leaves recoverable raw data. Rollback
  checks the published file identity before deletion and reports cleanup failures.
- Reservations contain full run IDs and unique claim IDs. Release verifies the
  claim; an old reservation cannot delete a replacement owner's marker.
- Publication, reservation reuse, and cleanup use exclusive guard files. An
  abandoned `.res.lock` blocks that candidate; do not automatically delete it.
  Inspect and explicitly remove such locks only after confirming no writer is active.
- `stale_age_seconds` only permits reuse of the explicitly named run's marker.
  Age alone never authorizes taking a foreign run's reservation. Cleanup requires
  `owner_uuid`; omission does nothing. Partial cleanup also validates the CSV's
  run ID and partial flag. Unknown or foreign files are retained.
- Cross-volume fallback reuses the bundle's existing reservation. The POSIX
  fallback still fails safely if no no-replace primitive is available.
- Partial metadata is validated before allocating staging. Replacing a checkpoint
  requires matching ownership metadata. Replacement failures retain/report the
  new staging file and preserve the previous checkpoint.

## Shared engine persistence API reference

`BaseMeasurement` accepts keyword arguments `output_dir`, `measurement_schema`,
`column_units`, optional `raw_column_units`, and optional `metadata`.
No persistence configuration is needed for `save=False`. Saving requires explicit
configuration; the engine no longer reports a virtual path as a successful save.

For example, a subclass for IV data can initialize the shared engine with:

```python
super().__init__(
    output_dir=output_dir,
    measurement_schema="iv_sweep",
    column_units={"voltage": "V", "current": "A"},
    metadata={"sample": sample_name},
)
```

The engine generates required lifecycle metadata and uses plain column names with
JSON unit metadata. `raw_column_units` describes partial data when its columns
differ from analyzed results. Full runs and sessions both use real filesystem
publication. Aborted/failed partials record their actual outcome; they never set
`filename`. Completed filenames are assigned only after successful publication.

Families producing plots override `_stage_side_artifacts(data, request,
reservation)` to return `(staging_path, target_path)` pairs. Targets must be in the
reserved destination and begin with `reservation.candidate_basename + "_"`.
Use run-owned hidden staging names; preserve raw data in memory. If staging itself
fails, attach any recovery paths to the exception. Do not override the shared
publication mechanism just to implement plots.

Save errors preserve in-memory raw data and expose `recoverable_staging_paths`
on the exception and measurement, and in `RunRecord.metadata`. The standalone
`write_partial_csv` helper supports intentional updates to an owned checkpoint.
Do not describe automatic periodic checkpoint scheduling as implemented.

## Verification and boundaries

Checkpoint 11c verification passed: **1147 passed, 1 skipped, 2 xfailed**.
The newer checkpoint 12 result is recorded above.
Sixteen new recovery/engine regressions cover the reviewed failures, actual
completed and partial CSVs for runs and sessions, and failed-save recovery.
The opt-in real SMB test remains skipped; cross-volume behavior was fault-injected.
No physical hardware or SMB deployment validation is claimed.

Measurement-family migrations remain in their planned checkpoints. Preserve the
user's decisions: plain columns, units in metadata, standardized APIs throughout,
and no legacy argument adapters or compatibility shims.
