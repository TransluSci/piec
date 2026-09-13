**Test consolidation plan — instrument and measurement contracts**

Status: proposed plan; no tests or production code changed. Inventory taken from the current branch on 2026-09-13 and compared with local `master`.

The proposed change is to write common assertions once and apply them to every applicable implementation. Use one test module per instrument category, a common measurement contract suite, and a few focused suites for shared infrastructure and scientific behavior. Keep small fixtures describing how to construct each implementation and what independent inputs/outputs it should produce.

The current suite contains **74 test modules, 24,954 lines, and 1,324 test function definitions**. Of those modules, 67 were added on this branch, one was modified, and six are unchanged from master. Eighteen modules end in `_review.py` or `_regressions.py`. These are static source counts, not pytest's collected case count; parametrized tests produce additional cases. The suite was not executed for this planning audit.

Aim for **approximately 25 test modules**, subject to keeping them readable. The useful reduction is in duplicated assertions, fixtures, and historical scaffolding. Parametrization may retain or increase the number of executed cases while substantially reducing the code we maintain. Do not delete distinct checks to meet a file or case quota.

**1. Instrument tests: one contract per category**

Each category module will apply its common assertions to physical drivers, virtual drivers, and applicable adapters. Start with AWG as a pilot, then sourcemeters, before generalizing the remaining categories.

| Proposed module | Common behavior to cover, where supported |
|---|---|
| `test_awg.py` | Configuration forwarding, waveform/output settings, channel handling, trigger configuration and execution, output shutdown. |
| `test_scope.py` | Acquisition configuration, channel selection, trigger/acquisition behavior, waveform return structure and timing. |
| `test_sourcemeter.py` | Source mode and level, compliance, output enable/disable, voltage/current reads, channel handling. |
| `test_dmm.py` | Measurement configuration, read result types, response parsing, invalid or unavailable measurements. |
| `test_daq.py` | Input/output operations, acquisition shapes, timing, trigger pulse behavior. |
| `test_lockin.py` | Configuration and supported readouts, including independent X/Y values and phase behavior. |
| `test_calibrator.py` | Output mode and level, enable/disable, supported readback and unknown-state behavior. |
| `test_stepper.py` | Movement, position, supported limits, quantization and reset behavior. |
| `test_pulser.py` | Existing public pulse configuration, triggering, and output behavior. |
| `test_rf_source.py` | Existing public frequency, level, modulation, and output operations where implemented. |

Establish the required and optional operations from the current supported API before writing assertions. These rows are coverage areas, not a proposal to require every instrument to implement every possible feature.

**Discovery and registration:** extract the useful discovery logic already in `tests/test_driver_mro.py`. Import production modules, identify locally defined subclasses, deduplicate aliases/re-exports, and exclude actual examples and retired code. Include adapters from `emulators` in a separate explicit discovery path; the current MRO discovery excludes that directory. Compare the discovered classes against the test fixture registry. A new subclass without runtime coverage must produce an actionable failure naming the missing fixture.

Each fixture should contain only the necessary constructor setup, supported capabilities, representative inputs, and independently specified responses or command expectations. Use a default factory where constructors permit it, with small overrides for models that need extra arguments. Inheritance gives automatic discovery; it cannot tell a test the correct vendor command or how to construct an arbitrary device.

For required operations, verify a real implementation resolves through the inheritance chain and then assert an observable result. Some base methods currently contain `pass`, so `hasattr()` and signature checks alone cannot establish support. Accept working inherited implementations and mixins; do not demand that every method appear directly in the concrete class. Check that supported calls bind correctly rather than insisting on one exact parameter list across unrelated categories.

An optional unsupported capability needs an explicit, reviewed entry with a reason. Unexpected failures must not turn into automatic skips. Existing incomplete support should be recorded as a gap rather than silently treated as passing behavior. Adding new production features is outside this cleanup.

**Physical drivers:** run the concrete driver code with a scripted fake transport at the VISA/vendor boundary. Assert the expected command, channel, units, parsing, and relevant failure behavior. Expected commands and replies must come from independent test data, not be copied dynamically from the production mapping being tested. Keep constructor coverage where initialization matters; a narrowly scoped bypass can remain for isolated method checks.

**Virtual drivers:** run against an owned, deterministic virtual setup and assert the resulting state or readout. A physical model constructed with the special `"VIRTUAL"` resource can dispatch to a virtual class, so that route must not be counted as testing the physical model's command implementation. Test dispatch separately.

**Adapters:** exercise the applicable category contract through a fake or virtual underlying instrument, preserving unique conversion and delegation checks. An adapter must not disappear from coverage because it lives outside a category folder.

**2. Shared virtual behavior: one reusable suite**

Consolidate repeated hook assertions from the AWG, scope, DMM, sourcemeter, lock-in, calibrator, and stepper hook modules into `test_virtual_instrument.py`. Small per-category adapters can supply a write/read operation, a hook, and the expected result.

The common cases should cover hook invocation, argument forwarding, precedence, exception propagation, fallback behavior, and isolation/reset between owned setups. Parameterize only the hooks to which each rule applies.

Keep category-specific behavior in the relevant instrument module: AWG waveform generation, scope pretrigger timing, sourcemeter compliance, independent lock-in X/Y responses, and stepper quantization are different assertions. Preserve the legacy virtual fallback paths that remain supported on this branch.

This work does **not** implement scope input impedance or the proposed material hierarchy. In particular, the currently incomplete virtual scope impedance behavior must not be labelled as simulated 50-ohm loading by a generic test.

**3. Measurement tests: shared expectations with a small fixture per implementation**

Create `test_measurement.py` for the public contract. Discover supported `BaseMeasurement` implementations and check that each has a test case specification. Initially cover `IVSweep`, `MokeMeasurement`, `DiscreteWaveform`, `HysteresisLoop`, `ThreePulsePund`, `MagnetoTransport`, and `AMR`. Account for exported classes defined in private modules, such as `MagnetoTransport`; do not exclude a supported implementation merely because its source filename starts with an underscore.

Each specification supplies a factory using fake/virtual instruments, minimal valid options, expected raw and analyzed schemas, expected units, a deterministic interruption/failure point, and the instrument-specific shutdown observations. Reuse the existing IV, MOKE, FE, and AMR bench fixtures instead of building a second simulation fixture system.

Apply a compact set of meaningful scenarios to every implementation:

1. Construction performs no hardware I/O, and invalid run options fail before acquisition/output side effects.
2. A minimal successful run returns a DataFrame with the required family columns, appropriate value types and units, and consistent raw/analyzed views.
3. Stop before execution produces the documented empty/aborted result without hardware I/O.
4. Cancellation after acquisition has begun retains available data, reaches the documented terminal outcome, and performs the expected shutdown.
5. An injected acquisition failure preserves available raw data and reports both the acquisition error and any shutdown failure correctly.
6. One representative saved run round-trips its data and schema/unit metadata through the shared persistence layer.

Reuse scenario assertions while allowing the fixture to express legitimate differences. Successful analyzed data, interrupted raw data, and a stop-before-start empty DataFrame do not all have the same schema. IV and FE columns differ from MOKE and AMR columns. Optional readbacks must appear when enabled, and their absence must not be hidden by comparing only intersecting columns.

Keep expected schemas independently declared in the tests. Comparing output only with a schema generated from that same output would miss a column being removed everywhere. Numerical comparisons need column-specific tolerances, especially for microsecond time axes. Apply finite-value requirements only where the contract requires them; an instrument overload indication is different from valid analyzed measurement data.

Use the family specification for capability differences such as pause support. Do not impose a universal “all outputs remain off during configuration” assertion: some AMR configuration intentionally applies field/excitation after validation. Measurement shutdown should safe its instruments; connection closing remains with the owner of those connections.

**4. Exercise the shared engine thoroughly once**

Keep the exhaustive lifecycle and error combinations in `test_measurement_engine.py`, using one small configurable fake measurement. The existing fake in that module is a useful starting point. Merge overlapping lifecycle, session, fault, and ownership assertions here.

Cover phase ordering, validation and reservation, stop/pause semantics, run ownership, error precedence, shutdown reporting, partial data, session exit, and exactly one terminal event per accepted run. Include the distinction between session-owned configure/capture and transient standalone calls. Preserve the rule that a rejected caller cannot safe an instrument owned by another active run.

Keep genuine worker/thread and snapshot delivery behavior in `test_measurement_runner.py`: startup failures, worker completion, cancellation, immutable snapshots, bounded live display, complete terminal data, and reliable terminal delivery. These boundaries cannot be established solely by testing the synchronous base class.

The full fault matrix runs against the small fake. The compact scenarios in `test_measurement.py` establish that every real implementation integrates with that engine. Avoid multiplying all faults by all families, saving modes, runner modes, and filesystem backends.

**5. Retain the science and protocol checks that generic schemas cannot catch**

Use `test_measurement_protocols.py` for a small set of measurement-specific scenarios and keep focused analysis modules. These assertions need independent expected values or committed reference data.

| Area | Distinct checks to preserve |
|---|---|
| IV | Known resistor response, ramp/step ordering and bounds, correct source programming. |
| FE hysteresis and PUND | Pulse order/polarity, time alignment and pretrigger data, integration windows, area/unit scaling, current and polarization results. |
| MOKE | Calibration direction and units, measured-field timing, cycle/direction structure, treatment of incomplete cycles. |
| AMR / magneto-transport | Angular endpoints and quantization, no extra motion, field conversion, independent X/Y responses, preservation of manually owned settings and shutdown of measurement-owned excitation. |
| WaveformReader | Supported native waveform layouts, canonical conversion, malformed data, synchronization and timing checks. |
| Simulation | Role compatibility, deterministic time/noise, independent benches, connection effects, and the existing material/plant laws. |

A generic “returns a DataFrame” test will not catch a factor-of-1,000 unit error or an extra motor step. Preserve at least one independent reference for each distinct law or measurement protocol. Do not regenerate goldens using the current implementation and treat agreement as independent validation.

**6. Consolidate persistence, GUIs, and documentation checks**

Move shared persistence checks into `test_persistence.py`: schema and metadata round trips, filename reservation/collision handling, atomic publication, bundle completeness, recovery, and cleanup ownership. Test fault windows once with representative data. Keep OS/filesystem-specific behavior separately marked where necessary; mocked filesystem tests do not establish behavior on a real SMB share.

Create `test_gui.py` with small GUI adapters for common start/stop, worker completion, terminal display, close, and connection ownership assertions. Preserve family-specific controls and settings checks as focused cases in that module. Use existing fake Tk/timer patterns without introducing a new production GUI interface just to share tests. Split the module if it becomes difficult to read; a file-count target is not a reason to create a monolith.

Use `test_examples.py` for import/documentation smoke checks and the published developer example's execution and cleanup boundaries. Retain the existing offline notebook and Sphinx checks. Avoid repeating the entire engine failure matrix against every example when it only exercises shared implementation.

**7. What to remove, and the destination of retained coverage**

Treat these as consolidation candidates. Before deleting an old test, record its unique assertion and either its replacement or why it checks a retired requirement.

| Current modules / fixtures | Proposed destination and treatment |
|---|---|
| `test_awg_contract.py`, `test_awg_trigger_commands.py`, AWG-specific virtual cases | `test_awg.py`; combine repeated trigger/command checks into parameter rows. Remove repeated method-existence and nested-bytecode checks once the public contract and behavior catch the original failure. |
| `test_daq_contract.py`, `test_daq_trigger_pulses.py` | `test_daq.py`; retain distinct pulse/timing behavior. |
| `test_dmm_contract.py`, `test_sourcemeter_contract.py` | Respective category modules; share setup and parametrized read/configuration assertions. |
| Seven `test_virtual_*_hook.py` modules and virtual review files | Common hook rules to `test_virtual_instrument.py`; unique effects to the category modules. |
| `test_instrument_core.py`, `test_driver_mro.py`, `test_autodetect.py`, `test_virtual_discovery.py`, `test_virtual_dispatch.py`, `test_imports.py` | `test_instrument.py` and `test_discovery.py`, with documentation/example import checks in `test_examples.py`. Consolidate carefully: six of these modules predate this branch. |
| Per-family `test_measurement_iv.py`, `test_measurement_moke.py`, `test_measurement_discrete_waveform.py`, `test_measurement_hysteresis.py`, `test_measurement_pund.py`, `test_measurement_magneto_transport.py` | Shared scenarios to `test_measurement.py`; unique protocol/numerical cases to `test_measurement_protocols.py`. |
| `test_amr_contract.py`, `test_moke.py`, family review modules | Route contract assertions to shared measurement/category tests and unique numerical, calibration, adapter, or protocol assertions to their focused destination. |
| `test_measurement_pipeline.py`, `test_fe_bench_fixture.py`, `test_amr_bench_fixture.py` | Fold useful setup/integration assertions into a minimal real measurement scenario; stop rerunning the whole pipeline separately for trivial default-field checks. |
| `test_measurement_lifecycle.py`, `test_measurement_engine.py`, `test_measurement_faults.py`, `test_measurement_sessions.py`, `test_measurement_ownership_regressions.py` | `test_measurement_engine.py`; preserve distinct ownership and failure paths. |
| Runner, snapshots, and terminal-snapshot modules, including their regression files | `test_measurement_runner.py`; merge related scenarios without removing concurrency boundaries. |
| Five `test_measurement_persistence*.py` modules | `test_persistence.py`; parameterize common metadata and fault cases. |
| Four `test_measurement_*_gui.py` modules, `test_moke_gui.py`, FE GUI-state and AMR presentation review cases | `test_gui.py`; use shared scenario assertions plus focused family cases. |
| Three family compatibility modules, `test_measurement_compatibility_manifest.py`, `test_measurement_contract_harness.py` | Move lasting schema/numerical assertions to measurement and protocol suites. Retain only a few negative checks proving the shared comparator rejects missing columns, unit/time errors, and missing enabled readbacks. |
| Compatibility manifest/harness and reference fixtures | Keep independent goldens, required schema/unit expectations, tolerances, and compact provenance. Retire obsolete migration-stage selectors and historical manifest structure checks after their lasting requirements are accounted for. |
| `test_simulation_contracts.py`, `test_simulation_review.py`, `test_virtual_bench.py`, `test_virtual_consumer_plants.py`, relevant waveform hook reviews | `test_simulation.py` and the appropriate virtual/category suite; retain material/plant and connection behavior. |
| `test_analysis_hysteresis.py`, `test_analysis_pund.py`, `test_waveform_reader.py` | Keep focused modules; remove only demonstrated duplicates. Extract independent field calibration coverage from MOKE/AMR tests into `test_field_calibration.py`. |
| `test_measurement_developer_guide.py` | `test_examples.py`; retain published-example validity and its own cleanup behavior. |

All 18 review/regression modules should eventually have their surviving assertions under the feature they protect. Their filenames alone are not evidence that their contents are unnecessary.

One current compatibility check reads an old manifest with `git show`. Replace historical execution dependencies with committed independent reference data and provenance where they no longer serve a live compatibility requirement. Only remove CI's full-history checkout after confirming no remaining checks need repository history.

**8. Proposed organization**

The target is ten instrument category modules plus fifteen focused modules:

`test_instrument.py`, `test_discovery.py`, `test_virtual_instrument.py`, `test_measurement.py`, `test_measurement_engine.py`, `test_measurement_runner.py`, `test_measurement_protocols.py`, `test_persistence.py`, `test_gui.py`, `test_simulation.py`, `test_waveform_reader.py`, `test_analysis_hysteresis.py`, `test_analysis_pund.py`, `test_field_calibration.py`, and `test_examples.py`.

Keep supporting discovery, scripted transports, driver cases, and measurement cases in a small `tests/support/` package; keep independent data under `tests/fixtures/`. Use ordinary pytest fixtures and parametrization, with only lightweight case records where helpful. Avoid creating a general testing framework with its own plugin system or extensive internal test suite.

A new driver should require its implementation and a small factory/response entry, then inherit the category checks automatically. A new measurement should require its factory/options/schema entry, then inherit the common run checks automatically. Add dedicated assertions only for behavior the existing contract cannot express.

**9. Implementation order and completion criteria**

1. **Establish the baseline.** Collect and run the current suite in the supported environment. Record case count and durations. Map existing assertions to contract, implementation-specific behavior, or obsolete migration scaffolding. Static similarity is a candidate for review, not proof of redundancy.
2. **Build the AWG pilot.** Extract discovery and a minimal transport fixture. Run the replacement AWG tests alongside the existing AWG tests. Prove missing registration, a required no-op method, and a wrong trigger command are caught. Remove covered duplicates once the mapping is complete.
3. **Extend instrument coverage.** Use sourcemeters to verify the design handles source/read/compliance behavior, then cover the other categories, adapters, and shared virtual hooks. Report existing gaps explicitly instead of broadening unsupported capability lists to make the suite green.
4. **Generalize measurements.** Extract the configurable fake engine fixture and small real measurement case specifications. Consolidate lifecycle/runner tests, then replace repeated family boilerplate while retaining scientific and shutdown checks.
5. **Consolidate supporting areas.** Merge persistence and GUI cases, simplify compatibility scaffolding, and move each review/regression assertion to its feature. Delete fixtures only after checking imports and runtime use.
6. **Validate the replacement and report the reduction.** Run the affected suites during each step, then the full suite on the existing Python 3.9/3.13 CI matrix, offline notebooks, and documentation checks. Compare maintained lines, modules, collected cases, and runtime with the baseline. Document which cases were removed as duplicates versus retired requirements.

Completion requires that every discovered supported driver/adapter and measurement is either exercised by its shared contract or identified as an explicit existing gap; no implementation silently drops out. Real hardware must not be opened during ordinary test collection or execution.

Use a few controlled negative cases to verify the new assertions detect the failures we care about: a missing current column, an incorrect time/unit scale, an omitted shutdown command, an extra AMR step, and a rejected caller interfering with another run. Reuse appropriate existing regression cases for these checks instead of adding another large layer of tests.

Keep production APIs, numerical behavior, saved formats, and the deferred simulation work outside this consolidation. If a new shared assertion exposes a real production defect, record it separately and resolve its disposition explicitly; do not weaken the assertion or silently bundle a behavior change into the test cleanup.
