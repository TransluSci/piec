# PIEC Measurement and Simulation Standardization Plan

Status: approved contract; implementation started.

## Implementation handoff: read this first

**Authoritative user decision (2026-09-08): all measurement families adopt the new standard.** Backward compatibility with old measurement APIs, columns, metadata, filenames, plotting helpers, and file readers is not required. Replace old implementations where necessary; update repository consumers in the same family checkpoint. This supersedes the earlier MOKE-only exception and all earlier instructions to freeze IV/FE/AMR behavior. Preserve scientific meaning, numerical results, calibration, and safety, not obsolete interfaces. Do not delete user data or rewrite saved experimental files.

**Next action:** commit this contract amendment separately, then implement checkpoint **2R** (revise the test/manifest contract) before resuming 2b–2d. The previous inserted M1 checkpoint is cancelled: schema and lifecycle changes now land together in each family's vertical slice, with its consumers updated. Existing staged work is reference material to reconcile, not permission to freeze old schemas.

If M1 implementation was already started before this amendment arrived, retain useful target-schema work and reconcile it in 2R; do not revert it merely to satisfy the revised ordering. Record what actually landed and the remaining lifecycle/consumer work in checkpoint 14. Concurrent edits are not automatically reviewed by this documentation amendment.

Implement **one numbered checkpoint from section 12 per task**. The architecture sections are requirements for those checkpoints, not permission to implement the whole document at once. Resume from the progress log; the next checkpoint under this amendment is 2R.

For each checkpoint:

1. Read this plan, inspect `git status --short`, and identify the last completed checkpoint from Git history and the progress log below. Preserve unrelated uncommitted work, including the existing `processed` addition in the developer guide.
2. State the checkpoint number, files in scope, and acceptance tests. Read the relevant existing code and characterization fixtures before editing.
3. Implement only that checkpoint and its tests. Do not introduce dependencies on later checkpoints. Framework checkpoints use fake hooks/in-memory persistence until the real adapter exists.
4. Run focused acceptance tests and the full available suite. Report exact commands and results. A missing interpreter, skipped platform test, or unavailable hardware is a blocked/unverified gate, never a pass.
5. Review the diff for target-contract compliance, numerical regressions and unrelated edits. Update the progress log with results and remaining gates. Stage explicit paths, never `git add .`.
6. When checks pass, create the checkpoint commit if committing has been authorized. Otherwise stop with the exact diff ready to commit. Report commit hash (or uncommitted status), tests, remaining gates, and the next checkpoint. **Stop here; wait for the next task before continuing.** Do not squash checkpoints together.

If a numbered checkpoint is too large for one reviewable change, divide it into lettered commits using the split rules in section 12. Each lettered commit is also a stopping point. If a contract contradiction requires a design decision, describe it and amend the plan in a documentation checkpoint before dependent implementation.

Suggested implementation prompt:

> Read MEASUREMENT_STANDARDIZATION_PLAN.md. Implement only checkpoint <number or letter>, preserving existing uncommitted work. Follow the handoff checklist, run the stated checks, and stop at that checkpoint. Do not implement later stages. Report any gate you cannot verify. [Add "Commit the checkpoint when its automated checks pass" if desired.]

### Progress log

| Checkpoint | Status | Validation / remaining gates |
|---|---|---|
| Plan review | Approved | Source review confirmed baseline commits `9d9760242f44a79401626964f0122cc91b149c18` and `d1bac1ccf37e6578586336278c1ea36cf39b4722` exist. Human review confirmed no unresolved contradictory requirements. Baseline test suite verified: 276 passed in 30.21s (`.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider` on Python 3.13.2). |
| 1 | Completed | Contract finalized and approved. Commit `1e49f43`. |
| 2a | Completed | Added compatibility manifest and harness. Commit `69548ab`. |
| 2R | Complete | Reference/target separation, migration-aware interface checks and strict scientific comparison are implemented. Isolated staged tree: 375 passed in 27.12s; full working tree including pending MOKE/2b work: 390 passed in 26.82s on Python 3.13.2. No production measurement changes belong in the 2R commit; CI Python 3.9/3.11 remains unverified locally. |
| 2b | Completed | Reconciled IV/MOKE deterministic scientific fixtures (`iv_sweep_golden.csv`, `moke_calibrated_golden.csv`, `moke_measured_golden.csv`) and 14 regression tests in `test_measurement_iv_moke_compatibility.py` verifying exact CSV layout, metadata, units, golden regression, and old-to-new column numerical equivalence. All 390 tests pass. |
| 2c | Completed | Added FE and PUND deterministic scientific fixtures (`discrete_waveform_golden.csv`, `hysteresis_loop_golden.csv`, `three_pulse_pund_golden.csv`) and 21 regression tests in `test_measurement_fe_pund_compatibility.py` verifying exact CSV layout, metadata, units, golden regression, polarization calculations, auto_timeshift, plot artifacts, and old-to-new column numerical equivalence (including raw view). Fixed read-only array in `pund.py`. All 411 tests pass in 24.27s on Python 3.13.2. |
| 2d | Completed | AMR scientific golden and separately labeled legacy observation, consumer inventory, and regression tests. Signal tolerance is 1e-10 V; flat X/Y are rejected. Known defects AMR-FIELD-001 (23a) and AMR-ANGLE-001 (24b) have strict expected-failure tests, not frozen scientific expectations. AMR suite: 25 passed, 2 xfailed; full suite: 436 passed, 2 xfailed in 23.25s on Python 3.13.2. CI environments remain unverified locally. |

| M1 | Cancelled by all-family standardization | Schema, API and consumer changes now belong in each family slice (13, 14, 20, 24), not a separate MOKE exception. |
| 3 | Completed | Repaired Awg.output_trigger indentation in piec.drivers.awg.awg so it is a class method rather than an inner function of configure_trigger. Added focused contract tests in tests/test_awg_contract.py verifying class method status, signature, absence of inner function in configure_trigger, and implementation across all concrete AWG drivers (VirtualAwg, Keysight81150a, SDG2000X). All 446 tests pass, 2 xfailed in 24.34s on Python 3.13.2. |
| 4 | Completed | Repaired inverted trigger_source condition in Awg.configure_trigger and Keysight81150a.configure_trigger; normalized case handling in SDG2000X trigger methods. Added focused contract tests in tests/test_awg_contract.py. Commit `48414d0`. |
| 4 follow-up | Completed | Comprehensive inventory and audit of all concrete AWG drivers and adapters (VirtualAwg, Keysight81150a, SDG2000X, Agilent33220A, Agilent33500, RigolDG1000, RigolDG4000, DaqAsAwg). Distinguished implemented trigger behavior from inherited empty stubs; explicitly documented unsupported capabilities in driver docstrings and Section 9.3 audit table; verified supported drivers via command/effect assertions and empty stubs via no-op assertions (32 tests in tests/test_awg_contract.py). |
| 5 | Completed | Standardized Sourcemeter, VirtualSourcemeter, and Keithley2400 on channel-first signatures with default channel=1. Removed legacy compatibility normalizer and Instrument hook; standardized repository callers and documentation to explicit keywords (e.g. source.output(channel=1, on=False), source.set_source_voltage(channel=1, voltage=...)). Retained native Python argument binding (TypeError for duplicate/excess/unknown arguments); numeric and mode setters reject missing values and invalid channels without state mutation or transport writes. Simplified MOKE test recording wrapper to def record(channel=1, voltage=None). Contract suite: 136 passed; full suite: 715 passed, 2 xfailed in 55.43s on Python 3.13.2. Checkpoint 6 remains next. |
| 4 DAQ pulse addition (user-authorized) | Completed | Added general DAQ pulse capability/validation API and documented software fallback override requirements. USB231 inherits DIO software pulses; USB1208HS adds finite TMR pulses. DaqAsAwg delegates through the general API with explicit terminal selection; analog playback synchronization remains unsupported. VirtualDaq records simulated pulses. See docs/daq_trigger_output.md. Focused: 49 passed; full: 579 passed, 2 xfailed in 24.05s. Physical verification remains pending. Checkpoint 5 remains next. |
| 4 capability addition (user-authorized) | Completed | Added documented Agilent33220A/33500 and Rigol DG1000(Z)/DG4000 trigger configuration, software firing where verified, validation and command tests. Fixed related DG1000 legacy/Z channel routing and 33500 waveform/pulse-edge mappings. See docs/awg_trigger_support.md for exact scope and references. Legacy DG1000 remote launch remains unverified; DAQ trigger backend unchanged. Focused: 118 passed; full: 554 passed, 2 xfailed in 28.57s. Physical and Python 3.9 CI verification remain pending. Checkpoint 5 remains next. |
| 4 audit correction | Completed | Distinguished Python implementation gaps from manufacturer-documented hardware trigger support; removed unverified trigger-count and protocol-limit claims; inventory test discovers AWG/emulator classes instead of checking a fixed count. No driver operating code changed. Focused: 32 passed; full suite: 468 passed, 2 xfailed in 25.13s. Checkpoint 5 remains next. |
| 6 | Completed | Audited and contract-tested voltage configuration and reading across all advertised DMMs (VirtualDMM, Agilent34410A, Keithley2000, Keithley193a). Repaired Agilent34410A set_sense_function NoneType crash and defaulted coupling/mode to DC/2W; implemented set_measurement_coupling and set_sense_mode across Agilent34410A and Keithley2000; synchronized internal SCPI function tracking across all getters and reset to avoid stale post-read or post-reset configuration; normalized recognized hardware overloads via named class constants (SCPI_OVERLOAD_THRESHOLD, DDC_OVERLOAD_PREFIXES, DDC_OVERLOAD_THRESHOLD) to non-finite IEEE 754 floats (+/- inf) so MOKE detector validation catches and rejects overloads while safing the sourcemeter; separated VirtualDMM as software simulation with direct non-finite pass-through; explicitly capability-gated unsupported configurations via NotImplementedError; added manufacturer documentation references and audit report in docs/dmm_voltage_read_audit.md; verified real MOKE measurement execution, overload rejection, and safing. Focused DMM suite: 79 passed; full suite: 794 passed, 2 xfailed in 17.77s on Python 3.13.2. Checkpoint 7 remains next. |
| 7 | Completed | Implemented WaveformReader setup adapter (piec.measurement.adapters.WaveformReader) and WaveformRecord. Normalizes oscilloscope get_data() outputs across multi-dialect formats (DataFrame, dict, tuple of arrays, and channel variants such as 'Time'/'Voltage', 'Channel {ch}', and 'Voltage_CH{ch}'). Enforces plain lowercase 'time' and 'voltage' output arrays, declared unit mapping ({'time': 's', 'voltage': 'V'}), finite numeric validation (rejection of NaN/Inf), non-empty positive equal-length arrays, and channel routing/validation. Separates signature inspection in __init__ from acquisition execution so scope exceptions (TypeError, ValueError, RuntimeError) propagate cleanly after exactly one read without catch-and-retry masking. Enforces strict channel isolation to reject wrong-channel tables without silent fallback. Added 56 comprehensive contract and regression tests in tests/test_waveform_reader.py. Focused suite: 56 passed; full suite: 850 passed, 2 xfailed in 20.83s on Python 3.13.2. Checkpoint 8 remains next. |
| 8 | Completed | Implemented lifecycle state machine (RunState, SafetyStatus), strict legal transition validation, thread-safe synchronous reservation with UUID and monotonic generation counter, token validation rejecting stale tokens and duplicate execution, Stop control semantics across active/safing/dormant phases, idle command lease protection, immutable RunRecord and RunRequest contracts, and BaseMeasurement integration. Added 90 comprehensive contract tests in tests/test_measurement_lifecycle.py. Focused suite: 90 passed; full suite: 940 passed, 2 xfailed in 20.83s on Python 3.13.2. Checkpoint 9a remains next. |
| 9a | Completed | Implemented full-run execution engine (BaseMeasurement.run_experiment) enforcing canonical phase ordering (STARTING -> CONFIGURING -> RUNNING -> SAFING -> ANALYZING -> SAVING -> COMPLETED/ABORTED/FAILED). Enforced Stop-before-start zero-I/O aborts with safety NOT_NEEDED. Guaranteed safing execution across all exit paths, error precedence (preserving primary errors while recording secondary shutdown errors, raising HardwareSafetyError on shutdown-only failures), outcome/persistence matrix compliance, and exact single RunRecord and TerminalEvent per reservation. Added 14 contract tests in tests/test_measurement_engine.py. Focused suite: 14 passed; full suite: 954 passed, 2 xfailed in 21.76s on Python 3.13.2. Checkpoint 9b remains next. |
| 9c | Completed | Implemented fault handling hardening across full runs, sessions, standalone scopes, and safe shutdown. Implemented `ShutdownAttemptRecorder` ensuring all required shutdown actions are attempted even if earlier actions fail, tracking readback verification, duration, and errors. Preserved original tracebacks without mutating `__context__` (Python 3.9 compatible, no `ExceptionGroup`). Deferral of `KeyboardInterrupt` and `SystemExit` during configuration and acquisition until safing finishes, then re-raised unchanged. Secondary cleanup and persistence failures recorded in `SafetyReport`, `RunRecord.secondary_errors`, and `TerminalEvent.secondary_errors` without masking primary errors. Cleanup-only interrupts re-raised unchanged; cleanup-only ordinary failures raise `HardwareSafetyError` with full report. Cooperative abort with required partial save failure transitions to `FAILED` and raises persistence error. Callback failures treated as acquisition failures. Reporting failures guarded to never mask scientific or safety errors. Added 25 comprehensive tests in `tests/test_measurement_faults.py`. Focused faults suite: 25 passed; all measurement suites: 155 passed; full test suite: 1005 passed, 2 xfailed in 17.66s on Python 3.13.2. Checkpoint 10a remains next. |
| 10a | Completed | Implemented bounded snapshots and dual display/control event paths. `MeasurementSnapshot` with defensive DataFrame copying on construction and retrieval, mapping/dict protocol, convenience properties (`raw_window`, `last_cycle`, `cycle_average`, `raw`), and immutable attributes. Bounded coalescing `DisplayQueue` with drop-oldest policy on saturation, tracking `dropped_count`, and non-blocking `put()`. Unbounded non-droppable `ControlQueue` delivering `StateChangeEvent`, `SafetyAlertEvent`, and `TerminalEvent` in strict FIFO order without loss. Immediate `SafetyAlertEvent` emission on safing failure (`SafetyStatus.UNSAFE`). Authoritative `final_snapshot` carried inside `TerminalEvent`. Added 17 comprehensive tests in `tests/test_measurement_snapshots.py`. Focused snapshot suite: 17 passed; all measurement suites: 365 passed, 2 xfailed in 25.62s; full test suite: 1022 passed, 2 xfailed in 18.12s on Python 3.13.2. Checkpoint 10b remains next. |
| 10b | Completed | Implemented `MeasurementRunner` and `CloseCoordinationStatus` in `src/piec/measurement/runner.py`. Enforced synchronous reservation on caller thread before worker launch, non-daemon background thread execution (`daemon=False`), worker thread-start failure recovery cleanly finalizing reservation as `FAILED` with `NOT_NEEDED` safety, and cooperative Stop/Pause controls. Implemented non-blocking application/window close coordination checking worker death, terminal completion, and confirmed hardware safety (`SAFE` / `NOT_NEEDED`), blocking exit when safety is `UNSAFE`. Wired convenience display and control queues directly through runner. Added 11 comprehensive unit and contract tests in `tests/test_measurement_runner.py`. Focused runner suite: 11 passed; all measurement suites: 376 passed, 2 xfailed in 16.88s; full test suite: 1033 passed, 2 xfailed in 18.97s on Python 3.13.2. Checkpoint 11a remains next. |
| 11a | Completed | Implemented handle-based CSV writer, reader, and schema/unit metadata serialization in `src/piec/measurement/persistence.py`. Enforces 1-row metadata, blank separator, and data table layout through a single open UTF-8 handle with `flush()` and `os.fsync()`. Validates compact sorted JSON serialization of column-to-unit mapping with JSON `null` for unitless columns. Validates metadata against `REQUIRED_METADATA_FIELDS` and standard version 1 schemas (`iv_sweep`, `moke`, `discrete_waveform`, `hysteresis`, `three_pulse_pund`, `amr`), and standard columns (`STANDARD_COLUMNS`). Rejects missing, extra, and conflicting column units, multi-row metadata, and non-blank separator lines. Refactored `piec.analysis.utilities.metadata_and_data_to_csv` to write through a single UTF-8 handle with flush and fsync. Added 26 tests in `tests/test_measurement_persistence.py`. Focused persistence suite: 26 passed; all measurement suites: 413 passed, 2 xfailed; full test suite: 1070 passed, 2 xfailed in 19.00s on Python 3.13.2. Checkpoint 11b remains next. |
| 11b | Completed | Implemented atomic no-replace publication (`atomic_publish_no_replace`), safe destination-directory staging via `tempfile.mkstemp()` (`create_staging_file`), atomic measurement CSV writing and publishing (`atomic_publish_measurement_csv`), and `write_measurement_csv(..., atomic=True)`. Enforced strict no-replace semantics: pre-existing targets raise `FileExistsError` without truncation or overwrite, while staging files are preserved on collision for data recovery. Incomplete staging files are cleaned up on write/sync failure. NTFS multi-threaded collision tests confirm exactly one winner and non-destructive loser staging preservation. Strict mode rejects cross-volume moves with `UnsupportedFilesystemError`. Redesigned non-strict collision-resistant fallback around hidden reservation marker (`.{target.name}.res`) and destination-local staging (`dest_staging`) to prevent exposing empty completed-looking CSVs on interruption and solve cross-volume publication. Isolated SMB test directory with unique `tempfile.mkdtemp` and restricted cleanup strictly to invocation artifacts. Added 19 tests in `tests/test_measurement_persistence_atomic.py`. Persistence suites: 44 passed, 1 skipped; all measurement suites: 481 passed, 1 skipped, 2 xfailed; full repo suite: 1113 passed, 1 skipped, 2 xfailed in 19.09s on Python 3.13.2. Checkpoint 11c remains next. |
| 11c | Completed | Review corrections: bundle publication retains original side staging until CSV success; failure reports recoverable paths and removes only unchanged owned publications. Reservation release checks the unique claim; guard files serialize publication, reuse, and explicit cleanup. Age alone cannot reclaim a foreign run's marker. Cleanup without owner_uuid is a no-op; partial cleanup requires matching validated CSV metadata. Partial metadata validation precedes staging allocation. The cross-volume fallback reuses the active bundle reservation. BaseMeasurement now publishes actual CSV/partial files through the shared helpers using explicit output_dir, measurement_schema, column_units, optional raw_column_units and metadata; _stage_side_artifacts supplies plots under the reserved basename. Failed saves preserve memory and report recovery paths on exceptions, the measurement, and RunRecord metadata. Added 16 recovery/integration regressions; full suite: 1147 passed, 1 skipped, 2 xfailed. See MEASUREMENT_HANDOFF.md. Checkpoint 12 is next. |
| 12 | Completed | Rewrote the developer guide and contributing page against the shared engine. Review corrections apply and validate compliance, preserve raw partials on read/callback failure, centralize attempt-all safing without masking acquisition errors, avoid unsupported readback claims, and handle display queue timeouts. Corrected Windows publication, close coordination, migration status, and partial-save descriptions. Added tests/test_measurement_developer_guide.py to execute the actual guide blocks and fault cases: 16 passed. Full suite: 1163 passed, 1 skipped, 2 xfailed. Checkpoint 13 is next; see MEASUREMENT_HANDOFF.md. |
| 13 | Completed | Migrated IV sweep to standardized engine (`piec.measurement.iv_sweep.IVSweep`). Replaced legacy constructor I/O with zero-I/O `BaseMeasurement` architecture, implemented target lifecycle hooks, plain `voltage`/`current` columns with `V`/`A` metadata units, cancellable pre-ramp/dwell/sweep, independent-pacing safing ramp to 0 V, guaranteed attempt-all safing with output disable on ramp error, and partial data preservation on abort. Updated `Measurements/DCIV/IV_sweep_GUI.py` to use `MeasurementRunner`, non-blocking Tk polling via `after()`, plain columns, and stop controls. Updated `dciv_measurement.md`. Added `IVSweep` to `manifest.json` migrated families and updated golden CSV to standard 1-row layout. Added unit/lifecycle/fault tests in `tests/test_measurement_iv.py` (16 passed), GUI tests in `tests/test_measurement_iv_gui.py` (2 passed), and updated compatibility suite `tests/test_measurement_iv_moke_compatibility.py` (14 passed). Full suite: 1181 passed, 1 skipped, 2 xfailed in 22.36s on Python 3.13.2. Review fixes: disable output before configuration; reject nonfinite endpoints; ramp every sweep transition with cancellation; keep session options frozen; bound live raw windows to 100 points while retaining complete acquisition and GUI terminal data. Added tests/test_measurement_iv_review.py; post-fix full suite: 1194 passed, 1 skipped, 2 xfailed. Checkpoint 14 is next. |
| 14 | Completed | Migrated MOKE measurement to standardized engine (`piec.measurement.moke.MokeMeasurement`). Subclassed `BaseMeasurement` with shared lifecycle, runner, and session support. Replaced constructor queries with zero-I/O architecture, positional instruments, and keyword-only settings. Enforced plain lowercase columns (`time`, `cycle`, `point`, `direction`, `source_output`, `field_calibrated`, `detector_voltage`, and optional `field_measured`, `field_time`) with compact JSON metadata units. Implemented paced cancellable pre-ramps, point-to-point transitions, and safing ramp to electrical zero, plus guaranteed attempt-all output disable even on zero-ramp error and custom shutdown handler support. Provided bounded live snapshots (`raw_window_points` limit) returning `MokeSnapshot`, cycle averaging excluding partial cycles, and full raw data recovery in `finally`. Updated golden CSVs (`moke_calibrated_golden.csv`, `moke_measured_golden.csv`) to standard 1-row metadata layout with `run_id`, `outcome`, `partial`, `save_requested`. Added `MokeMeasurement` and `MokeSnapshot` to `manifest.json` `migrated_families`. Created comprehensive unit/lifecycle/fault test suite in `tests/test_measurement_moke.py` (16 passed). Compatibility suite `tests/test_measurement_iv_moke_compatibility.py` (14 passed), MOKE tests `tests/test_moke.py` (49 passed), GUI tests `tests/test_moke_gui.py` (5 passed), and DMM contract tests (34 passed) all pass. Full test suite: 1210 passed, 1 skipped, 2 xfailed in 23.87s on Python 3.13.2. Checkpoint 15 is next. |
| 14 review | Completed | Fixed ownership bypasses; inherited full raw_data and shared snapshot lifecycle through snapshot_type; reset MOKE views before configuration and early abort; removed compatibility methods and constructor aliases; renamed shutdown_handler and migrated GUI/notebook/documentation consumers. MOKE GUI now uses MeasurementRunner and retains connections on unsafe shutdown. Added 10 regressions; focused 94 passed; full suite 1220 passed, 1 skipped, 2 xfailed. Checkpoint 15 is next; MOKE GUI hardening remains 16. |
| 15 | Completed | Hardened IV GUI interaction and ownership against race conditions and thread safety. Enforced single hardware writer rule across callbacks (blocking new runs or VISA refresh while active). Tracked GUI-created instruments and gated teardown on confirmed safety (SAFE/NOT_NEEDED) and worker death. Retained instrument connections and blocked window close when safety is UNSAFE. Coordinated window closing (WM_DELETE_WINDOW) with cooperative stop and non-blocking polling. Handled Stop-before-start zero-I/O aborts, dual queues, live bounded display views, complete terminal event data plotting, and error/recovery reporting. Added 8 comprehensive regression tests in tests/test_measurement_iv_gui.py (10 passed). Focused IV suites: 53 passed; full test suite: 1228 passed, 1 skipped, 2 xfailed in 26.38s on Python 3.13.2. Checkpoint 16 is next. |
| 15 review | Completed | Fixed deferred connection teardown after safety retry, recovery-path lookup from terminal RunRecord metadata, and pre-run plot-axis handling. Added three GUI regressions; focused IV GUI/review tests 26 passed. Default full run encountered missing host Tk icons.tcl in a PUND plotting test; Agg-backend full suite: 1231 passed, 1 skipped, 2 xfailed; command recorded in MEASUREMENT_HANDOFF.md. Checkpoint 16 remains next. |
| 16 | Completed | Hardened MOKE GUI interaction and ownership against race conditions, thread safety, and resource ownership. Enforced single hardware writer rule in refresh_instruments, browse_calibration, and run_measurement. Gated deferred connection teardown on confirmed safety (SAFE/NOT_NEEDED) before window destruction, retaining open connections on UNSAFE shutdown. Extracted recoverable staging paths from TerminalEvent.record.metadata on save failure. Hardened pre-run controls (trace toggles, geometry combobox, STOP, and redraw) as safe operations before initial run. Bound geometry selection to dynamic plot title updates. Added 8 comprehensive regression tests in tests/test_moke_gui.py (13 passed). Focused MOKE suites: 96 passed; full test suite (with Agg backend): 1239 passed, 1 skipped, 2 xfailed in 24.30s on Python 3.13.2. Checkpoint 17 is next. |
| 17 | PENDING | Physical hardware testing is unavailable in execution environment (Gemini reported an empty VISA discovery result; no physical execution recorded). Virtual and headless test suites pass (1249 passed, 1 skipped, 2 xfailed on Python 3.13.2) but do not validate physical hardware. Documented physical execution record template, safety requirements, staged MOKE validation protocol, and remaining hardware verification checklist in Section 13.1 and docs/physical_validation_iv_moke.md. Checkpoint 17 remains PENDING; wait for user direction before checkpoint 18. |
| 18 | Completed | Converted scientific hysteresis analysis to in-memory processing (`piec.analysis.hysteresis.process_hysteresis`). Standardized output schema to plain columns (`time`, `voltage`, `current`, `polarization`, `applied_voltage`) and declared units (`s`, `V`, `A`, `uC/cm^2`, `V`). Implemented explicit parameter validation, `HysteresisAnalysisResult` supporting tuple unpacking, in-memory plotting functions (`plot_hysteresis_pv`, `plot_hysteresis_iv`, `plot_hysteresis_traces`), and preserved `process_raw_hyst` as a temporary backward-compatible file bridge for unmigrated callers. Confirmed exact numerical equivalence with golden CSV (residuals <= 9.5e-17). Added 15 unit and regression tests in `tests/test_analysis_hysteresis.py`. Full test suite with Agg: 1264 passed, 1 skipped, 2 xfailed in 24.44s on Python 3.13.2. Checkpoint 17 physical validation remains PENDING. Checkpoint 19 is next. |
| 19 | Completed | Converted scientific PUND analysis to in-memory processing (`piec.analysis.pund.process_pund`). Standardized output schema to plain columns (`time`, `voltage`, `current`, `polarization`, `polarization_p_hat`, `polarization_p_star`, `polarization_p_hat_r`, `polarization_p_star_r`, `delta_polarization`, `applied_voltage`) and declared units (`s`, `V`, `A`, `uC/cm^2`, `uC/cm^2`, `uC/cm^2`, `uC/cm^2`, `uC/cm^2`, `uC/cm^2`, `V`). Implemented strict parameter validation (finite positive widths/delays/area/length/shunt, finite amplitudes/offset, strictly increasing time, nonnegative time offset, unit checks), `PundAnalysisResult` supporting tuple unpacking, in-memory plotting functions (`plot_pund_delta_p`, `plot_pund_traces`, `plot_pund_components`), and private temporary file bridge `_process_raw_3pp_file` for unmigrated `ThreePulsePund.analyze` caller until Checkpoint 20c. Confirmed exact numerical equivalence against golden CSV across all 10 quantities (residuals <= 1.33e-16). Added 49 unit, schema, numerical, and fault tests in `tests/test_analysis_pund.py`. Focused FE/PUND suites: 114 passed; full test suite with Agg: 1342 passed, 1 skipped, 2 xfailed in 24.72s on Python 3.13.2. Checkpoint 17 physical validation remains PENDING. Checkpoint 20a is next. |
| 20a | Completed | Standardized `DiscreteWaveform` base acquisition onto `BaseMeasurement` shared lifecycle with zero constructor I/O, WaveformReader oscilloscope adapter, strict trigger order, and attempt-all safing. Targeted suites: 294 passed; full suite with Agg: 1367 passed, 1 skipped, 2 xfailed. Checkpoint 17 physical validation remains PENDING. |
| 20b | Completed | Standardized `HysteresisLoop` onto `DiscreteWaveform` and `BaseMeasurement` with in-memory scientific processing (`process_hysteresis`), plain schema `hysteresis` v1 columns/units, multi-artifact plot staging (`_PV.png`, `_IV.png`, `_trace.png`), and runner-based GUI with in-memory plotting and safe close coordination. Retired private file bridge `_process_raw_hyst_file`. Full suite with Agg: 1393 passed, 1 skipped, 2 xfailed. Checkpoint 17 physical validation remains PENDING. |
| 20c | Completed | Standardized `ThreePulsePund` onto `DiscreteWaveform` and `BaseMeasurement` with in-memory scientific processing (`process_pund`), plain schema `three_pulse_pund` v1 columns/units, multi-artifact plot staging (`_dPvst.png`, `_trace.png`), and runner-based GUI with in-memory plotting and safe close coordination. Retired private file bridge `_process_raw_3pp_file` and removed `_LegacyWaveformSupport`. Full suite: 1411 passed, 1 skipped, 2 xfailed in 28.18s. Checkpoint 17 physical validation remains PENDING. Checkpoint 21 is next. |
| 21 | Completed | Hardened FE GUI (`FEMeasurementApp`) interaction and ownership across HysteresisLoop and ThreePulsePund. Enforced parameter validation strictly before instrument instantiation/connection. Enforced virtual selection pairing (rejection of mixed virtual/physical and empty addresses). Enforced single hardware writer rule (busy state blocks concurrent runs, VISA refresh, and dynamic parameter/measurement switching). Debounced Stop-before-start zero-I/O abort. Enforced cooperative active close with deferred window destruction, and retained open connections on unsafe shutdown. Drained display queue to avoid lag and mapped in-memory plot quantities with unit-derived axis labels. Added 43 comprehensive headless tests in `tests/test_measurement_fe_gui.py`. Targeted FE suite: 207 passed; full test suite with Agg: 1540 passed, 1 skipped, 1 xfailed in 31.58s on Python 3.13.2. Checkpoint 17 and Checkpoint 22 physical validations remain explicitly PENDING. |
| 22 | PENDING | Physical hardware testing unavailable in execution environment; FE physical record remains explicitly PENDING. |
| 23/23a (implemented early; original commit mislabeled 21) | Reviewed adapter implementation | Implemented AMR setup-role adapters (`FieldSource`, `FieldReader`, `TransportReadout`, `OrientationController`, `AMRSetupProfile`) with default preservation of manual lock-in settings (`readout_configuration="preserve"`), internal/external excitation, linear/table/native field modes, tolerance verification across zero/negative fields, and attempt-all safing. Repaired `AMR-FIELD-001` in `convert_field_to_voltage` and added `convert_voltage_to_field`. Added 37 comprehensive contract and virtual driver tests in `tests/test_amr_contract.py`. Full suite with Agg: **1478 passed, 1 skipped, 1 xfailed** in 28.54s on Python 3.13.2. Checkpoint 17 physical validation remains PENDING. |
| 24a | Completed | Standardized `MagnetoTransport` onto `BaseMeasurement` shared lifecycle, runner and session execution, excitation safing validation, attempt-all safe shutdown with connection retention, `stepper` and `voltage_calibration` parameters with backward-compatible aliases, target contract validation; full suite: 1564 passed, 1 skipped, 1 xfailed. Checkpoint 17 and Checkpoint 22 physical validations remain explicitly PENDING. |
| 24b | Completed | Migrated AMR acquisition, schema `amr` v1 with plain columns ('angle', 'field', 'x', 'y') and declared units, BaseMeasurement lifecycle, and consumers onto standardized MagnetoTransport base. Repaired defect AMR-ANGLE-001 (eliminated extra post-measurement motor step; motor endpoint strictly matches commanded angle). Preserved manual lock-in settings by default and enforced mandatory declared excitation shutdown policy before energizing. Atomic engine-owned publication and cooperative controls (Stop-before-start, pause/resume, in-flight Stop). Removed _LegacyMagnetoTransport and obsolete API tests. Full test suite with Agg backend: **1571 passed, 1 skipped** in 32.72s on Python 3.13.2. Checkpoint 17 and Checkpoint 22 physical validations remain explicitly **PENDING**. |
| 24c | Completed | Migrated AMR GUI (AMRApp in Measurements/AMR/amr_GUI.py) onto MeasurementRunner, non-daemon background execution, bounded live updates from display queue raw_window view, authoritative terminal data view from final_snapshot or data, and main-thread plotting with metadata-derived units from experiment.column_units ('angle (deg)', 'field (Oe)', 'x (V)', 'y (V)'). Preserved manual front-panel lock-in settings by default (initialize_lockin=False). Provided explicit setup path for real excitation shutdown: simulation-only policy (_simulation_excitation_shutdown) zeros reference voltage on virtual lock-in for all-virtual setups, while physical setups strictly require an explicit excitation_shutdown_handler before initializing drivers. Zero tolerance for no-op callbacks. Open instrument connections are retained on SafetyStatus.UNSAFE, and window close is deferred until worker exit and verified safety. Updated Measurements/AMR/AMR_testing.ipynb with explicit simulation excitation shutdown handler and metadata-derived dual-channel plotting. Updated manifest.json and test_measurement_amr_compatibility.py consumer inventory. Added 16 comprehensive tests in tests/test_measurement_amr_gui.py. Full test suite with Agg: **1597 passed, 1 skipped** in 44.45s on Python 3.13.2. Checkpoint 17 and Checkpoint 22 physical validations remain explicitly **PENDING**. |
| 25 | Completed | AMR GUI interaction/ownership hardening: settings/preflight validation (addresses, sweep direction, limits, sensitivity), Run/Pause/Stop/close coordination through common runner, startup failure handling (validation vs active ownership retention), terminal-before-worker-exit gating, UNSAFE connection retention & run button locking, auxiliary action resilience (stepper test, autodetect, refresh). Targeted GUI: 35 passed; focused: 215 passed; full repo suite: **1621 passed, 1 skipped** in 62.07s on Python 3.13.2. Checkpoints 17, 22, and 26 physical validations remain explicitly **PENDING**. |
| 26 | PENDING | AMR physical record: physical hardware testing is unavailable in execution environment (`pyvisa.ResourceManager().list_resources()` returned `()`); protocol template, staged execution procedures, and checklist documented in Section 13.3 and `docs/physical_validation_amr.md`. Record remains explicitly **PENDING**. Checkpoints 17, 22, and 26 physical validations are all PENDING. |


Checkpoint 16 review completed: geometry choices now restore independent session-local
setups, captured and validated before connection, with per-geometry shutdown handlers.
Unconfigured geometries start with explicit virtual demo defaults. Acquisition
geometry stays attached to snapshots instead of relabeling old data from the current
selector. Control events precede display rendering, bounded to one live frame per
poll; terminal frames take priority. Added 10 regression cases and removed the
scheduler race in the existing Stop-before-start test. Full suite with Agg:
**1249 passed, 1 skipped, 2 xfailed**. Physical hardware remains unverified.

Checkpoint 17 recorded: physical execution is **PENDING** as physical VISA instruments
are unavailable in this test environment. Virtual tests pass but do not substitute for
physical hardware validation. Staged validation protocol and remaining hardware checks
documented in Section 13.1 and `docs/physical_validation_iv_moke.md`.

Checkpoint 18 completed: scientific hysteresis analysis is now an in-memory pure function
`process_hysteresis` with plain schema columns, explicit units, parameter validation, and
tuple-unpacking result. Verified exact numerical and trace equivalence against golden CSV.
Maintained private `_process_raw_hyst_file` as a temporary bridge for unmigrated consumers. Checkpoint 17
physical validation remains explicitly **PENDING**.

Checkpoint 19 completed: scientific PUND analysis is now an in-memory pure function
`process_pund` with plain schema columns, explicit units, parameter validation, and
tuple-unpacking result. Verified exact numerical and trace equivalence against golden CSV.
Maintained private `_process_raw_3pp_file` as a temporary bridge for unmigrated consumers. Checkpoint 17
physical validation remains explicitly **PENDING**. Checkpoint **20a only** is next: DiscreteWaveform
base acquisition and consumers.

2R handoff: `assert_family_interface` selects reference or target structural checks using `migrated_families`; mark a family migrated only with its own execution/schema/safety tests. `assert_numerical_data_matches_reference` requires all expected columns (use `view="raw"` for raw FE), accepts reference or target names, and compares waveform time including negative pre-trigger values. Only MOKE's manifest-declared elapsed clocks may vary. `assert_golden_csv_matches` compares time by default; MOKE callers explicitly pass `time_columns=("time", "field_time")` for elapsed clocks. Keep waveform timing numerical. The uncommitted 2b MOKE golden calls have been adjusted to this explicit policy.

This document is the implementation contract for standardizing PIEC measurements. If a later implementation choice conflicts with this plan, the implementation must stop and the plan must be amended in a separate documentation commit before code continues.

Checkpoint 19 review corrections completed: manual alignment applies to pulse
windows; no-peak fallback uses the manual offset; AWG DC offset appears in nominal
applied voltage. Incomplete aligned pulse trains and invalid alignment options
are rejected. Existing complete-capture goldens remain unchanged. Targeted tests:
**83 passed**; full suite with Agg: **1355 passed, 1 skipped, 2 xfailed**.
Checkpoint **20a only** is next; physical checkpoint 17 remains **PENDING**.

Checkpoint 18 review corrections: fixed shunt metadata precedence, finite positive
parameter validation, integer counts, metadata container validation, explicit input
unit checks, strict timestamp ordering, and rejection of unrepresentable negative
offsets. Public analysis/plots use plain columns; only the private
`_process_raw_hyst_file` bridge translates the unmigrated caller's legacy CSV.
Remove that bridge at checkpoint 20b. Targeted suites: **99 passed**. Full suite
with Agg: **1293 passed, 1 skipped, 2 xfailed**. Checkpoint 19 only is next;
checkpoint 17 physical validation remains PENDING.

Checkpoint 20a review corrections completed: configuration failures now propagate
without acquisition; cancellation is checked between arm, enable and trigger.
Removed the migrated base's save_dir alias and isolated old direct capture/save
methods in private support used only by unmigrated subclasses. Full suite with
Agg: **1374 passed, 1 skipped, 2 xfailed**. Checkpoint **20b only** is next;
physical checkpoint 17 remains PENDING. See MEASUREMENT_HANDOFF.md.

Checkpoint 20b review corrections completed: DC offset is represented in nominal
applied voltage; plot staging cleans files/figures on failure and uses Agg figures
in workers. Hysteresis GUI uses the runner, in-memory snapshots, Stop and deferred
safe close with connection retention on UNSAFE shutdown. PUND GUI integration is
still part of 20c. Targeted tests: **63 passed**; full suite: **1393 passed,
1 skipped, 2 xfailed** with Agg. Checkpoint **20c only** is next; physical
checkpoint 17 remains PENDING. See MEASUREMENT_HANDOFF.md.

Checkpoint 20c completed: standardized ThreePulsePund onto BaseMeasurement lifecycle,
schema three_pulse_pund v1 with plain lowercase columns and canonical units, in-memory
process_pund processing, multi-artifact plot staging (_dPvst.png, _trace.png) when
save=True and save_plots=True, and runner-based GUI integration supporting live polling,
in-memory plotting, Stop, deferred close, and connection retention on unsafe shutdown.
Retired private file bridge _process_raw_3pp_file and removed _LegacyWaveformSupport.
Full test suite: **1411 passed, 1 skipped, 2 xfailed** in 28.18s on Python 3.13.2.
Checkpoint 17 physical validation remains explicitly **PENDING**. Checkpoint **21 only** is next.

Checkpoint 20c review corrections completed: nominal PUND pulse polarity matches
AWG generation for signed amplitudes; FE run options require actual booleans before
reservation/I/O. Targeted suites: **109 passed**; full suite with Agg:
**1440 passed, 1 skipped, 2 xfailed**. Checkpoint **21 only** is next;
physical checkpoint 17 remains PENDING. See MEASUREMENT_HANDOFF.md.

Checkpoint 21 completed: implemented AMR setup-role adapters (`FieldSource`, `FieldReader`,
`TransportReadout`, `OrientationController`, `AMRSetupProfile`) per Section 9.5. Preserved
the confirmed lab workflow with manual lock-in setting preservation by default
(`readout_configuration="preserve"`). Repaired `AMR-FIELD-001` in `convert_field_to_voltage`
(100 Oe gives 0.01 V with 10000 Oe/V default calibration) and added `convert_voltage_to_field`.
Standardized `convert_angle_to_steps` and `convert_steps_to_angle`. Added 37 comprehensive contract
and virtual driver integration tests in `tests/test_amr_contract.py`. `AMR-ANGLE-001` remains marked
`xfail` until Checkpoint 24b. Full test suite with Agg: **1478 passed, 1 skipped, 1 xfailed** in 28.54s
on Python 3.13.2. Checkpoint 17 physical validation remains explicitly **PENDING**.

Checkpoint 24a completed: standardized `MagnetoTransport` onto `BaseMeasurement`
shared lifecycle with zero constructor I/O, `stepper` and `voltage_calibration`
standardized parameters (and backward-compatible aliases `arduino` and `voltage_callibration`),
AMRSetupProfile setup role coordination, excitation safing validation before energizing,
attempt-all safe shutdown with connection retention on UNSAFE, and MeasurementRunner
integration. Manifest updated with `MagnetoTransport` in `migrated_families`.
Added 18 unit/lifecycle/fault tests in `tests/test_measurement_magneto_transport.py`.
Full test suite with Agg: **1564 passed, 1 skipped, 1 xfailed** (`AMR-ANGLE-001`) in 31.43s
on Python 3.13.2. Checkpoint 17 and Checkpoint 22 physical validations remain explicitly **PENDING**.

Checkpoint 24b completed: migrated AMR acquisition, schema amr v1 with plain columns ('angle', 'field', 'x', 'y') and declared units, BaseMeasurement lifecycle, and consumers onto standardized MagnetoTransport base. Repaired defect AMR-ANGLE-001 (eliminated extra post-measurement motor step; motor endpoint strictly matches commanded angle). Preserved manual lock-in settings by default and enforced mandatory declared excitation shutdown policy before energizing. Atomic engine-owned publication and cooperative controls (Stop-before-start, pause/resume, in-flight Stop). Removed _LegacyMagnetoTransport and obsolete API tests. Full test suite with Agg backend: **1571 passed, 1 skipped** in 32.72s on Python 3.13.2. Checkpoint 17 and Checkpoint 22 physical validations remain explicitly **PENDING**.

Checkpoint 24c completed: migrated AMR GUI (AMRApp in Measurements/AMR/amr_GUI.py) onto MeasurementRunner, non-daemon background execution, bounded live updates from display queue raw_window view, authoritative terminal data view from final_snapshot or data, and main-thread plotting with metadata-derived units from experiment.column_units ('angle (deg)', 'field (Oe)', 'x (V)', 'y (V)'). Preserved manual front-panel lock-in settings by default (initialize_lockin=False). Provided explicit setup path for real excitation shutdown: simulation-only policy (_simulation_excitation_shutdown) zeros reference voltage on virtual lock-in for all-virtual setups, while physical setups strictly require an explicit excitation_shutdown_handler before initializing drivers. Zero tolerance for no-op callbacks. Open instrument connections are retained on SafetyStatus.UNSAFE, and window close is deferred until worker exit and verified safety. Updated Measurements/AMR/AMR_testing.ipynb with explicit simulation excitation shutdown handler and metadata-derived dual-channel plotting. Updated manifest.json and test_measurement_amr_compatibility.py consumer inventory. Added 16 comprehensive tests in tests/test_measurement_amr_gui.py. Full test suite with Agg: **1597 passed, 1 skipped** in 44.45s on Python 3.13.2. Checkpoint 17 and Checkpoint 22 physical validations remain explicitly **PENDING**. Checkpoint **24d onward / 25** is next.

Checkpoint 25 completed: completed detailed AMR GUI interaction and ownership audit in `Measurements/AMR/amr_GUI.py`. Overrode `save_settings()` and `load_settings()` to persist `initialize_lockin_var` without frame corruption. Added preflight validation rejecting blank/whitespace addresses, simulation excitation shutdown on physical VISA resources, sweep direction mismatch (`total_angle * angle_step < 0`), step counts $> 1,000,000$, non-positive amplitude/frequency, negative measure time, and empty sensitivity. Driver and experiment setup errors cleanly close opened instruments and reset status to `"Idle"`. Runner start failure retains active ownership in `self._instruments` and keeps `_busy()` True if `not runner.can_close()`. Coordinated Run/Pause/Stop/close lifecycle through common runner, debounced Stop and Pause buttons, deferred window close until worker exit and verified safe shutdown, and blocked close on unclosed connections. Enforced terminal delivery prior to worker exit and retained open connections on `SafetyStatus.UNSAFE` (locking `run_button` and alerting operator). Added 15 new interaction and ownership audit tests in `tests/test_measurement_amr_gui.py` (total 35 tests, all passing). Full test suite with Agg backend: **1621 passed, 1 skipped** in 62.07s on Python 3.13.2. Checkpoints 17, 22, and 26 physical validations remain explicitly **PENDING**.

Checkpoint 26 recorded: AMR physical validation record is **PENDING** as physical VISA instruments are unavailable in this execution environment (`pyvisa.ResourceManager().list_resources()` returned `()`). Documented physical execution record template, acceptance criteria, 4-stage validation protocol (Stage 1: Stepper motor alone & AMR-ANGLE-001 endpoint check, Stage 2: Field source + readback alone & AMR-FIELD-001 calibration, Stage 3: Lock-in alone & manual settings preservation / excitation shutdown, Stage 4: Integrated low-field AMR measurement on reference sample), and observation log in Section 13.3 and `docs/physical_validation_amr.md`. All physical validation records (Checkpoint 17: IV/MOKE, Checkpoint 22: FE, Checkpoint 26: AMR) remain explicitly **PENDING**.


## 1. Purpose and non-negotiable constraints

Standardize IV, MOKE, discrete waveform/FE/PUND, and AMR through the same lifecycle, public execution interface, unit metadata, persistence, snapshots, and GUI ownership rules.

- Work incrementally, one reviewed commit checkpoint at a time. Replace old code when needed; do not implement all families in one commit.
- No measurement compatibility shims, old-format converters, duplicate old/new runners, or deprecation cycle are required. Keep useful names where convenient; update every repository consumer affected by a change.
- Constructor instruments may be positional; measurement settings and run options are keyword-only. Constructors perform no hardware I/O, output-directory creation, or hook calls.
- Measurements own procedures; Level 2 drivers own instrument contracts; setup adapters own wiring/calibration/safe policies; physics models own simulated samples; GUIs own presentation.
- One execution owner writes hardware. Safing de-energizes/halts but never closes instrument connections.
- Plain data column names and an explicit per-column units mapping apply to every family. Retain the one-row metadata/blank-line/data CSV structure as the chosen new format, not as a backward-compatibility requirement.
- Preserve numerical scientific results, calibration direction and units, acquisition meaning, and raw data recovery. Scientific algorithm changes need separate reference datasets and commits.
- Keep Python 3.9 support. Do not depend on ExceptionGroup.
- Generic DAQ behavior and unrelated driver APIs are outside scope except separately demonstrated contract defects. Do not put MOKE-specific behavior in generic virtual drivers. Use one physical/virtual MokeMeasurement through injection.
- Software safing is best effort under live Python, working communications, and finite driver timeouts; it does not replace a physical interlock.

## 2. Reference observations versus the target contract

### 2.1 Scientific references

Use immutable sources to establish numerical expectations: `9d9760242f44a79401626964f0122cc91b149c18` for existing families and `d1bac1ccf37e6578586336278c1ea36cf39b4722` as a MOKE prototype reference. These are observations, not frozen interfaces. MOKE has never been released. Historical test counts in the progress log do not verify this revised target.

### 2.2 Manifest and tests (checkpoint 2R)

The current `tests/fixtures/measurement_compatibility/manifest.json` and helpers may keep their paths initially to avoid incidental churn, but must become a target-standardization contract:

- Separate `reference_observations` (old signatures, names, side effects, fixture provenance) from `target_contract` (new API, schemas, unit maps and ownership). Old fields are not mandatory compatibility assertions.
- Add each family's explicit old-to-new column mapping for comparing numerical arrays in tests. This is a test aid, not a runtime legacy-file converter.
- Replace exact old-signature/default/return/re-export tests with tests for section 3's shared interface as each family migrates. All full runners return a DataFrame. Do not retain IV/FE/AMR None returns or the positional AMR configuration flag.
- Preserve meaningful golden numerical data and tolerances. New output goldens assert target plain headers, unit JSON, metadata shape, plot artifacts and selected field. Constructor-I/O, unsafe-output omissions, old filenames, and obsolete spellings are not invariants.
- Record scientific parameter units, schema order/dtypes, waveform alignment, calibration and plotting quantities. Validate every unit entry, including unitless fields; do not hide errors by broadly dropping metadata.
- Maintain an explicit migrated-family list. Tests for old families can remain temporarily while they still use old code; update them in that family's migration commit. Never claim an unmigrated family passes the new contract. No blanket skips/xfails: narrow expected failures require a demonstrated pre-existing defect and a repair checkpoint.
- Inventory all repository GUIs, notebooks, analysis functions, exports, examples and docs so none retain obsolete calls/column lookups after a family migrates.

### 2.3 Scope boundaries

Authorization to replace measurements does not authorize deleting saved datasets, changing scientific algorithms, or refactoring unrelated drivers. No runtime support for old measurement files is required. Keep numerical evidence from old files as test fixtures where useful. The package's generic virtual-driver compatibility fallback remains outside this measurement API decision until its own simulation checkpoints.

## 3. Target architecture and common API

The path is GUI/notebook -> MeasurementRunner (for background work) -> concrete measurement inheriting BaseMeasurement -> setup adapters -> Level 2 drivers. Simulation swaps the setup/instrument/physics wiring, not the measurement science.

### 3.1 One public lifecycle

BaseMeasurement owns these public wrappers; concrete classes implement protected hooks, not alternative runners:

- `run_experiment(*, on_update=None, save=True, save_partial=None, options=None)` returns the final or partial DataFrame for every family; errors follow section 5.
- `configure_instruments()`, `capture_data(*, on_update=None)`, `session(*, save=False, save_partial=None, options=None)`, `safe_shutdown()`, `request_stop()`, and `snapshot()` have the same ownership rules across families.
- `request_pause(paused=True)` is a capability-gated cooperative control. AMR supports it; unsupported families reject before changing state. No public mutable abort/pause booleans.
- Read-only `run_state`, `safety_status`, `last_run_record`, and `run_records` expose lifecycle results. `raw_data` retains full raw acquisition after completion; `data` is the analyzed result, or raw partial data on abort/failure. Snapshots contain bounded copies.
- `filename` names only a successfully published completed CSV, `partial_filename` names incomplete output, and `column_units` maps the columns of `data` to units. Keep separate raw/view mappings when processed or snapshot columns differ.

Use the same immutable validated RunRequest for synchronous and runner execution. Copy/validate options before reservation; reject unknown options before I/O. An AMR-specific choice such as skipping lock-in configuration is `options={"configure_lockin": False}`, never an extra positional runner argument. Freeze options so later caller mutation cannot alter the run. UI callbacks never issue hardware commands.

All constructors use explicit instruments/setup dependencies with keyword-only settings; standardize `stepper` and `voltage_calibration` in place of `arduino` and `voltage_callibration`. Retain descriptive class names where useful without requiring aliases. Keep helpers only when they serve an actual procedure; hardware helpers require the command owner and may not bypass the base. Use `shutdown_handler` for an injected MOKE callback so it cannot shadow `safe_shutdown()`.

Use static final annotations and tests to prohibit migrated subclasses overriding base-owned wrappers. In-memory base initialization must not call overridable hooks; live identities are collected during protected configuration.

### 3.2 Run records and runner

MeasurementRunner reserves synchronously and starts one non-daemon worker; it owns no science or instrument writes. RunRecord is immutable and includes UUID/generation, start/end times, terminal outcome, save policy/artifacts, snapshot sequence, safety report, primary error phase/type/message, secondary cleanup/persistence/reporting errors and schema/version. Keep exception objects/tracebacks in memory only; persist scalar summaries. Replace heterogeneous history behavior with `run_records` and update consumers.

## 4. Run lifecycle and concurrency contract

### 4.1 States

Use these states consistently:

| State | Meaning |
|---|---|
| `IDLE` | No run has been reserved |
| `STARTING` | A run is reserved but its worker may not have begun |
| `CONFIGURING` | Instrument setup is in progress; outputs must remain disabled |
| `RUNNING` | Acquisition may energize the setup |
| `STOPPING` | Cancellation is latched and acquisition is yielding to safing |
| `SAFING` | Required shutdown actions are being attempted |
| `ANALYZING` | Hardware has been safed; successful raw data is analyzed |
| `SAVING` | A final artifact or incomplete-run artifact is being staged/published |
| `COMPLETED` | All requested success-path work finished |
| `ABORTED` | Stop won, safing succeeded, and required partial persistence succeeded |
| `FAILED` | A required operation failed |

The only legal forward transitions are:

| From | To |
|---|---|
| `IDLE`, `COMPLETED`, `ABORTED`, `FAILED` | `STARTING` for a newly reserved generation |
| `STARTING` | `CONFIGURING`, `STOPPING`, or `FAILED` if worker launch fails |
| `CONFIGURING` | `RUNNING`, `STOPPING`, or `SAFING` after an error |
| `RUNNING` | `STOPPING` or `SAFING` |
| `STOPPING` | `SAFING`, or `ABORTED` directly when no I/O began |
| `SAFING` | `ANALYZING` on a clean completed capture, `SAVING` for requested incomplete persistence, or a terminal state |
| `ANALYZING` | `SAVING`, `COMPLETED` when saving was not requested, or `FAILED` when no incomplete save is requested after an error |
| `SAVING` | `COMPLETED`, `ABORTED`, or `FAILED` according to the recorded outcome |

No other transition is permitted. State changes use one validation helper so measurement subclasses and GUIs cannot assign states directly.

Safety is separate from run state:

| Safety status | Meaning |
|---|---|
| `UNKNOWN` | No conclusion is available yet |
| `NOT_NEEDED` | The run ended before any instrument I/O could occur, or the setup has no hazardous action |
| `SAFING` | Shutdown attempts are in progress |
| `SAFE` | Every required software shutdown action reported success |
| `UNSAFE` | At least one required shutdown action failed or could not be confirmed |

Thread termination never implies `SAFE`. A shutdown report also records whether the safe state was command-only or independently read back; `SAFE` is not a claim that software physically measured zero field/current when the setup has no such readback.

### 4.2 Run reservation closes the Stop/start race

The GUI reserves synchronously before starting a worker. Reservation, under the state lock, must:

1. accept only `IDLE` or a terminal state;
2. reject a nested or concurrent run;
3. clear the stop event;
4. create a full 128-bit UUID and monotonically increasing local generation;
5. set `STARTING`;
6. return an opaque token bound to that generation.

Only after reservation does the GUI start a non-daemon worker with the token. The worker validates the token before I/O. A stale worker can never execute a newer reservation.

If Stop is pressed after reservation but before the worker starts, `request_stop()` latches the event while state is `STARTING`; the worker produces an aborted terminal record without touching hardware. If thread creation itself fails, the runner finalizes that reservation as `FAILED` with safety `NOT_NEEDED`.

A synchronous `run_experiment()` performs the same reserve-then-execute sequence internally.

### 4.3 Legal stop behavior

`request_stop()` and AMR's pause request are the only cross-thread control writes; reservation and copy-only state/snapshot reads are also supported. No such operation writes hardware. Stop's state behavior is:

| Current state | Result |
|---|---|
| `STARTING`, `CONFIGURING`, `RUNNING` | Set the event and transition to `STOPPING` |
| `STOPPING` | Leave state unchanged; request is idempotent |
| `SAFING`, `ANALYZING`, `SAVING` | Leave state unchanged; do not move backward |
| `IDLE` or terminal | Ignore the request |

The stop event is cleared only by a successful new reservation. The state lock is never held across instrument I/O, callbacks, waits, analysis, or disk access.

Use `request_stop()` and `request_pause()` rather than mutable control attributes. Pause retains the configured field, acts at a documented safe acquisition boundary, and waits cancellably. Stop wakes a paused worker; reservation resets pause. Update the AMR GUI controls in its migration checkpoint.

Reservation also rejects while an idle `safe_shutdown()` owns the command lease. Acquire/release that lease under the same lock as run reservation, without holding the lock across I/O. Otherwise a new run can race with idle shutdown. Reject duplicate execution of the same token, not just stale generations. Reset current-run data, errors, and filenames at reservation so Stop-before-start cannot return a previous run's data; prior results remain in prior run records.

Acquisition delays use cancellable waits. Shutdown delays use a separate non-cancellable pacing function; a latched Stop must not collapse a safe ramp's required delay.

When capture returns, the worker takes the state lock to establish a completion linearization point. If Stop obtained the lock first, the outcome is aborted. If capture completion obtained it first, a later Stop does not convert completed acquisition into an abort.

### 4.4 Canonical full-run ordering

Every full run follows this order:

1. Reserve and enter `STARTING`.
2. If Stop is already latched, finalize as aborted without I/O.
3. Enter `CONFIGURING` and configure instruments with outputs disabled.
4. Atomically choose `RUNNING` or `STOPPING` based on cancellation.
5. Capture data. A callback failure is an acquisition failure.
6. Enter `SAFING` immediately after configuration/acquisition finishes or raises.
7. Attempt every required shutdown action and emit an immediate safety alert if any required action fails.
8. Only when acquisition completed and safing succeeded, enter `ANALYZING` and analyze an untouched copy/staging representation of raw data.
9. If saving was requested, enter `SAVING` and publish the final artifact atomically. Otherwise record `save_requested=false` and leave the final filename unset.
10. On abort or failure, skip scientific analysis and optionally stage an explicitly incomplete raw artifact according to the save policy.
11. Record diagnostics/history, choose exactly one terminal state, and emit exactly one terminal event.
12. Re-raise the selected error, if any, only after safing and finalization attempts finish.

`COMPLETED` is never assigned before required analysis and saving succeed.

### 4.5 Notebook and standalone operations

Piecewise notebook use is supported without creating multiple cleanup owners:

- `with measurement.session():` creates one reservation, records the calling thread as owner, and owns exactly one shutdown boundary on exit.
- Within that session, public configure/capture wrappers recognize the owner and do not create nested scopes.
- Nested sessions and `run_experiment()` inside a session are rejected.
- Cross-thread hardware-bearing calls are rejected.
- A session supports one capture operation; repeated acquisition belongs inside the concrete capture hook or in separate sessions.
- After a capture, clean session exit safes first and then runs analysis; it saves only when the session was explicitly given `save=True`. A configuration-only session has no analysis step.
- A successful configuration hook must leave outputs disabled and motion stopped.
- Standalone `configure_instruments()` uses a transient operation scope. On partial configuration failure it attempts safing before re-raising; on success its disabled-output postcondition is verified where the adapter supports readback.
- Standalone `capture_data()` uses a transient capture scope and always attempts safing. Inside a run/session it delegates without a second cleanup.
- Each standalone scope reserves and finalizes its own generation, emits one terminal event, and does not implicitly analyze or save.
- Direct calls to raw instrument objects are outside this guarantee and must be documented as such.

All families, including AMR, use the same standalone no-save rule. Optional incremental persistence belongs to the engine and follows the run's save policy, writing partial artifacts only. Single-point hardware helpers are owner-scoped; manual workflows use a session. Remove AMR's measurement-owned per-point file publication.

Configuration-only scopes transition from `CONFIGURING` through `SAFING` to `COMPLETED`; capture-only scopes also pass through `CONFIGURING` for prerequisite validation without silently repeating legacy configuration. The successful standalone configuration path uses the same cleanup boundary. Retain validated settings for subsequent capture (including MOKE's configured readiness), while marking outputs disabled. Owner tracking covers every public hardware helper, not just the four base wrappers.

### 4.6 Outcome and persistence matrix

Default `save_partial` follows `save`: no files are written when `save=False` unless the caller explicitly requests partial persistence.

The matrix describes the common execution result. Every full runner returns a DataFrame as specified in section 3. Every partial-save entry, including shutdown and final-publication failures, is conditional on `save_partial` and available raw rows. `save=False` also suppresses plot-file writes even when `save_plots=True`; it does not suppress in-memory scientific analysis.

| Event | Analysis | Artifact policy | Final state | Caller receives |
|---|---|---|---|---|
| Clean success, `save=True` | Run | Publish completed CSV | `COMPLETED` | Data |
| Clean success, `save=False` | Run | No file; `filename=None` | `COMPLETED` | Data |
| Cooperative Stop with rows | Skip | Publish `.partial.csv` if requested | `ABORTED` if save succeeds | Partial data |
| Stop before I/O | Skip | No data artifact | `ABORTED` | Empty/current data |
| Configuration failure | Skip | No data file by default; diagnostics remain in the run record/event | `FAILED` | Original error |
| Acquisition/callback failure | Skip | Publish raw `.partial.csv` if requested | `FAILED` | Original error |
| Shutdown failure | Skip | Attempt raw `.partial.csv`; alert immediately | `FAILED` | Earlier error, otherwise `HardwareSafetyError` |
| Analysis failure | Failed | Publish untouched raw `.partial.csv` if requested | `FAILED` | Analysis error |
| Final publication failure | Already ran | Attempt a separately named raw `.partial.csv` | `FAILED` | Publication error |
| Required partial save failure after Stop | Skip | Data remains in memory | `FAILED` | Persistence error |

`self.filename` refers only to a successfully published completed artifact. Add `partial_filename` for incomplete data. The terminal event carries both.

## 5. Safety, error precedence, and instrument ownership

### 5.1 Setup-specific safe policy

The base cannot assume every instrument has a voltage zero, an analog output, or a motor. It invokes a concrete/setup shutdown hook through an attempt recorder.

A safe policy declares ordered required actions such as bounded ramp to the setup's electrical safe value, output disable, or optional motor stop. Important rules are:

- electrical safe output and zero physical field are distinct concepts;
- calibration is applied exactly once;
- output disable is attempted even if ramping fails;
- shutdown never enables an output;
- shutdown never calls `close()` or disconnects a session;
- motor halt is used only when the driver/adapter advertises it;
- repeated shutdown attempts do not create an unsafe action, though repeated communication failures are still reported.

MOKE's injected `shutdown_handler` belongs to the setup shutdown policy. Normal return reports success; an exception leaves safety unconfirmed. The default policy ramps to electrical zero and disables output. GUI Stop calls `request_stop()`; idle manual safing calls `safe_shutdown()`. Remove redundant `shut_off()` compatibility paths.

A non-owner call to public `safe_shutdown()` during an active run must not write hardware. It latches cooperative Stop and raises a `RuntimeError` stating that shutdown is deferred to the execution owner; it never reports the hardware as safe. The execution owner performs and reports the actual shutdown. When no run is active, the caller may execute `safe_shutdown()` synchronously as the temporary command owner.

### 5.2 Shutdown timing requirements

Every energizing setup policy defines:

- finite source/read/query timeouts configured before energizing;
- a positive maximum output step;
- a finite ramp delay independent of cancellation;
- a total expected shutdown deadline;
- a final disable attempt even after a ramp error;
- setup-specific manual interlock instructions for the GUI.

The deadline is diagnostic, not magical preemption: Python cannot interrupt a native driver call that ignores its timeout. Hardware validation therefore includes timeout behavior and a physical emergency procedure.

### 5.3 Python 3.9-compatible failure handling

Cleanup attempts catch `BaseException`, record the failure, and continue through all required actions. If `KeyboardInterrupt` or `SystemExit` is the first primary event, it is deferred until those attempts finish and then re-raised unchanged. If one occurs later inside cleanup after an earlier primary error, it is recorded as a secondary cleanup failure and the earlier primary keeps precedence.

The engine records the first primary failure as exception, original traceback, and phase. It does not mutate `__context__` and does not use `ExceptionGroup`.

Error precedence is deterministic:

1. A configuration, acquisition, callback, analysis, or final-save error remains the primary error and is re-raised with its original traceback.
2. All cleanup and secondary persistence failures remain prominent in the safety report, last-run record, terminal event, and logs; they do not mask that primary error.
3. If ordinary cleanup fails without an earlier primary error, raise `HardwareSafetyError` containing the full shutdown report. A cleanup-only `KeyboardInterrupt` or `SystemExit` is instead re-raised unchanged after the remaining actions are attempted.
4. If a cooperative abort is otherwise clean but a required partial save fails, the run becomes `FAILED` and raises the persistence error.
5. A run-record/event reporting failure is recorded when possible and never replaces an earlier scientific or safety error.

The shutdown report lists every required action, whether it was attempted, whether it succeeded, its duration, any error, and whether independent readback was available. `SAFE` requires success of all required software actions; “thread ended” is insufficient, and “command sent” is distinguishable from a readback-verified state.

### 5.4 Connection ownership

Measurements never close instruments. Connection teardown belongs to whoever created the instrument:

- notebook/user-injected instruments remain open until the user closes them;
- a GUI closes only instruments it created;
- GUI-owned instruments are closed only after the worker is dead, the terminal event has arrived, and safety is `SAFE` or `NOT_NEEDED`;
- if safety is `UNSAFE` or unknown, the GUI preserves the warning and manual-interlock instructions. A forced exit requires explicit acknowledgement and must not be described as safe.

## 6. Snapshots, events, and GUI contract

### 6.1 Snapshot model

A common snapshot contains:

- run ID, monotonically increasing sequence, state, completed steps, and optional total steps;
- a status message;
- fresh bounded DataFrame views such as `raw_window`, `last_cycle`, or `cycle_average`.

A frozen dataclass alone does not make DataFrames immutable, so every exposed view is a copy. Acquisition stores rows efficiently and must not rebuild/copy the full DataFrame for every point. Full data is materialized only at bounded checkpoints, cycle boundaries, or completion as appropriate.

MOKE supplies bounded raw/last-cycle/average views through the common snapshot mapping; optional convenient properties use the same standardized columns.

MOKE `.raw` is already the bounded `raw_window_points` window, not the full dataset. Preserve that meaning and the existing last-cycle/average shapes. Copy views under a short snapshot-publication lock; do not iterate buffers while another thread mutates them. Terminal snapshots remain bounded; full raw data is available separately after completion.

### 6.2 Two event paths

Use two distinct paths:

- a bounded, coalescing display queue for high-rate snapshots; dropping an older display snapshot is allowed;
- an unbounded/non-droppable control path for state changes, safety alerts, and one terminal event.

The terminal event contains the final deep-copied snapshot, outcome/state, safety report, final and partial filenames, primary error summary, and secondary failures. Including the authoritative final snapshot prevents a terminal event from overtaking the final display state.

### 6.3 GUI threading and close behavior

All measurement GUIs continue to use the repository's `MeasurementApp` styling and layout conventions. Standardization changes worker behavior, not the visual language.

Rules:

- no Tk or Matplotlib widget call occurs from the worker;
- no GUI callback issues an instrument command while a run is active;
- workers are non-daemon;
- Run reserves synchronously before thread start;
- Stop only calls `request_stop()`;
- window close sets a closing flag, requests stop, disables controls, and continues polling through `after()`;
- Tk callbacks never block on `join()`;
- the window closes only after worker termination, terminal delivery, and confirmed safety;
- queue saturation cannot discard terminal or safety information;
- exceeding the expected stop deadline displays the setup's physical-interlock procedure but never launches a second writer;
- GUI Stop is labeled/described as cooperative software stop, not a physical emergency stop.

All families use presentation helpers for interactive plots. Synchronous main-thread notebooks may render; runner workers never invoke Tk, interactive pyplot, show(), or canvas updates. Deliver plot data to the UI. Saved artifacts use noninteractive figures. Update notebook plotting calls and file-artifact tests together; preserve plotted physical quantities and numerical traces.

## 7. Standard schemas and units for every measurement

### 7.1 Metadata and display

Every saved file has one metadata row, a blank separator, and the data table. Required scalar metadata: `measurement_schema`, `measurement_schema_version`, `run_id`, `outcome`, `partial`, `save_requested`, and `column_units_json`, plus scientific parameters, calibration, instrument identities and acquisition settings.

Column names never contain units. `column_units_json` is sorted compact JSON containing every saved column exactly once. Values are canonical unit strings, or JSON null for unitless indices/categories. Resolve runtime units before serializing; never save placeholders. `json.loads()` must recover the exact mapping. Raw, processed, and snapshot views each have units for their own columns. Axis labels combine the quantity and metadata unit; consumers must not parse units from headers or assume all fields share one unit.

This defines each family's first standardized schema, version 1; set distinct names `iv_sweep`, `moke`, `discrete_waveform`, `hysteresis`, `three_pulse_pund`, and `amr`. These names distinguish the new standard from old unversioned formats. No runtime converters are required. Future standardized schema changes require an explicit version decision.

### 7.2 Exact target columns

| Family/view | Ordered columns | Units |
|---|---|---|
| IV | `voltage`, `current` | V, A |
| AMR default lockin_xy | `angle`, `field`, `x`, `y` | deg; setup-declared field unit; signal-reader-declared X/Y units |
| AMR optional field-readback suffix | `field_measured`, `field_time` | setup-declared measured-field unit; s |
| AMR additional transport modes | `angle`, `field`, then `resistance` or `voltage`, `current`; optional field-readback suffix | deg; field unit; ohm or V/A. See section 9.5 for separate implementation checkpoints. |
| MOKE raw/final | `time`, `cycle`, `point`, `direction`, `source_output`, `field_calibrated`, `detector_voltage` | s; null; null; null; calibration output unit; calibration field unit; V |
| MOKE optional suffix | `field_measured`, `field_time` | calibration field unit; s |
| Discrete waveform / FE raw | `time`, `voltage` | s, V |
| Hysteresis processed | raw columns then `current`, `polarization`, `applied_voltage` | A, uC/cm^2, V |
| Three-pulse PUND processed | raw columns then `current`, `polarization`, `polarization_p_hat`, `polarization_p_star`, `polarization_p_hat_r`, `polarization_p_star_r`, `delta_polarization`, `applied_voltage` | A; uC/cm^2 for each polarization; V |

PUND mappings are literal: `P^` -> `polarization_p_hat`, `P*` -> `polarization_p_star`, `P^r` -> `polarization_p_hat_r`, `P*r` -> `polarization_p_star_r`, `dP` -> `delta_polarization`. Preserve the existing mathematical definitions, order and values; do not infer a new scientific meaning from these identifiers. WaveformReader's normalized result must use `time` and `voltage` too.

AMR's `field` remains the requested calibrated field; do not relabel it measured field. Its reader must declare X/Y physical units explicitly (V only for voltage readings). MOKE keeps calibrated and measured field distinct. Calibration units may vary without changing names; never relabel numerical values without conversion.

MOKE snapshot/average columns use these same identifiers. `cycles_averaged` is unitless. `field_column` selects `field_measured` or `field_calibrated` according to field-selection mode. Full raw data remains recoverable independently from processed data; analysis receives a copy or unpublished staging representation. File-oriented FE analysis becomes in-memory functions with explicit data and metadata inputs; old path wrappers are not required.

### 7.3 Golden fixtures

Keep deterministic numerical goldens for all families. Compare reference arrays through explicit test-only column mappings and documented tolerances. New output fixtures use the target headers, schema/version and units. Never regenerate numerical goldens merely to hide a changed result. Update producer, analyzer, GUI, notebooks and tests together in a family's vertical slice; do not only rename fixture headers.

## 8. Windows- and SMB-aware persistence

PIEC guarantees that it never intentionally presents a partially written completed `.csv`. It does not claim universal power-loss durability or universal atomic rename semantics on every SMB server.

### 8.1 Write and publish rules

1. Generate a full UUID for the run and use it in staging/checkpoint ownership.
2. Create staging files in the destination directory with `tempfile.mkstemp()`; do not hold an open `NamedTemporaryFile` across rename on Windows.
3. Write metadata, the blank separator, and data through one UTF-8 text handle. Flush and `fsync` that handle, then close it before publication.
4. Add a handle-based writer. Update repository users of the path-based helper to the handle-based writer; do not compose an atomic write from the current helper's three independent opens.
5. Use one documented filename grammar for all families: `{index}_{measurement_schema}.csv`, with one basename for plots; no old filename adapter is required. Claim a candidate with an exclusively created hidden marker at a deterministic path derived from the candidate basename; store the full owner UUID inside it. A UUID in the marker filename alone would let competing writers reserve the same candidate. On collision choose the next index. Never reserve by creating an empty completed-looking CSV. A stale marker is not reusable until the explicit age/ownership recovery policy approves it.
6. Publish through one tested `atomic_publish_no_replace` abstraction. It must reject an existing target and never silently overwrite it. `Path.replace()` is not a no-replace operation.
7. Where a filesystem cannot provide the required no-replace primitive, strict mode fails clearly and leaves data in memory/staging. Any opt-in weaker mode must be labeled collision-resistant, never collision-proof.
8. Assign `self.filename` only after the completed CSV is published successfully.
9. Readers ignore `.partial` and staging files.

### 8.2 Multi-artifact measurements

For measurements that create plots:

- reserve one shared basename for the artifact bundle;
- stage every expected artifact with run-owned UUID names;
- publish side artifacts first and the completed CSV last, using the CSV as the completion marker;
- never overwrite an existing side artifact;
- on failure, remove only artifacts proven to belong to the current reservation and record any orphan cleanup failure.

Cross-file publication is not claimed to be transactional. Publishing the CSV last ensures normal PIEC readers do not treat an incomplete bundle as complete.

### 8.3 Partial data and recovery

- In-progress checkpoints and terminal incomplete data use a full-run-ID `.partial.csv` name and never look like completed output.
- Replacing the checkpoint owned by the same run is an intentional overwrite and is separate from first publication.
- Abort/failure leaves `self.filename=None` and records `partial_filename`.
- On a save error, in-memory data remains available and recoverable staging paths are reported.
- Stale partial/reservation cleanup is explicit, ownership-checked, and age-gated; it never deletes an unknown file automatically.

### 8.4 Persistence tests

Tests cover:

- simultaneous writers selecting the same filename candidate;
- pre-existing final and side-artifact targets;
- failures during metadata, data, flush, sync, close, and publication;
- non-ASCII metadata and JSON unit round trips;
- interrupted checkpoints and stale reservations;
- cleanup ownership;
- local NTFS behavior;
- the lab SMB path only when explicitly configured.

SMB results are recorded for the tested server/filesystem and are not generalized to all network shares.

## 9. Driver and setup-adapter prerequisites

Measurement code must not infer contract parity from similar method names. Each advertised driver used by a slice receives a shared contract test before that measurement migrates.

### 9.1 Sourcemeter

Audit the applicable Level 2 source/sense surface, including output control, source/sense selection, source voltage/current, both compliance modes, voltage/current source configuration, quick read, and voltage/current/resistance getters.

`Sourcemeter`, `VirtualSourcemeter`, and concrete drivers (such as `Keithley2400`) standardize on explicit channel-first signatures with default `channel=1` across all applicable methods, including the safety-critical output-disable path (`output(channel=1, on=True)`). Repository consumers and measurement code pass arguments using explicit keywords (e.g., `source.set_source_voltage(channel=1, voltage=5.0)`, `source.output(channel=1, on=False)`).

By user decision, no legacy argument-compatibility layer, positional translation, or deprecation shim is maintained. Native Python argument binding applies; duplicate, unknown, or excessive arguments raise `TypeError`. Numeric setters reject missing values without interpreting the channel as a value. Calls specifying an invalid channel (or positional arguments that bind to invalid channels, such as single-argument floats or booleans) are rejected before state changes or transport writes.

### 9.2 DMM

Before the MOKE slice, contract-test voltage configuration and reading across every advertised DMM intended for that setup: sense-function selection, DC coupling, optional range/integration settings, `get_voltage()`, and finite/non-finite return handling. Unsupported optional configuration is capability-gated explicitly; it is not inferred by catching arbitrary driver errors. `VirtualDMM` must obey the same call and scalar-return contract.

### 9.3 AWG

Two independent base-driver defects require separate fixes and tests:

- un-indent `Awg.output_trigger()` so it is actually a class method;
- apply `trigger_source` when it is not `None` in `configure_trigger()`.

Then audit concrete AWGs for real manual-trigger support. Manual triggering is required only for measurements whose chosen synchronization mode needs it; otherwise it is capability-gated. Contract tests also verify waveform selection, amplitude, offset, frequency, trigger ordering, and disabling every used channel on every exit.

#### 9.3.1 Concrete AWG and Adapter Trigger Audit Inventory

This inventory describes current Python implementations, not the absence of features
in hardware. Empty setters are current observations, not a desired permanent contract;
update their characterization tests when implementing a driver. Mock command assertions
verify emitted commands, not physical operation or every synchronization mode.
Manual/software initiation of a waveform and a physical trigger-output connector are
distinct capabilities and require separate verification.

Manufacturer evidence: the [33220A User's Guide](https://www.keysight.com/no/en/assets/9018-04437/user-manuals/9018-04437.pdf)
describes internal, external, front-panel and software/bus triggers for sweep/burst;
the [33500 Series User's Guide](https://www.keysight.com/us/en/assets/9018-03290/user-manuals/9018-03290.pdf)
describes external and manual sweep/burst triggering;
the [DG1000 User's Guide](https://eu.rigol.com/eu/Images/DG1000_UserGuide_EN_tcm30-2774.pdf)
and [DG4000 User's Guide](https://www.rigol.com/dam/global/downloads/brochures/en/user-manual/waveform-generators/DG4000_UserGuide_EN.pdf)
describe external/manual triggering. These establish hardware capabilities, not mappings
for every generic setter. Implement any missing driver support in a separate reviewed
checkpoint using the exact model's programming documentation and command tests.
For SDG2000X adjustable external trigger threshold support, this audit makes no hardware
claim. DaqAsAwg exposes external pulse output through the general DAQ API;
this does not implement triggered analog playback.

The user subsequently authorized implementing the missing hardware-driver capabilities
as a separate commit before checkpoint 5. The current command table, manufacturer
references, prerequisites and remaining limits are in [AWG trigger support](docs/awg_trigger_support.md).

| Driver | Current implementation |
|---|---|
| VirtualAwg | Simulated trigger and source/level/slope/mode state; no trigger-count claim |
| Keysight81150a | Existing ARM configuration and `:TRIG`; retained command tests |
| SDG2000X | Existing burst source/slope/mode and channel-1 manual trigger; adjustable level remains unimplemented |
| Agilent33220A | Source/slope/triggered-or-gated burst plus bus trigger; level requests raise explicitly |
| Agilent33500 | Source/slope/triggered-or-gated burst, programmed trigger level, bus trigger |
| RigolDG1000 | Identified legacy/Z dialect; source/slope/burst mode; Z bus trigger; legacy software launch unverified and channel-1-only burst/sweep |
| RigolDG4000 | Separate burst/sweep source and slope, burst mode, bus trigger |
| DaqAsAwg | Explicit external pulse configuration through general DAQ API: USB1208HS TMR hardware width or software DIO (including USB231); triggered analog playback remains unsupported. See docs/daq_trigger_output.md. |

No new physical verification is claimed. Missing hardware support must not be inferred
from a missing Python method. The original no-op characterization assertions were
replaced for the implemented drivers; they are not permanent compatibility requirements.


### 9.4 Oscilloscope

Existing `get_data()` signatures and returned column names differ. Measurements use a `WaveformReader` setup adapter that returns exactly `time` and `voltage` for a requested channel. The adapter maps driver-specific `Time`, `Voltage`, or `Voltage_CH{channel}` fields, validates finite numeric equal-length arrays, and records actual channel/sample information.

Do not add a fictitious `read_waveform()` requirement to every oscilloscope driver, and do not make scientific measurement code parse driver-specific tables.

### 9.5 General AMR setups and the existing four-instrument profile

Checkpoint 25 completed: comprehensive AMR GUI ownership and interaction audit.
Covered settings/preflight address, sweep direction, interval count, and sensitivity
validation; Run/Pause/Stop/close coordination through common runner; startup failure
handling (validation vs active ownership retention); terminal delivery prior to
worker thread exit; UNSAFE connection retention with run button locking; and
auxiliary action (stepper test, autodetect, refresh) hardening. Preserved notebook
execution order, virtual-only shutdown checks, NOT_NEEDED abort cleanup, and display
error handling. Targeted GUI suite: 35 passed; focused suite: 215 passed; full
suite with Agg: 1621 passed, 1 skipped in 62.07s. Next is checkpoint 24d onward
(additional AMR electrical adapters) / 26. Physical 17/22 remain PENDING.

24c follow-up review restored executable notebook setup/acquisition/plot ordering
and a runtime-checked all-virtual shutdown policy. Notebook results are read in
memory. GUI rendering errors cannot prevent terminal cleanup; empty results clear
stale plots. Test Stepper closes on query failure; failed closes retain references
for explicit retry. Physical 17/22 remain PENDING.

**24b review corrections:** snapshots now bound raw_window (default 100 points)
while terminal data and persistence retain full acquisition. All requested and
quantized motor positions are preflighted; descending sweeps are supported.
Settling occurs once in a cancellable wait; blocking driver motion still requires
the driver to return before Stop can finish. Stop during averaging discards the
unfinished point without extra reads. GUI/notebook no-op shutdown callbacks were
removed; a real declared policy is required before physical execution. AMR no
longer accepts save_dir/live_plot/plot_config. Next is 24c presentation/runner
integration, followed by checkpoint 25's detailed GUI ownership audit.

**24a review corrections:** public MagnetoTransport is isolated from private
unmigrated AMR support. No legacy direct I/O methods or parameter aliases are on
the public base. Excitation shutdown validation is mandatory before any run;
the require_excitation_safing bypass is removed. Field commands and strict options
are validated before excitation configuration, reader/identification failures
propagate, and all shutdown roles are attempted. Supplied profile policy and
field units are preserved; optional measured-field/time data and separate
calibration provenance are recorded. Pause before acquisition retains field;
Stop wakes it. Checkpoint 24b must migrate AMR onto this base and remove private
_LegacyMagnetoTransport and obsolete API characterization tests while retaining
scientific and fault regressions. Physical 17/22 remain PENDING.

Checkpoint 21 review corrections completed: FE measurement selection is locked
while busy and queued selection events restore the active type. Failed startup
without active ownership resets terminal-wait state and restores idle controls.
Gated Hysteresis/PUND Stop-before-start tests require ABORTED/NOT_NEEDED with no
configuration, acquisition or shutdown hooks. Targeted: 62 passed; full Agg:
1546 passed, 1 skipped, 1 xfailed in 30.01s. Next is 24a only; physical 17/22
remain PENDING.

**Adapter review correction:** `bd0d10b` was labeled checkpoint 21 in error;
its AMR role work belongs to 23/23a. The Section 13 numbering is authoritative:
21 FE GUI hardening is next and still requires its audit; 22 FE physical record
remains PENDING without actual execution. AMR lifecycle work starts at 24a.

The current role API requires an explicit no-argument excitation shutdown_handler
for confirmed software safing, independent of preserve/configure. A missing
handler or any failed role action must remain unconfirmed/UNSAFE at lifecycle
integration; do not release ownership on an error result. External excitation
requires a named external_source_owner. Manual external ownership alone does not
confirm shutdown. Generic software-controlled external-source configuration,
limits and device ownership remain a separate tested adapter requirement.
Calibrated sources select V/A output mode explicitly; analog DMM readers currently
require V. Native field methods have no voltage fallback. Source/readback units
must match exactly unless a separate explicit conversion adapter is supplied.


AMR studies electrical transport versus orientation under declared magnetic-field and excitation conditions. The angle recorded is the apparatus/sample-current geometry, not a claim to have independently measured the magnetization direction. Retain this geometry definition and the angle zero in metadata. A simple cos-squared response is a test model, not an assumption to impose on every sample.

The core measurement depends on roles, not a fixed count or brand of instruments:

| Role | Responsibility | Current working lab setup |
|---|---|---|
| FieldSource | Command the chosen field through a bounded setup-specific mapping/controller; declare limits and safe policy | DC calibrator driving the magnet's control input |
| FieldReader (optional) | Read actual field with units and calibration/provenance | DMM reading the field sensor/gaussmeter analog output |
| TransportReadout | Configure declared excitation and acquire named electrical quantities with units | Lock-in reference/excitation and X/Y detector readout; external circuit described in the setup profile |
| OrientationController | Move to the next requested angle, wait for completion/settling and declare angle basis/limits | Existing Arduino/stepper motor |

**Required first profile:** support all four existing instruments together (calibrator + field-readback DMM + lock-in + stepper). Retain the working wiring, electrical settings, dwell/averaging and scientific procedure through adapters, while adopting the shared lifecycle and fixing tracked defects. Do not replace this setup with a sourcemeter-only design or repurpose its DMM as the sample-signal reader. Different roles may share an instrument or use separate instruments; connection ownership and safing cover each unique physical device once while attempting all required channel actions.

#### Field command and field measurement are separate configuration choices

- Command modes: a source-output-to-field calibration table loaded through FieldCalibration; an explicit bounded linear scale/offset profile (including the present 10000 Oe/V factor); or a controller that natively accepts field setpoints. A scalar factor must be supplied by the selected profile, not hard-coded into AMR. FieldCalibration mappings already include downstream gain: apply them once, without silently extrapolating or selecting a non-unique inverse.
- Readback modes: none, a digital gaussmeter, or a DMM plus a declared analog-sensor-to-field calibration. Command calibration and sensor calibration are separate objects even if the old setup uses the same scale for both. Do not assume coil-command volts equal Hall-sensor volts.
- A gaussmeter by itself does not tell a calibrator what output to command. Readback-only calibration is not an implicit feedback controller. The initial implementation commands through one of the modes above and optionally verifies field after settling and at each angular acquisition. Closed-loop field correction requires its own bounded control design and tests; do not invent it in the capture loop.
- The `field` column remains the requested/calibrated command in the base schema. When a reader is configured append `field_measured` and `field_time` (seconds elapsed); include matching unit entries and `field_basis`, source calibration/controller identity, reader calibration, tolerance and timing metadata. Report predicted/calibrated field in metadata when distinct from the requested field. Never relabel inferred field as measured.
- Verification uses explicit absolute plus relative tolerance (`abs(error) <= absolute_tolerance + relative_tolerance * abs(target)`), valid at zero and negative field. The setup declares warn/fail policy; the existing lab profile can retain warning behavior for finite mismatches. Reader errors/non-finite values are acquisition/configuration failures, not guessed field values. Readback must have compatible physical quantity and units; do not equate H and B by label-only conversion.

#### Electrical excitation and signal modes

The role returns named quantities plus units; no scalar instrument is forced to manufacture X/Y. `lockin_xy` remains the default supported mode with `x`, `y` in declared reader units. Add a separate `resistance` mode only through a reader/setup that actually measures resistance, with a `resistance` column in ohms. A sourcemeter or source-plus-voltmeter setup may expose `voltage_current` with `voltage` and `current`; only derive resistance when actual current, wiring/contact geometry, zero-current handling and excitation convention are known. One device may provide excitation and sensing.

Record `signal_mode`, excitation source, amplitude/current, frequency, RMS/peak convention, sense/wiring geometry and reference phase as applicable. A lock-in voltage or its programmed oscillator amplitude is not automatically sample resistance or known sample current. The exact excitation wiring of the current four-instrument setup must be documented from the user before adding resistance conversion; until then save truthful X/Y voltages. Preserve X/Y numerical behavior without inventing that conversion.

**Confirmed lab workflow:** the lock-in supplies excitation internally in the present setup, external excitation is also configurable, and the operator normally chooses lock-in settings/sensitivity manually. Therefore the default lab profile uses `readout_configuration="preserve"`: no initialize/reset, autorange, sensitivity/filter changes, or reference-source/amplitude/frequency writes at run start. Read existing settings where supported; otherwise retain user-declared settings with explicit provenance/unknown values. Never record requested defaults as verified actual settings. The profile's deliberate output-enable/safing actions remain required and separate from instrument setting preservation.

Expose an explicit `readout_configuration="configure"` choice with validated settings for users who want automation; `options={"configure_lockin": False}` maps to preserve and True maps to configure during this migration. Snapshot the selected policy/settings in the immutable run request. GUI setup offers internal/external excitation, use-existing/configure settings, and idle-only settings readback; preserve manual sensitivity tuning before acquisition. Configuration defaults must never overwrite the front-panel choices merely because Run was clicked.

An external excitation profile distinguishes the lock-in reference input from the physical device driving the sample. It names/binds the external source when software controls it and declares its limits, source configuration policy and shutdown actions. For a manually operated external source, the profile explicitly documents who controls and de-energizes it; do not claim software safing confirmed that external output. Do not send internal-oscillator configuration commands in external mode. Sample-current magnitude and external circuit remain unverified here, so retain X/Y voltage output unless a separately validated transport adapter supplies actual resistance/current.

Acceptance tests must cover the existing four-instrument internal-excitation profile with preserve mode (no reset/sensitivity/reference writes), explicit configure mode, external excitation with the correct reference/source routing and shutdown owner, and metadata distinguishing queried/user-declared/unknown settings. Front-panel or GUI tuning belongs before a run; active GUI commands still may not compete with the worker.

For schema version 1, mode-specific suffixes follow common `angle`, `field`: `x`,`y` for lockin_xy; `resistance` for resistance; `voltage`,`current` for voltage_current. The optional measured-field suffix follows those signal columns. Extend manifest target schemas and GUI selectors in the same adapter/slice commits; existing AMR fixtures refer specifically to lockin_xy. Each mode has exact ordered columns/unit mappings and separate numerical fixtures. Only advertise tested adapter/mode combinations; the first complete vertical slice must support the current four-instrument profile. Additional electrical modes land as separate commits after that slice.

#### Rotation scope

Require an automatic OrientationController in the first implementation, supplied by the existing stepper adapter or another tested motorized positioner. Define angle zero, rotation plane, sign convention, travel limits, degrees-per-step, residual-step accumulation and bounded settling. An open-loop stepper provides a commanded/step-count angle estimate, not independently measured encoder feedback. Optional readback must be labeled separately. Halt/homing/readback are capability-gated; the Stepper base guarantees only step(). Fix the extra endpoint movement in checkpoint 24b.

A motor is not a fundamental requirement of AMR physics. Manual rotation and vector-field orientation are future adapters, not reasons to add optional motor=None branches now. A future ManualOrientationController would emit a move request with run generation and requested angle, then wait cancellably for explicit confirmation (and optionally entered actual angle). Stop cancels the wait; stale confirmations cannot resume a later run. It must declare whether field/excitation remain on during the wait, never infer movement from Pause/Resume alone, and never call a GUI from the worker. This manual UI/controller work is deferred until requested; keep the first automated release straightforward.

### 9.6 MOKE roles

The general MOKE measurement uses:

- a sourcemeter as the direct calibrated output source;
- a DMM as the detector-voltage reader;
- an injected calibration mapping direct source output to field;
- an optional gaussmeter/field-reader adapter whose measured field remains a separate column.

No lab-specific power amplifier or magnet behavior is embedded in the sourcemeter/DMM drivers. The setup adapter and calibration describe that wiring.

In-plane and out-of-plane GUI choices select validated setup profiles before the run. A profile binds the appropriate source/channel, calibration, limits, optional field reader, and shutdown policy while the same `MokeMeasurement` performs the loop. Geometry is saved as metadata. When measured-field plotting is enabled and a field reader is present, the GUI plots the measured-field column; otherwise it plots calibrated field, and both columns remain distinct in saved data.

## 10. Measurement vertical slices

Every slice implements sections 3 and 7 and updates all of that family's repository consumers in its own reviewable commit(s). New-format assertions replace old-interface assertions; numerical/safety tests remain. No family-specific alternate lifecycle remains after its migration.

### 10.1 IV

Use `voltage`/`current`, V/A metadata, and the shared runner. Configure at electrical zero with output disabled; capture ramps and reads cancellably; safing ramps with independent pacing and attempts output disable even after a ramp failure. Test faults at every source/read step and numerical IV equivalence.

### 10.2 MOKE

Implement the initial plain-column schema, calibration-dependent unit metadata, optional field reader, bounded raw/cycle/average snapshots, and setup shutdown handler. Update all field selection and display labels. The prototype has no legacy format obligation. Test both field modes, alternative units, callback faults, partial cycles, averaging, repeat runs and shutdown.

### 10.3 Discrete waveform, hysteresis and PUND

Convert scientific processing to in-memory functions with explicit metadata; preserve numerical results and plotted quantities. Use WaveformReader with plain columns and explicit units. Migrate acquisition, analysis and consumers; safing attempts disable on every used AWG channel even if another action fails. Validate triggering, impedance, channel mapping, timing alignment and all polarization calculations.

### 10.4 AMR / magneto-transport

Use setup roles for field source/reader, X/Y signals and rotation. Standardize constructor spellings and shared run options; plain `angle`, `field`, `x`, `y` with declared units. Remove constructor I/O, mutable abort/pause booleans, capture-owned persistence and plotting. Keep the pause capability through the standard control methods. Validate field/motion separately, Stop during dwell/motion, calibration applied once, and numerical signal/angle results.

## 11. Simulation modernization

Simulation changes are additive and occur after measurement lifecycle migrations are stable.

### 11.1 Scope

Audit every consumer of shared virtual sample state:

- `VirtualInstrument` global `sample` / `mag_sample`;
- `VirtualDMM`;
- `VirtualSourcemeter`;
- `VirtualCalibrator`;
- `VirtualLockin`;
- `VirtualStepper`;
- `VirtualAwg`;
- `VirtualScope`;
- DAQ-to-AWG/scope adapters only if their own interface tests expose a defect.

### 11.2 Role-specific protocols and hooks

Use small roles for field-responsive materials, angle-dependent resistance, voltage/waveform response, and two-terminal electrical loads. The electrical-load contract supports voltage-source and current-source operation, compliance, time, and state; a one-way voltage-to-current callback is insufficient.

Virtual hooks are generic:

- DMM voltage reader;
- sourcemeter electrical load;
- per-channel scope reader;
- lock-in X/Y reader;
- calibrator field/output binding;
- stepper angle/material binding;
- AWG/scope signal routing.

Explicit per-instance injection takes precedence. Existing shared-sample behavior remains as a deprecated fallback until all internal and documented callers migrate or a major release removes it. No MOKE-, AMR-, or FE-specific branch is added to a generic virtual driver.

### 11.3 VirtualBench

`VirtualBench` owns material instances, virtual instruments, connection routing, reset, seed/RNG, and a deterministic timebase. Resetting one bench cannot mutate another. Tests run two benches concurrently, cover voltage- and current-source operation, verify compliance, and compare physical/virtual measurement schemas.

For MOKE simulation, the bench routes the sourcemeter's direct output through the injected field calibration to a hysteretic magnetic material, then exposes that material's optical response as a generic DMM voltage-reader hook; an optional second reader supplies simulated gaussmeter field. This wiring lives in the bench/setup fixture, never in `VirtualDMM`, `VirtualSourcemeter`, or the measurement class.

## 12. Commit checkpoints and acceptance gates

One checkpoint (or lettered subcheckpoint) per task/commit; stop after checks and review. Do not combine scientific algorithm changes with standardization. Commit tests with the behavior. Update the progress log with actual results, not anticipated passes. Stage explicit paths; preserve unrelated user work.

Run focused tests and `.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider -q` for code checkpoints. CI covers Python 3.9 and supported current Python; report unrun environments. An unavailable interpreter is a blocked gate, not a pass. Hardware checkpoints are independent manual release gates, not a reason to stop offline work on other families.

### File boundaries

Use `src/piec/measurement/base.py`, `contracts.py`, `runner.py`, `persistence.py`, and `adapters/` for shared components. Scientific code stays in each family's current measurement/analysis module unless a focused change is needed. Update package exports as consumers change. Focused tests belong under `tests/`; current `tests/fixtures/measurement_compatibility/` can hold reference/target fixtures while checkpoint 2R separates their meaning.

### Ordered checkpoints

| ID | Commit scope | Acceptance gate |
|---|---|---|
| 1 | Contract documentation (original checkpoint complete; this amendment needs its own documentation commit) | No conflicting old-API preservation requirements |
| 2R | Revise manifest/harness into separate reference observations and target contracts for every family | All target column/unit maps recorded; old-interface checks explicitly transitional; numerical evidence retained; no production migration |
| 2b | IV/MOKE deterministic scientific fixtures | Values, calibration and field-mode expectations from references; target-format requirements recorded without claiming old code implements them |
| 2c | FE/PUND numerical fixtures | Polarization, alignment and plotted traces have deterministic reference values/tolerances |
| 2c | Completed | Added FE and PUND deterministic scientific fixtures (`discrete_waveform_golden.csv`, `hysteresis_loop_golden.csv`, `three_pulse_pund_golden.csv`) and 21 regression tests in `test_measurement_fe_pund_compatibility.py` verifying exact CSV layout, metadata, units, golden regression, polarization calculations, auto_timeshift, plot artifacts, and old-to-new column numerical equivalence (including raw view). Fixed read-only array in `pund.py`. All 411 tests pass in 24.27s on Python 3.13.2. |
| 2c | FE/PUND numerical fixtures | Polarization, alignment and plotted traces have deterministic reference values/tolerances |
| 2d | Completed | AMR scientific golden and separately labeled legacy observation, consumer inventory, and regression tests. Signal tolerance is 1e-10 V; flat X/Y are rejected. Known defects AMR-FIELD-001 (23a) and AMR-ANGLE-001 (24b) have strict expected-failure tests, not frozen scientific expectations. AMR suite: 25 passed, 2 xfailed; full suite: 436 passed, 2 xfailed in 23.25s on Python 3.13.2. CI environments remain unverified locally. |
| 3 | AWG output_trigger indentation repair | Focused base-driver contract test |
| 4 | AWG trigger_source conditional repair | Focused tests and affected-driver audit |
| 5 | Standardize sourcemeter channel-first interface | Channel-first signatures across drivers; explicit keywords in callers; no legacy compatibility layer |
| 6 | DMM voltage-read audit | Fake-transport tests for advertised MOKE DMMs and VirtualDMM; defects repaired in separate fix commits |
| 7 | WaveformReader adapter | Plain time/voltage arrays with units; finite, equal-length validation and channel mapping |
| 8 | States, reservation, records | Concurrent/duplicate execution and stale tokens rejected; repeat runs and legal transitions |
| 9a | Full-run engine with fake hooks and in-memory persistence/event sinks | Canonical ordering, Stop-before-start, and one record/event per reservation |
| 9b | Sessions and standalone scopes | One command owner; no nesting or competing idle-shutdown writer; same no-save semantics for all families |
| 9c | Fault handling hardening | Configuration/acquisition/callback/safing faults plus KeyboardInterrupt/SystemExit; all shutdown actions attempted; error precedence |
| 10a | Bounded snapshots and display/control paths | Mutation isolation, queue saturation, terminal ordering |
| 10b | Runner | Synchronous reservation, non-daemon worker, thread-start failure and close coordination |
| 11a | Handle writer and schema metadata | One-row CSV layout and exact JSON unit round trips |
| 11b | Atomic no-replace publication | NTFS collisions/faults; explicit opt-in SMB tests; untested filesystems not claimed safe |
| 11c | Bundles, partials and recovery | CSV published last, UUID ownership, no accidental overwrite, recoverable raw data |
| 12 | Rewrite developer guide to the implemented engine | Examples compile and show the shared API, plain columns, metadata units, and one hardware writer |
| 13 | IV vertical slice, including IV GUI/analysis/notebooks/tests | Target API/schema, numerical goldens, complete consumer audit and source/read fault injection |
| 14 | MOKE vertical slice, including MOKE GUI/notebooks/tests | Initial target schema, calibrated/measured modes, unit-derived labels, averages, callback faults, repeat runs and safing |
| 15 | IV GUI interaction/ownership hardening after slice 13 | Stop-before-start, active close, terminal errors and owned-instrument close; no old API dependency |
| 16 | MOKE GUI interaction/ownership hardening after slice 14 | Geometry, bounded views, Stop/close, safety alerts and terminal delivery |
| 17 | IV/MOKE physical record | Dated actual execution only; otherwise PENDING |
| 18 | In-memory hysteresis processing | New plain schema and explicit metadata; numerical/trace equivalence; update affected callers in the same commit |
| 19 | In-memory PUND processing | Same as 18 including each PUND polarization quantity |
| 20a | Completed | Standardized DiscreteWaveform base acquisition to inherit BaseMeasurement, adhere to discrete_waveform schema v1, utilize WaveformReader, enforce strict trigger ordering (arm scope -> enable AWG output -> fire AWG trigger), implement attempt-all output safing, and preserve unmigrated HysteresisLoop/ThreePulsePund paths. All 294 targeted tests passed; full test suite: 1367 passed, 1 skipped, 2 xfailed in 23.86s. Physical checkpoint 17 remains PENDING. |
| 20b | Completed | Standardized HysteresisLoop to inherit DiscreteWaveform/BaseMeasurement lifecycle, adhere to hysteresis schema v1, execute in-memory analysis via process_hysteresis, stage multi-artifact plots (_PV.png, _IV.png, _trace.png), remove legacy bypass paths (save_dir, apply_and_capture_waveform, save_waveform, analyze), and retire private _process_raw_hyst_file bridge. Updated all consumers and documentation. All targeted tests passed; physical checkpoint 17 remains PENDING. |
| 20c | Completed | PUND integration and consumers; target runner/schema, plots, numerical and fault tests. |
| 21 | Completed | FE GUI interaction/ownership hardening across HysteresisLoop and ThreePulsePund. Main-thread Tk/plots, virtual selection, pre-connection validation, Stop/close coordination, single hardware writer rule, and save policies. Added 43 tests in `tests/test_measurement_fe_gui.py`. |
| 22 | PENDING | FE physical record: physical hardware testing unavailable in execution environment; record remains explicitly PENDING. |
| 23 | AMR setup-role adapters | Working four-instrument profile, default preservation of manual lock-in settings, internal/external excitation; separate command/readback calibrations; linear/table/native-field command modes; optional digital-gaussmeter or analog-DMM readback; units, limits, zero/negative-field tolerance and isolated role tests |
| 23a | Repair/retire placeholder field conversion (AMR-FIELD-001) | Default 10000 Oe/V gives 100 Oe -> 0.01 V; replace the strict expected failure with passing field-adapter tests |
| 24a | Completed | Standardized `MagnetoTransport` onto `BaseMeasurement` shared lifecycle with zero constructor I/O, `stepper` and `voltage_calibration` parameters (and backward-compatible properties), AMRSetupProfile role delegation, excitation safing validation before energizing, attempt-all safe shutdown with connection retention on UNSAFE, and runner integration. Added 18 unit/lifecycle/fault tests in `tests/test_measurement_magneto_transport.py`. Full test suite with Agg: 1564 passed, 1 skipped, 1 xfailed. |
| 24b | Completed | Migrated AMR acquisition, schema amr v1 with plain columns ('angle', 'field', 'x', 'y') and declared units, BaseMeasurement lifecycle, and consumers onto MagnetoTransport. Repaired AMR-ANGLE-001 (zero extra motor step; endpoint matches commanded angle). Excitation shutdown required before energizing; manual lock-in settings preserved by default. Atomic publication, bounded snapshots, cooperative pause/stop. Removed _LegacyMagnetoTransport and obsolete API tests. Full test suite: 1571 passed, 1 skipped. |
| 24c | Completed | AMR notebook/GUI presentation integration: MeasurementRunner lifecycle, bounded raw_window live display, authoritative terminal data view, metadata-derived axis labels, simulation vs physical excitation shutdown policy, manual lock-in preservation by default, open connection retention on UNSAFE, notebook simulation safing & unit plotting. Full suite with Agg: 1597 passed, 1 skipped. |
| 24d onward | Additional AMR electrical adapters, one signal mode per commit after the working four-instrument slice | Mode-specific data/units and truthful excitation; direct-resistance or voltage/current numerical fixtures, producer/GUI/consumer updates; no fabricated X/Y or assumed current |
| 25 | Completed | AMR GUI interaction/ownership hardening: settings/preflight validation (addresses, sweep direction, limits, sensitivity), Run/Pause/Stop/close coordination through common runner, startup failure handling (validation vs active ownership retention), terminal-before-worker-exit gating, UNSAFE connection retention & run button locking, auxiliary action resilience (stepper test, autodetect, refresh). Targeted GUI: 35 passed; focused: 215 passed; full repo suite: 1621 passed, 1 skipped in 62.07s. |
| 26 | PENDING | AMR physical record: physical hardware testing unavailable in execution environment; record remains explicitly PENDING. |
| 27 | Role-specific simulation contracts | Units, reset, deterministic time/RNG and voltage/current-source electrical loads |
| 28a onward | Generic per-instance virtual hooks, one driver family per commit | Explicit injection overrides global fallback; no sample-specific driver branches |
| 29 | VirtualBench | Routing, reset isolation, deterministic noise/time and two-bench concurrency |
| 30a–30d | Migrate IV/MOKE/FE/AMR simulation fixtures one family per commit | Physical/virtual schemas agree; preserve applicable generic-driver fallback tests |
| 31 | Retire internal global-sample use after consumers migrate | Keep external generic-driver fallback unless separately authorized to remove it |
| 32 | Optional scientific additions, only if separately requested | One algorithm/reference dataset/unit/tolerance/review per commit; outside this standardization |
| 33 | Final documentation, workflows and release notes | Offline notebooks, docs build, full tests; list replaced APIs/formats without implementing converters |

If a family slice needs more commits, use lettered steps with an explicit file list and gate. Each intermediate commit must leave repository consumers operational: combine producer/consumer changes where necessary. An intermediate analysis commit may use a private, temporary bridge for an unmigrated internal caller; remove it when that caller migrates. Do not create a permanent public old/new compatibility layer. Do not defer essential GUI API/schema fixes to later GUI-hardening checkpoints.

## 13. Physical validation records

Automated/virtual tests do not prove physical safety. Each hardware checkpoint stays marked `PENDING` until a record contains:

- date and tester;
- exact instrument model, serial/asset identifier as appropriate, and firmware;
- wiring/load and measurement geometry;
- driver and repository commit;
- configured voltage/current/field/frequency limits and compliance;
- physical interlock and manual emergency procedure;
- commanded-versus-observed output/readback;
- Stop and window-close latency;
- injected/read timeout behavior;
- observed final output-enable state and residual output/field;
- pass/fail result and anomalies.

MOKE validation is staged: first source plus DMM into a benign electrical load and observed by an oscilloscope; only then the amplifier/magnet with established limits and interlock. AMR validates motion and field roles independently before combining them. FE begins at low amplitude into an explicitly known impedance.

### 13.1 Checkpoint 17: IV and MOKE physical validation record (PENDING)

The record template is complete; physical validation remains **PENDING**.
Use `docs/physical_validation_iv_moke.md` as the single detailed template for the
Section 13 record fields, staged execution, observation log and sign-off.

Gemini reported an empty VISA discovery result; no actual hardware execution is
recorded. This discovery result is not proof that all interfaces were searched.
Historical virtual/software results are not physical evidence.

Before execution, the operator must establish and record bench-specific limits,
acceptance criteria and their basis. No universal voltage/current accuracy,
residual-field threshold or Stop latency is imposed by this template. Record the
actual instruments, supported drivers, wiring, calibration and tested commit.
The example MOKE calibration is illustrative and cannot validate physical field.

Distinguish acquisition failure from shutdown failure: a detector error can end
FAILED with SAFE shutdown; connections can then close after worker exit. UNSAFE
shutdown retains connections and defers normal closure. Observe physical output
independently and record whether an interlock is visible to software.

Keep checkpoint 17 PENDING until dated physical execution and sign-off exist.
The plan permits later offline work, but this handoff stops before checkpoint 18
until the user requests it.

### 13.2 Checkpoint 22: Ferroelectric (FE) physical validation record (PENDING)

The record template is complete; physical validation remains **PENDING**.
Use `docs/physical_validation_fe.md` as the single detailed template for the
Section 13 record fields, staged execution, observation log and sign-off.

Physical AWG, oscilloscope, and amplifier instruments were not discovered in this
automated environment (`pyvisa.ResourceManager().list_resources()` returned `()`).
Virtual and headless test suites pass (207 focused FE tests, 43 GUI tests) but do not
substitute for physical hardware validation.

Per Section 13: "FE begins at low amplitude into an explicitly known impedance."
Hardware validation is staged:
1. Low amplitude ($V \le 1.0\text{ V}$) into a benign linear capacitor standard ($C \approx 10\text{ nF}$) in series with a precision shunt resistor ($50\text{ }\Omega$). Verifies strict trigger ordering (arm scope -> enable AWG output -> trigger AWG), WaveformReader channel routing and finite numerical validation, linear dielectric response ($P_r \approx 0$, $V_c \approx 0$), and attempt-all AWG output safing (`:OUTP OFF`).
2. Three-pulse PUND on linear capacitor standard to verify pulse sequence timing, polarities, auto_timeshift alignment, and cancellation of switching vs non-switching displacement ($\Delta P \approx 0$).
3. Reference ferroelectric capacitor (PZT, BFO, HZO) integration with established voltage/current limits and manual emergency procedures. Verifies in-memory `process_hysteresis` and `process_pund` data extraction, multi-artifact plot staging (`_PV.png`, `_IV.png`, `_trace.png`, `_dPvst.png`), and canonical schema publication (`hysteresis` v1, `three_pulse_pund` v1).
4. Fault handling: scope trigger timeout, communication failure, and attempt-all safing with `SafetyStatus.UNSAFE` connection retention.

Keep checkpoint 22 PENDING until dated physical execution and sign-off exist.

### 13.3 Checkpoint 26: AMR physical validation record (PENDING)

The record template is complete; physical validation remains **PENDING**.
Use `docs/physical_validation_amr.md` as the single detailed template for the
Section 13 record fields, staged execution, observation log and sign-off.

Physical stepper motor, electromagnet calibrator, field readback DMM, and lock-in
amplifier instruments were not discovered in this automated environment
(`pyvisa.ResourceManager().list_resources()` returned `()`). Virtual and headless
test suites pass (215 focused AMR/Magneto tests, 35 GUI tests) but do not substitute
for physical hardware validation.

Per Section 13: "AMR validates motion and field roles independently before combining them."
Hardware validation is staged:
1. Motion role alone: Stepper motor / orientation controller verification without magnetic field or sample excitation. Verifies angular scaling, forward/reverse directional handling, stop latency, and confirms repair of defect `AMR-ANGLE-001` (zero extra motor step; endpoint strictly matches commanded angle).
2. Field role alone: Calibrator / electromagnet power supply and field readback DMM / Hall probe without sample excitation or motion. Verifies voltage-to-field calibration (`AMR-FIELD-001` repair: $10000\text{ Oe/V}$ gives $0.01\text{ V}$ for $100\text{ Oe}$), bipolar zero-crossing, and attempt-all de-energization safing to $0\text{ Oe}$.
3. Transport readout & excitation safing role alone: Lock-in amplifier into a known benign resistor standard (e.g. 1 kΩ). Verifies preservation of front-panel manual settings by default (`initialize_lockin=False`, `readout_configuration="preserve"`), execution of declared physical excitation shutdown policy (amplitude drops to $0.000\text{ V}$), and retention of open connections on simulated shutdown failure (`SafetyStatus.UNSAFE`).
4. Integrated low-field AMR measurement: Reference thin-film AMR sample (e.g. 20 nm NiFe stripe) mounted in electromagnet gap. $0^\circ \to 180^\circ$ rotation sweep at $H = 100\text{ Oe}$. Verifies bounded `raw_window` display updates, authoritative terminal delivery, atomic CSV publication under canonical schema `amr` v1 with declared units (`deg`, `Oe`, `V`, `V`), and characteristic $\cos^2(\theta)$ anisotropic magnetoresistance curve.

Keep checkpoint 26 PENDING until dated physical execution and sign-off exist.
All physical validation checkpoints (17, 22, and 26) are explicitly marked **PENDING**.

## 14. Definition of done

- Every family passes the target manifest, shared runner/session/ownership contract, plain-column schema and unit metadata tests.
- No migrated family overrides the base lifecycle or retains a parallel old runner/format solely for compatibility.
- Numerical scientific regressions, calibrated/measured distinctions, raw recovery and plotted physical quantities pass.
- Stop/start races, stale/duplicate workers, callback faults, shutdown faults and close behavior are tested; every reservation has one terminal record/event and a separate safety result.
- Incomplete files cannot appear complete and publishers never silently overwrite targets.
- All affected GUIs, analysis functions, notebooks, exports and docs use the new standard; no obsolete lookup/call remains in repository consumers.
- Two virtual benches run without cross-talk; supported-Python checks pass. Physical checkpoints show actual results or explicitly remain PENDING.
- User data is untouched; unrelated driver compatibility has not been removed as a side effect.
