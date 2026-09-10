# Measurement standardization handoff

Continue on `measuremnt-standarization`. Checkpoint 15 is complete. Next is
**checkpoint 16 only: MOKE GUI interaction/ownership hardening**, following the
measurement standardization plan. Validate and commit checkpoint 16 separately.

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
