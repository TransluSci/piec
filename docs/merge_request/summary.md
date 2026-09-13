# PIEC branch merge request summary

This merge brings `measuremnt-standarization` into `master`. It introduces a shared measurement execution and saving framework, migrates the existing measurement families, adds MOKE and USB1208HS support, and expands virtual instruments into explicitly connected simulation setups. This is an API and data-format migration as well as a feature addition.

The comparison is pinned to branch commit `99a8d697901468e7f7c7db275994fb1fab7a3984` and local `master` commit `9d9760242f44a79401626964f0122cc91b149c18`. Master is the merge base: the branch is 103 commits ahead and zero behind. The committed change contains **176 files, 50,406 added lines, and 3,653 removed lines**, including 82 test and fixture files. These counts exclude this comparison documentation. No remote refresh is implied.

Use this document for the merge request overview. The [detailed comparison](detailed.md) explains the before and after behavior, affected files, migration work, and review evidence for each area.

## Physical drivers and common driver interfaces

- **AWGs:** Repair the incorrectly nested `Awg.output_trigger()` declaration and the reversed trigger-source condition in `Awg.configure_trigger()` and `Keysight81150a`. Add shared SCPI trigger handling for Agilent 33220A and 33500, Rigol DG1000, and Rigol DG4000. Rigol DG1000 now distinguishes legacy and Z command dialects; Agilent 33500 maps `USER` to `ARB` and programs both pulse transitions. Siglent trigger inputs become case-insensitive.
- **DAQs:** Add the USB1208HS, USB1208HS-2AO, and USB1208HS-4AO family. Expand USB231 implementations of the common DAQ configuration API and make channel, range, and rate capabilities explicit. Add a generic trigger-pulse API with software digital output and a USB1208HS hardware timer backend.
- **DMMs:** Implement missing configuration behavior, synchronize function caches, normalize overloads to signed infinity, and propagate read errors. Keithley 193A retains its DDC protocol and explicitly rejects unsupported software configuration.
- **Sourcemeters:** Align virtual calls with the existing channel-first physical interface, add the base resistance-read declaration, and validate Keithley 2400 channels before I/O. Callers should use explicit keywords such as `set_source_voltage(channel=1, voltage=1.0)`.

**Review implication:** Command tests verify emitted commands and error handling. They do not certify physical triggering or measurement accuracy. Legacy DG1000 software triggering remains explicitly unverified. [Driver details](detailed.md#physical-drivers-and-common-driver-interfaces).

## DAQ emulators

`DaqAsAwg` and `DaqAsOscilloscope` now use DAQ capability metadata for channel mapping, sample rates, and voltage ranges. Scope acquisition reports duration using the actual scan rate when available. `DaqAsAwg` can emit a pulse through an explicitly selected DAQ resource.

**Review implication:** A DAQ trigger pulse does not arm, start, or synchronize analog waveform playback. Complete `DaqAsOscilloscope` integration remains less directly covered than the DAQ and AWG adapter contracts. [Emulator details](detailed.md#daq-emulators).

## Virtual drivers

Seven virtual instrument families gain independent injected hooks: AWG, oscilloscope, sourcemeter, DMM, lock-in, calibrator, and stepper. Hooks connect instruments to setup-owned models, with validated inputs and results, preserved hook errors, and explicit reset behavior. The sourcemeter distinguishes configured settings from compliant terminal voltage/current. Calibrator, stepper, and sourcemeter failures can leave output or motion unconfirmed instead of falsely reporting success.

`VirtualDaq` also records simulated trigger pulses. Virtual pulser, RF source, dispatch, and the base virtual-instrument implementation are not newly redesigned in this diff. Historical shared sample fallbacks remain available outside explicitly wired setups.

**Review implication:** Use private hooks or `VirtualBench` for isolation; do not assume every virtual object is now isolated automatically. [Virtual driver details](detailed.md#virtual-drivers).

## Simulation models and virtual benches

Add role contracts for electrical loads, magnetic response, angle-dependent resistance, and waveform response; resistor, diode, and capacitor loads; a hysteretic magnetic material; and `VirtualBench`. A bench owns its instruments, models, routes, random streams, and clock, with deterministic reset and failure reporting.

IV, MOKE, FE, and AMR numerical fixtures move to private benches. FE and AMR examples attach private plants through setup helpers. The magnetic resistive model now requires explicit excitation current and returns an in-phase voltage with zero quadrature; fixtures that need nonzero quadrature declare their own law.

**Review implication:** Stateful loads require explicit time advancement. Reset replay and simulated compliance are tested software behavior, not physical calibration. [Simulation details](detailed.md#simulation-models-and-virtual-benches).

## Shared measurement framework

Add `BaseMeasurement`, lifecycle contracts, sessions, snapshots, and `MeasurementRunner`. Existing families now share execution ownership, cooperative cancellation, shutdown reporting, in-memory results, and publication. Constructors defer instrument I/O. A full run performs configuration, acquisition, shutdown, analysis, and optional saving, then records its outcome.

The engine retains raw data after acquisition failures, keeps the original failure primary when cleanup also fails, and separates run outcome from shutdown status. GUI display queues can discard stale display updates; control events and final results follow a separate path. Sessions support interactive configure/capture workflows under one execution owner.

**Review implication:** Update subclasses to protected hooks and consumers to the runner/session API. Shutdown commands and their available readback evidence must be assessed separately from a `COMPLETED` or `FAILED` outcome. [Framework details](detailed.md#shared-measurement-framework).

## Measurement families

| Family | Main change | Migration or review focus |
|---|---|---|
| IV sweep | Shared lifecycle; paced, cancellable voltage ramps; full raw recovery; output-disable attempts even if the shutdown ramp fails | `output_dir` replaces `save_dir`; settings are keyword-only; output columns are `voltage`, `current` |
| MOKE | Entirely new relative to master; calibrated source sweep, DMM detector, optional measured field, repeated cycles, and completed-cycle averaging | Distinguish calibrated from measured field and detector voltage from inferred magnetic quantities |
| Discrete waveform | Shared execution with scope arm, AWG enable, and trigger ordering; normalized waveform acquisition | Use shared run/session/capture methods instead of the old apply/save workflow |
| Hysteresis | In-memory analysis after shutdown; explicit offset and alignment handling; staged plot artifacts | Update analysis calls and lowercase columns; polarization units are metadata |
| Three-pulse PUND | In-memory analysis, consistent pulse polarity and offset handling, shared runner and persistence | Preserve pulse windows and switching/non-switching component meaning when updating scripts |
| MagnetoTransport and AMR | Explicit field/readout/orientation roles; preserve manual lock-in settings by default; cooperative pause and stop | Supply an excitation shutdown handler; use `stepper`, corrected calibration, and lowercase `x`, `y` |

**AMR scientific corrections:** The final motor step no longer advances past the reported endpoint. The default 10,000 Oe/V field conversion now gives 0.01 V for 100 Oe, correcting the old helper's 10 V result. Saved angles reflect commanded step quantization, not independent encoder verification. [Measurement details](detailed.md#measurement-families).

## Analysis and calibration

Replace file-driven `process_raw_hyst` and `process_raw_3pp` with `process_hysteresis` and `process_pund`, which accept DataFrames and explicit parameters and return analysis result objects. Plotting is separate from computation. Add `FieldCalibration` with explicit electrical/field units, interpolation, validated inverse lookup, and no extrapolation.

**Review implication:** Analysis no longer requires a saved CSV, and old function names are not retained as compatibility wrappers. [Analysis details](detailed.md#analysis-and-calibration).

## Data schemas and saving

All six standardized schemas use plain column names and version 1 metadata. Units move into `column_units_json`; files also identify schema, run, outcome, partial status, and saving intent. New persistence uses one UTF-8 handle, flush/fsync, unique reservations, and atomic publication that refuses to overwrite an existing result. Side artifacts publish before the primary CSV; failures expose retained data and recoverable staging paths.

**Review implication:** Update CSV readers and scripts that assume unit-bearing column names, old filenames, or a successful save whenever a run returns. Partial files and staged recovery files are not completed results. Existing user files are not rewritten, and this merge adds no automatic converter or general compatibility shim. [Persistence details](detailed.md#data-schemas-and-saving).

## GUIs notebooks documentation and CI

IV, FE, and AMR GUIs adopt the shared runner and coordinated connection ownership; MOKE adds a GUI and notebook. GUIs defer closing connections until execution finishes and shutdown status allows release. Updated virtual notebooks use temporary output locations and private plants. A new script executes four notebooks, and CI adds Python 3.9/3.13 coverage, complete Git history for baseline tests, and strict offline documentation checks. Packaging includes the example FE material JSON.

**Review implication:** Connection ownership and failed-shutdown recovery deserve review alongside normal acquisition. Python 3.9 and remote CI results must be checked independently of the recorded local Python 3.13 result. [Consumer and CI details](detailed.md#guis-and-notebooks).

## Validation and outstanding work

The branch's [checkpoint 33 handoff](../../MEASUREMENT_HANDOFF.md) records **2,159 passed and 1 skipped on Python 3.13**, **four notebooks with 36 code cells passed**, a warning-free offline Sphinx build, and a successful wheel build. These are recorded implementation results, not a fresh test run performed while writing these documents.

- Physical **IV/MOKE, FE, and AMR validation remain PENDING** in the committed validation records.
- Real SMB validation remains unverified; the share-specific test is opt-in. Mocked filesystem behavior is not an SMB deployment result.
- Python 3.9 and remote CI were not confirmed by the recorded local validation.
- The current full branch comparison reports whitespace issues with `git diff --check master...HEAD`; historical statements about a clean diff should not be treated as a clean full-range check.
- Additional AMR electrical readout adapters, manual rotation workflows, and optional later scientific additions are outside this merge.

Recommended review order: common drivers and adapters, lifecycle and persistence, each measurement family, virtual hooks and benches, then GUI behavior and validation evidence. The [detailed document](detailed.md) provides a migration table, source map, and concrete review checks.
