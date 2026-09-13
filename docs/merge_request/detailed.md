# PIEC branch merge request detailed comparison

This document explains the changes proposed by `measuremnt-standarization` relative to `master`, organized for reviewers responsible for drivers, measurements, simulation, analysis, user interfaces, and data handling. The branch replaces separate measurement execution paths with a shared lifecycle and persistence layer, adds MOKE and USB1208HS support, and makes virtual setups explicitly configurable and reproducible.

The merge changes public APIs and saved column names. Scientific compatibility is checked through numerical references and targeted defect repairs; preserving every old call signature or accidental behavior is not the migration policy. Review the new execution and data contracts together with the instrument-specific behavior.

The companion [summary](summary.md) is suitable for the merge request overview. Each major part below has a summary followed by implementation details, effects on consumers, and source or test references.

## Comparison scope

| Item | Compared value |
|---|---|
| Source branch | `measuremnt-standarization` |
| Source commit | `99a8d697901468e7f7c7db275994fb1fab7a3984` |
| Target ref | Local `master` |
| Target commit and merge base | `9d9760242f44a79401626964f0122cc91b149c18` |
| Ahead and behind | 103 ahead, zero behind |
| Changed files | 176: 116 added and 60 modified; no deleted files |
| Text change | 50,406 additions and 3,653 deletions |
| Comparison method | `git diff master...HEAD`, checked against the source and target implementations |

Master is an ancestor of this branch, so the merge-base comparison and direct comparison of these two commits describe the same file changes. These are local refs; the comparison does not assert that a remote master was freshly fetched. Counts describe the committed implementation before adding these two review documents and exclude uncommitted changes.

### Change distribution

The categories below are mutually exclusive. Line counts include documentation, notebook JSON, and test fixtures; they are a size guide, not a measure of functional complexity.

| Area | Files | Added lines | Removed lines |
|---|---:|---:|---:|
| Physical drivers and common driver contracts | 16 | 1,303 | 433 |
| Virtual drivers | 8 | 3,356 | 503 |
| DAQ emulators | 3 | 195 | 44 |
| Driver documentation and notebook | 2 | 157 | 342 |
| Measurement framework and families | 15 | 8,747 | 907 |
| Measurement documentation | 2 | 767 | 5 |
| Simulation models and benches including their documentation and JSON | 9 | 1,832 | 37 |
| Analysis | 4 | 952 | 219 |
| GUIs and measurement examples | 12 | 2,361 | 1,033 |
| Tests and fixtures | 82 | 27,337 | 11 |
| Project and user documentation | 20 | 3,324 | 116 |
| CI packaging and scripts | 3 | 75 | 3 |
| Total | 176 | 50,406 | 3,653 |

### Reading map

- [Physical drivers and common driver interfaces](#physical-drivers-and-common-driver-interfaces)
- [DAQ emulators](#daq-emulators)
- [Virtual drivers](#virtual-drivers)
- [Simulation models and virtual benches](#simulation-models-and-virtual-benches)
- [Shared measurement framework](#shared-measurement-framework)
- [Measurement families](#measurement-families)
- [Analysis and calibration](#analysis-and-calibration)
- [Data schemas and saving](#data-schemas-and-saving)
- [GUIs and notebooks](#guis-and-notebooks)
- [Documentation packaging and CI](#documentation-packaging-and-ci)
- [Compatibility and migration reference](#compatibility-and-migration-reference)
- [Validation evidence and merge review](#validation-evidence-and-merge-review)

## Physical drivers and common driver interfaces

**Summary.** Hardware-facing changes establish the driver behavior needed by the migrated measurements: usable AWG triggering, clearer DAQ capabilities, reliable DMM voltage configuration and overload handling, and consistent sourcemeter calls. USB1208HS is a new supported driver family. The underlying `Instrument`, `Scpi`, automatic discovery implementation, and virtual dispatch implementation are unchanged in this branch comparison.

### AWG trigger interface

On master, `Awg.output_trigger()` was nested inside `configure_trigger()` rather than declared as a class method. This branch corrects its placement. The base declaration is still a placeholder: its presence alone does not prove that a concrete model implements triggering.

`Awg.configure_trigger()` and the Keysight 81150A override also had a reversed condition: they called the trigger-source setter when the supplied source was `None`. The branch changes this to `is not None`, so a provided source is applied and an omitted source is left unchanged.

A new `ScpiTriggerMixin` implements common validation, source/edge selection, burst mode selection, and software triggering for the following drivers:

| Driver | Change in this branch | Important boundary |
|---|---|---|
| Agilent 33220A | Adds source, external edge, triggered/gated burst, and `*TRG` command handling | Adjustable external trigger level is not implemented by this addition |
| Agilent 33500 | Adds channel-specific triggering and 0.9 to 3.8 V programmed trigger-level support | This level is the programmed output trigger level, not a direct external input-threshold setting; the class channel list must match the connected model |
| Rigol DG1000 | Adds trigger behavior selected by legacy versus DG1000Z protocol | Legacy triggering configuration is channel 1 only; remote software initiation remains unverified and raises |
| Rigol DG4000 | Adds model-specific burst/sweep source and slope command routing, burst mode, and software trigger | `trigger_function="sweep"` selects sweep; combining sweep with burst mode is rejected |
| Keysight 81150A | Fixes the source condition in the existing configuration method | Existing model command implementation is retained |
| Siglent SDG2000X | Normalizes trigger source, slope, and mode inputs to uppercase | Adjustable trigger-level behavior is still unimplemented in the Python driver |

For the new mixin, source aliases such as `MAN`/`BUS` and `INT`/`IMM` map to model-specific tokens. Invalid channels, sources, modes, and functions are rejected before configuration writes. An I/O failure still propagates after any earlier successful writes; the driver does not undo a partially applied physical configuration.

Trigger configuration does not itself select a waveform, enable burst or sweep, turn on the analog output, or establish cross-instrument synchronization. `output_trigger()` sends the device-wide software trigger to already prepared channels. It is not a claim about a physical trigger-output connector or simultaneous response across instruments.

### AWG command corrections beyond triggering

Rigol DG1000 now performs a read-only identity query on its first operation, caches the selected dialect, and refuses to guess for unknown identities. A caller can explicitly choose `protocol="dg1000"` or `"dg1000z"` for a verified setup. Legacy output and waveform commands use the appropriate unprefixed or channel-2-suffixed forms; Z models use the `SOUR<n>` and `OUTP<n>` forms. Frequency, amplitude, offset, phase, waveform, output, and pulse commands follow that selection.

Undocumented legacy pulse-transition commands now raise instead of sending a guessed Z command. Z rise/fall setters affect the requested transition, and the combined setter uses both transitions. Agilent 33500 converts the common `USER` waveform name to its `ARB` command and makes the combined pulse-edge setter apply both rise and fall times.

**Files and evidence:** [AWG base](../../src/piec/drivers/awg/awg.py), [SCPI trigger mixin](../../src/piec/drivers/awg/_scpi_trigger.py), [DG1000](../../src/piec/drivers/awg/rigol_dg1000.py), [trigger support audit](../awg_trigger_support.md), [AWG contract tests](../../tests/test_awg_contract.py), and [command tests](../../tests/test_awg_trigger_commands.py). The audit contains the command references and model-specific limitations; its mock tests are not physical certification.

### DAQ family support

The new `USB1208HS` class covers USB-1208HS, USB-1208HS-2AO, and USB-1208HS-4AO. It advertises family capabilities and then narrows physical-instance analog outputs from identity: zero, two, or four AO channels. The implementation supports input-mode/range configuration, scalar and scanned acquisition, analog output, digital I/O, and output scan management. Scanned input requests scaled engineering units from the Universal Library instead of assuming a raw converter encoding.

The driver declares eight single-ended or four differential inputs, mode-dependent ranges, 16 digital I/O lines, and high-rate scan capabilities. The class-level virtual capability describes the family maximum; a physical base model without AO does not acquire analog outputs merely because the family class advertises them.

USB231 gains concrete implementations for common AI, AO, DI, DO, and DIO selection/configuration methods, plus generic `quick_read()` and `read_data()` entry points. Capability metadata expresses the fixed +/-10 V ranges, AI rate bounds of 1 to 50,000 samples/s, and AO bounds of 1 to 5,000 samples/s. It retains differential mode as the physical startup default and updates available AI channels with input mode.

The common `Daq` interface is reorganized and documents input mode and trigger pulses. Optional vendor imports allow module import without opening physical MCC hardware; opening hardware still requires its vendor dependencies.

### DAQ trigger pulses

The new common API exposes `get_trigger_pulse_capabilities()`, `validate_trigger_pulse()`, and `send_trigger_pulse()`. A caller chooses a resource, channel, width, polarity, and optional hardware-timing requirement.

- The digital fallback requests idle, active, then idle via digital output. USB231 uses this software-timed path. USB and operating-system latency affect launch and pulse width.
- USB1208HS adds timer resource 0 through `pulse_out_start` and `pulse_out_stop`, requesting one hardware-timed pulse. The implementation accepts widths from 25 ns to 50 s, waits using the returned programmed period, and reports the quantized programmed width.
- Cleanup attempts restore idle or stop the timer on failure or cancellation. Pulse calls are serialized, but unrelated users of the terminal still need coordination.
- `require_hardware_timing=True` rejects software and simulated timing. The implementation never silently changes from the requested timer pin to a digital pin.

These are pulse-output capabilities, not triggered analog acquisition or playback synchronization. Physical widths and electrical behavior remain to be measured.

**Files and evidence:** [DAQ base](../../src/piec/drivers/daq/daq.py), [USB231](../../src/piec/drivers/daq/usb231.py), [USB1208HS](../../src/piec/drivers/daq/usb1208hs.py), [pulse behavior](../daq_trigger_output.md), [DAQ contracts](../../tests/test_daq_contract.py), and [pulse tests](../../tests/test_daq_trigger_pulses.py).

### DMM configuration and overloads

Agilent 34410A and Keithley 2000 now implement configuration paths that were missing or incomplete, including coupling and resistance sensing mode. Their cached SCPI sense function is initialized, synchronized when getters select another function, and restored after reset. Default DC and two-wire arguments avoid the former `None.upper()` problem in function selection. NPLC requests for unsupported functions raise explicitly.

Read methods return scalar floats. Hardware overload representations are normalized to signed infinity instead of being accepted as huge finite voltages or currents. The measurement or adapter decides how to handle that result; MOKE and AMR readouts reject non-finite scientific samples. Virtual DMM preserves IEEE `inf`, `-inf`, and `nan` so overload paths can be exercised.

Keithley 193A continues to use DDC commands such as `F0X` for DC voltage, not SCPI. Its parser recognizes overload prefixes and magnitude thresholds. Current, resistance, and temperature read failures propagate rather than printing and returning `None`. Unsupported manual range and software-commanded four-wire configuration raise explicitly; physical four-terminal wiring is a separate matter.

**Consumer effect:** Do not assume that every optional configuration call succeeds on every DMM, or that a returned float is finite. Declared support should determine configuration; a transport error is not evidence that an option is simply unavailable.

**Files and evidence:** [34410A](../../src/piec/drivers/dmm/agilent_34410a.py), [Keithley 2000](../../src/piec/drivers/dmm/keithley_2000.py), [Keithley 193A](../../src/piec/drivers/dmm/keithley193a.py), [DMM audit](../dmm_voltage_read_audit.md), and [DMM contract tests](../../tests/test_dmm_contract.py).

### Sourcemeter interface

The physical `Sourcemeter`/Keithley 2400 interface on master already used channel-first calls. This branch aligns `VirtualSourcemeter` and the measurement callers with that contract and adds `get_resistance(channel=1)` to the base interface. Keithley 2400 methods now reject invalid channels before sending commands.

Use `set_source_voltage(channel=1, voltage=1.0)`, `set_sense_mode(channel=1, sense_mode="2W")`, and similarly explicit calls. Treat the first positional argument as the channel. The final branch does not introduce a legacy positional-argument normalizer or compatibility layer; intermediate commit messages about such a layer do not describe the final API.

**Files and evidence:** [base interface](../../src/piec/drivers/sourcemeter/sourcemeter.py), [Keithley 2400](../../src/piec/drivers/sourcemeter/keithley2400.py), and [sourcemeter contract tests](../../tests/test_sourcemeter_contract.py).

## DAQ emulators

**Summary.** The existing adapters become more responsive to the wrapped DAQ's capabilities, and AWG-shaped pulse output can use the new generic DAQ pulse API.

`DaqAsAwg` maps its one-based analog channels to the DAQ's declared AO channels, derives sample-rate bounds from AO capability metadata, and validates requested synthesis rates. It detects actual hardware scan methods rather than relying on dynamic attribute presence alone. Existing hardware-scan and software-generation paths remain.

`configure_trigger_output()` stores an explicitly validated pulse resource without I/O; `output_trigger()` delegates to the wrapped DAQ. Its trigger configuration method rejects requests for triggered analog playback. This makes the limitation visible at the API boundary.

`DaqAsOscilloscope` uses the DAQ's AI rate limits instead of assuming USB231's 50 kHz ceiling. It chooses a supported voltage range and can calculate capture duration from `_last_ai_scan_rate`. The range helper selects the narrowest containing range, or the widest advertised range when none contains the requested span; this is not proof that an out-of-range signal can be captured without clipping. Existing scan-to-software fallback behavior also remains.

**Review boundary:** The branch's recorded adapter audit explicitly distinguishes DAQ/AWG adapter tests from complete `DaqAsOscilloscope` integration. A scope-shaped dictionary in a waveform-normalization test is not an end-to-end adapter run.

**Files and evidence:** [capability helpers](../../src/piec/drivers/emulators/_daq_capabilities.py), [DAQ as AWG](../../src/piec/drivers/emulators/daq_to_awg.py), [DAQ as oscilloscope](../../src/piec/drivers/emulators/daq_to_oscilloscope.py), and the DAQ/AWG tests cited above.

## Virtual drivers

**Summary.** Seven virtual families gain generic per-instance hooks so setup and material behavior can be supplied externally. Their public driver role remains recognizable to measurements; simulation wiring, units, validation, errors, and reset ownership become explicit.

### Shared hook behavior

Hooks are supplied through constructors or setters/properties. Conflicting hook aliases are rejected. Signature binding selects supported arguments before invocation, so an exception inside a hook is propagated rather than interpreted as a reason to retry it with a different argument list. Explicit hooks take priority over historical unhooked behavior.

Reset restores driver-owned configuration while retaining the hook. A driver reset does not automatically reset a closure's random generator, material, or clock. Setup owners or `VirtualBench` coordinate those resets. Driver-local assignments to fallback sample properties no longer need to mutate a global material for the migrated paths.

### Changes by virtual family

| Family | Injected behavior | Main behavioral change and limitation |
|---|---|---|
| `VirtualAwg` | `waveform_hook`, `apply_hook`, or `trigger_hook` | Generates a voltage/time waveform for an external consumer; validates settings and trigger behavior; uses its own resettable random stream. Explicit hook paths keep material physics outside the driver |
| `VirtualScope` | `waveform_hook`, `channel_hook`, or `data_hook` | Reads channel-specific waveforms from an external source; accepts supported tuple, mapping, and DataFrame forms; validates shapes and timing; keeps scale/range state consistent |
| `VirtualSourcemeter` | `load_hook`, `source_hook`, `measure_hook`, or `transport_hook` | Supports voltage/current sourcing and load-solved compliant terminal pairs; distinguishes setpoints, effective output, and compliance status |
| `VirtualDMM` | `voltage_reader` or `reader_hook` | Returns scalar voltage with declared coupling forwarded where supported; rejects collection results; preserves non-finite overload values |
| `VirtualLockin` | `xy_reader` or `transport_hook` | Returns a plain finite `(X, Y)` tuple in volts, forwards declared excitation current, and derives phase using `atan2` |
| `VirtualCalibrator` | `output_hook` or `field_hook` | Notifies effective electrical output including off/reset; retains stored setpoints separately; failed notifications mark output unconfirmed |
| `VirtualStepper` | `angle_hook`, `position_hook`, or `step_hook` | Reports absolute/delta angle and step state; validates integral steps and direction; reset sends the actual delta to zero; failures mark motion unconfirmed |

The AWG and scope also receive waveform consistency corrections, including amplitude/offset/polarity behavior, trigger handling, acquisition scaling, and support for pre-trigger scope timestamps. Driver waveform dialects still exist: the measurement-level `WaveformReader` supplies canonical lowercase `time`/`voltage` data. These are different layers of normalization.

### Sourcemeter load physics and state

A hooked sourcemeter accepts a callable or `ElectricalLoadContract`. The load computes both terminal voltage and current under compliance. The driver checks the returned pair instead of clipping one quantity independently and thereby implying a different load. Invalid or incomplete active responses fail.

Configured source values remain available while disabled effective output is reported as zero voltage/current. This is a simulation convention for isolated terminals; it does not discharge an external capacitor or establish that physical residual charge is zero. Hook failures leave output unconfirmed and block effective-output/compliance reads until an explicit recovery command succeeds.

Stateful loads use the setup timebase. Reads at the same time and operating point can reuse one evaluation; advancing a capacitor requires an explicit positive time step. Merely calling another getter does not create elapsed time.

### Remaining virtual scope

`VirtualDaq` adds simulated pulse recording and idle restoration but does not receive the seven-family material hook redesign. `VirtualPulser` and `VirtualRFSource` remain state-oriented implementations with no code changes in this diff. `VirtualInstrument`, `virtual_dispatch.py`, and the exact `"VIRTUAL"` model-dispatch mechanism already exist on master.

Global fallback samples are **not removed** by this branch. New private setup paths avoid them, and generic fallback behavior remains for external consumers. Do not describe this merge as eliminating all shared state or automatically isolating every adapter.

**Files and evidence:** The eight changed virtual files are [AWG](../../src/piec/drivers/awg/virtual_awg.py), [scope](../../src/piec/drivers/oscilloscope/virtual_oscilloscope.py), [sourcemeter](../../src/piec/drivers/sourcemeter/virtual_sourcemeter.py), [DMM](../../src/piec/drivers/dmm/virtual_dmm.py), [lock-in](../../src/piec/drivers/lockin/virtual_lockin.py), [calibrator](../../src/piec/drivers/dc_calibrator/virtual_calibrator.py), [stepper](../../src/piec/drivers/stepper_motor/virtual_stepper.py), and [DAQ](../../src/piec/drivers/daq/virtual_daq.py). Dedicated `test_virtual_*_hook.py` suites and the [waveform corrections tests](../../tests/test_waveform_hooks_review.py) cover these contracts.

## Simulation models and virtual benches

**Summary.** Simulation becomes a setup layer with explicit roles, connected instruments, deterministic state, and reproducible fixtures. Existing FE and magnetic models remain scientific components rather than being embedded in generic driver hooks.

### Role contracts and models

New contracts describe electrical loads, field-responsive materials, angle-dependent resistance, and waveform-responsive materials. `LoadResponse` carries terminal quantities, compliance state, time, and detached immutable model state. Electrical quantities use volts, amperes, ohms, and seconds.

- `ResistorLoad` provides resistance-based response with optional temperature/noise behavior and compliance in both source modes.
- `DiodeLoad` provides Shockley conduction with optional series resistance and compliance behavior. It is not a reverse-breakdown model.
- `CapacitiveLoad` tracks charge with a time-stepped backward-Euler calculation and leakage. A positive elapsed time is required; timestep choice affects the resolved behavior.
- `HystereticMagneticMaterial` adds field-history-dependent magnetic response for MOKE setups.
- `MagneticSample` implements the angle-dependent contract with seeded noise and reset. It requires excitation current explicitly and returns `(R * current, 0.0)` for its resistive voltage response. A programmed reference amplitude is not silently treated as measured sample current.
- The FE material adopts the waveform contract and explicit reset/time behavior. Its native polarization is in C/m^2; measurement analysis explicitly converts to uC/cm^2.

### Bench ownership and routing

`VirtualBench` creates and owns named models and instruments. It validates supported driver classes, copies model parameters, and reserves route ports to prevent ambiguous wiring. Named random streams derive from the bench seed and names, so adding an unrelated stream does not consume another stream's sequence. Explicit seeds support reproduction across instances; reset also replays an unseeded bench within that instance.

Three built-in route types connect a sourcemeter to a load, an electrical/magnetic/optical MOKE plant to source and detector, or an AWG trigger to a scope channel. The MOKE plant has its own copied calibration and optical gain/offset/noise. The measurement calibration is a separate input. The direct waveform route copies triggered samples and returns zeros for output-off triggers; it does not model scope resampling, trigger latency, or FE material response.

Reset attempts all instrument resets and all model resets, then resets clock/random streams and route buffers. Connections persist; instrument configuration returns to defaults and must be reapplied. `BenchResetError` preserves component names and exceptions. A failed reset is not a successful shutdown confirmation. Operations within one bench should be serialized; distinct benches can be independent.

### Fixture and example migration

IV, MOKE, FE, and AMR numerical fixtures now construct private benches through [virtual setup fixtures](../../tests/fixtures/virtual_setups.py). Their numerical reference values are retained while instrument identity metadata identifies the virtual instruments. The AMR numerical fixture deliberately declares its nonzero quadrature law; that response is not fabricated by the generic resistive model.

FE and AMR notebook/GUI consumers use `connect_fe_plant` and `connect_amr_plant` to attach private materials to caller-owned instruments. These helpers do not take over connection closing or reset the caller's instruments. The FE parameter JSON is packaged for examples and copied per setup.

**Files and evidence:** [contracts](../../src/piec/simulation/contracts.py), [bench](../../src/piec/simulation/bench.py), [magnetic material](../../src/piec/simulation/magnetic_material.py), [hysteretic material](../../src/piec/simulation/hysteretic_magnetic_material.py), [FE material](../../src/piec/simulation/fe_material.py), [setup helpers](../../src/piec/simulation/setups.py), [bench guide](../virtual_bench.md), [simulation tests](../../tests/test_simulation_contracts.py), and [bench tests](../../tests/test_virtual_bench.py).

## Shared measurement framework

**Summary.** `BaseMeasurement` replaces duplicated orchestration with one execution owner, one outcome model, retained data, explicit shutdown reporting, and shared saving behavior. `MeasurementRunner` supplies asynchronous execution without putting experiment logic in the GUI.

### Before and after

On master, IV, discrete waveform/FE, and magneto-transport families implement their own run, acquisition, saving, plotting, and stop behavior. For example, IV explicitly configured, swept, disabled output, and saved in sequence; an exception before the disable step could bypass that path. FE analysis was driven by saved files. Magneto-transport mixed measurement logic and live plotting.

The new full-run path is reservation, configuration, acquisition, shutdown, analysis, optional publication, and terminal reporting. Run states include `IDLE`, `STARTING`, `CONFIGURING`, `RUNNING`, `STOPPING`, `SAFING`, `ANALYZING`, `SAVING`, `COMPLETED`, `ABORTED`, and `FAILED`. A separate safety status records `UNKNOWN`, `NOT_NEEDED`, `SAFING`, `SAFE`, or `UNSAFE`.

The engine controls phase order; individual families implement what configuration and shutdown mean. IV and waveform acquisition defer output activation until acquisition. MagnetoTransport configures its field and optional excitation during its configuration hook, after validating setup and shutdown requirements. The common engine should not be read as a universal guarantee that all physical outputs remain off throughout every family's configuration.

### Ownership cancellation and failure behavior

Reservation tokens identify a run and generation. Duplicate execution, stale tokens, concurrent runs, and cross-thread hardware-bearing calls are rejected. Stop requests are cooperative; acquisition loops and dwell/ramp helpers check them. Stop before instrument I/O records an abort without issuing hardware shutdown commands for an operation that never began.

After configuration/acquisition is entered, the engine attempts shutdown on completion, cancellation, failure, and Python interrupts. Shutdown actions are recorded individually. Later cleanup failures do not replace an earlier acquisition/configuration error; a shutdown failure can itself become the primary `HardwareSafetyError` when there was no earlier failure. Incomplete or failed acquisition skips normal scientific analysis and may retain/save raw partial data according to policy.

`SAFE` reflects the shutdown actions and available readback evidence recorded by the implementation. It must not be presented as an independent physical interlock certification. Measurement shutdown also does not close the instrument connection, preserving access for diagnosis and recovery.

### Synchronous and interactive APIs

`run_experiment(save=False)` returns an in-memory DataFrame without requiring an output directory. Successful full runs return analyzed data; cooperative abort returns retained raw partial data. Failures re-raise while retaining data and diagnostics on the measurement.

`session(save=False, options=...)` holds one execution lease for interactive configure/capture operations and guarantees shutdown at context exit. Standalone `configure_instruments()` and `capture_data()` execute transient scopes with cleanup; they do not leave a persistent session active between separate calls. Use an explicit session when several operations must share ownership and configuration.

New families implement protected hooks such as `_configure_instruments`, `_capture_data`, `_safe_shutdown`, `_analyze_data`, and `_stage_side_artifacts`. The public engine wrappers remain common. Constructors accept injected instruments/settings and defer identity queries and other hardware I/O until execution.

### Runner snapshots and GUI delivery

`MeasurementRunner.start()` reserves synchronously before launching a non-daemon worker. Startup failures and unstarted workers are finalized so they do not strand execution ownership. Ownership is retained through terminal delivery and worker completion.

Snapshots contain run identity, generation, sequence, state, safety, progress, and detached views. Bounded display queues favor the newest data and can drop obsolete frames; state, safety, and terminal control events use a separate reliable queue. Bounded live views do not replace the complete raw result or terminal data. Per-run views reset so a failed second run does not display the first run's result as current.

Closing requests Stop, then checks worker termination, lifecycle status, and shutdown status. Clean never-started idle state can close; a terminal run with unknown or unsafe shutdown cannot use ordinary close as confirmation. The GUI continues polling instead of blocking its event loop on a long join.

**Files and evidence:** [base engine](../../src/piec/measurement/base.py), [contracts](../../src/piec/measurement/contracts.py), [runner](../../src/piec/measurement/runner.py), [public exports](../../src/piec/measurement/__init__.py), and [developer guide](../../src/piec/measurement/MEASUREMENT_DEVELOPER_GUIDE.md). Tests cover [lifecycle](../../tests/test_measurement_lifecycle.py), [engine](../../tests/test_measurement_engine.py), [sessions](../../tests/test_measurement_sessions.py), [faults](../../tests/test_measurement_faults.py), [snapshots](../../tests/test_measurement_snapshots.py), and [runner behavior](../../tests/test_measurement_runner.py).

## Measurement families

### IV sweep

**Summary.** IV moves from a standalone loop and saver to the shared engine, with controlled transitions and retained results when a run stops or fails.

The constructor takes the sourcemeter positionally and experiment settings as keywords. `output_dir` replaces `save_dir`. Configuration disables a possibly active output before identity/source/sense commands, programs electrical zero with compliance, and applies the sensing mode. Instrument calls use the channel-first contract explicitly.

Acquisition enables output and uses paced, cancellable ramps both to the start voltage and between sweep points. `ramp_step` bounds the command step and `ramp_delay` sets pacing. Intermediate ramp commands do not become extra measurement rows. Stop during a ramp or dwell prevents the pending sample from being read.

Raw rows are retained even when reading or callbacks fail. Live snapshots show at most the latest 100 points; terminal results retain the full sweep. Shutdown attempts a paced return to zero, output disable even if that ramp failed, and a final zero command. It does not close the source connection.

**Schema and migration:** `voltage (V)` and `current (A)` become `voltage` and `current`, with V/A in metadata. Replace the old `configure_sourcemeter`, `sweep`, and `save_data` workflow with the shared run/session APIs.

**Sources:** [IV implementation](../../src/piec/measurement/iv_sweep.py), [IV tests](../../tests/test_measurement_iv.py), [IV regression review](../../tests/test_measurement_iv_review.py), and [IV and MOKE compatibility tests](../../tests/test_measurement_iv_moke_compatibility.py).

### MOKE

**Summary.** MOKE is a new family relative to master. Its implementation was introduced and then standardized within this branch; it should be described as a new feature in this merge.

`MokeMeasurement` combines a sourcemeter, voltage-reading DMM, `FieldCalibration`, and a user-supplied closed output cycle. A source can operate in volts or amperes as declared by calibration. The constructor validates the cycle, source limits, compliance, ramp settings, and optional field-reader units before execution.

Acquisition ramps through each requested point, reads detector voltage, and optionally reads field sequentially through a separate field reader. `field_calibrated` remains distinct from `field_measured`; `field_time` records the field reading's relative time. Measured field is not silently substituted into the source-control calibration, and sequential readings are not represented as simultaneous hardware sampling.

The family retains all raw points and exposes bounded raw views, the last complete cycle, and an average over complete cycles. Partial/aborted cycles do not enter completed-cycle averaging. Detector and field non-finite readings fail; collected rows survive failure. Shutdown attempts electrical zero and output disable, with support for a setup-specific additional handler.

**Schema and interpretation:** Base columns are `time`, `cycle`, `point`, `direction`, `source_output`, `field_calibrated`, and `detector_voltage`; measured-field mode adds `field_measured` and `field_time`. Geometry is recorded setup information. Detector voltage is an optical readout, not automatically an absolute magnetization or Kerr-angle calibration.

**Sources:** [MOKE implementation](../../src/piec/measurement/moke.py), [MOKE guide](../source/measurements/moke.md), [MOKE tests](../../tests/test_measurement_moke.py), [review regressions](../../tests/test_measurement_moke_review.py), and the [new GUI](../../Measurements/MOKE/MOKE_GUI.py).

### Discrete waveform acquisition

**Summary.** The common FE acquisition base now obtains normalized in-memory data under the shared lifecycle, with explicit trigger ordering and cleanup.

Configuration disables the configured AWG output and prepares AWG/scope settings. Acquisition checks cancellation, arms the scope, enables the AWG, checks again, fires the trigger, waits cooperatively, and reads through `WaveformReader`. A setup or cancellation failure prevents the later activation steps from proceeding.

`WaveformReader` adapts supported driver return shapes and column dialects into float arrays and a `time`/`voltage` DataFrame with s/V units. It inspects the driver's calling convention before fetching data instead of retrying a driver read after an arbitrary `TypeError`. It validates shape, length, channel selection, and finite acquisition data, and offers `WaveformRecord` with acquisition metrics.

Shutdown attempts to disable the configured and other advertised AWG channels, then zero the configured channel's amplitude. This is broader than turning off just one channel; callers must coordinate instrument sharing accordingly. It is a sequence of recorded attempts, not proof that failed hardware obeyed them.

**Migration:** Replace `apply_and_capture_waveform` and `save_waveform` workflows with the engine run/session/capture methods. Raw waveform columns become lowercase. Hardware scope drivers are not all rewritten; normalization is in the adapter.

**Sources:** [waveform classes](../../src/piec/measurement/discrete_waveform.py), [reader adapter](../../src/piec/measurement/adapters/waveform_reader.py), [reader tests](../../tests/test_waveform_reader.py), and [waveform measurement tests](../../tests/test_measurement_discrete_waveform.py).

### Hysteresis loops

**Summary.** Hysteresis retains triangular excitation and polarization analysis while separating computation from saving and putting shutdown ahead of post-processing.

`HysteresisLoop` builds on standardized waveform acquisition. Frequency, cycle count, area, shunt resistance, baseline count, amplitude, DC offset, and alignment settings are explicit. Analysis receives the raw waveform directly, so saving a CSV is no longer a prerequisite. Applied-voltage reconstruction includes the requested DC offset, including idle portions, and alignment settings are validated.

Plot helpers produce the polarization-voltage, current-voltage, and trace views. Saved plots are staged as side artifacts through the shared publication hook; in-memory runs can analyze without files. Run options such as `save_plots`, `show_plots`, and `auto_timeshift` are checked before execution.

**Schema:** `time`, `voltage`, `current`, `polarization`, and `applied_voltage`, with s, V, A, uC/cm^2, and V respectively. Raw partials remain `time`/`voltage` with their own units. Area input remains m^2.

**Sources:** [HysteresisLoop](../../src/piec/measurement/discrete_waveform.py), [analysis](../../src/piec/analysis/hysteresis.py), [measurement tests](../../tests/test_measurement_hysteresis.py), [analysis tests](../../tests/test_analysis_hysteresis.py), and [FE/PUND numerical compatibility](../../tests/test_measurement_fe_pund_compatibility.py).

### Three pulse PUND

**Summary.** Three-pulse PUND adopts the same acquisition, shutdown, analysis, and publication path while correcting alignment, polarity, and offset consistency.

Reset and measurement pulse parameters are validated and used consistently in programmed waveforms and analysis. Manual/automatic alignment controls the actual pulse slicing and nominal applied waveform. Inadequate or invalid captures are rejected rather than silently producing a plausible result from missing pulse windows. DC offset applies across the reconstructed waveform, including idle intervals.

Analysis computes the individual polarization components and switching difference in memory. Separate plot functions handle switching-polarization and component/trace views. GUI execution uses the common runner, and save/plot settings are validated options rather than ad hoc lifecycle arguments.

**Schema:** `time`, `voltage`, `current`, `polarization`, `polarization_p_hat`, `polarization_p_star`, `polarization_p_hat_r`, `polarization_p_star_r`, `delta_polarization`, and `applied_voltage`. Polarization fields use uC/cm^2. Raw partials keep the acquisition schema.

**Sources:** [ThreePulsePund](../../src/piec/measurement/discrete_waveform.py), [PUND analysis](../../src/piec/analysis/pund.py), [measurement tests](../../tests/test_measurement_pund.py), [analysis tests](../../tests/test_analysis_pund.py), and [polarity regressions](../../tests/test_fe_polarity_options_review.py).

### MagnetoTransport setup roles

**Summary.** Magneto-transport separates field generation, field sensing, electrical readout, and orientation so a setup's calibration and shutdown responsibilities are explicit.

`AMRSetupProfile` combines four adapters:

| Role | Responsibility | Key behavior |
|---|---|---|
| `FieldSource` | Convert a requested field into a source command | Linear, table, or native field mode; validates declared bounds; electrical zero is distinguished from zero calibrated field |
| `FieldReader` | Read field and evaluate agreement with the requested field | Independent sensor calibration and explicit units; configurable tolerance and mismatch policy |
| `TransportReadout` | Read lock-in X/Y voltages and manage declared readout policy | Preserves manual settings by default; explicit configure mode; declared excitation owner and shutdown handler |
| `OrientationController` | Translate requested angles into motor steps | Plans and validates quantized moves, tracks commanded angle, and halts motion during shutdown |

The standardized `MagnetoTransport` implementation is split into `_magneto_transport_base.py` and re-exported through the existing module paths. Its point acquisition and AMR's sweep share the same engine. Profile construction and measurement construction perform no instrument I/O. Execution requires a callable excitation shutdown handler before the field or excitation is configured.

The default `readout_configuration="preserve"` avoids resetting, initializing, autoranging, or overwriting operator-selected lock-in settings. Explicit configuration changes declared reference/input/gain settings. Preserving settings is separate from de-energizing excitation at shutdown. External excitation additionally requires an identified owner.

Field-source and field-reader calibration are independent. `field` is commanded field; optional `field_measured`/`field_time` describe readback. X/Y are volts. The current lock-in role does not claim resistance or derive sample current merely from reference amplitude.

**Sources:** [base](../../src/piec/measurement/_magneto_transport_base.py), [role adapters](../../src/piec/measurement/adapters/amr.py), [role contract tests](../../tests/test_amr_contract.py), [adapter regressions](../../tests/test_amr_adapter_review.py), and [MagnetoTransport tests](../../tests/test_measurement_magneto_transport.py).

### AMR angular sweep and scientific fixes

**Summary.** AMR uses the role-based setup and shared lifecycle, adds explicit start/end and quantized position handling, and repairs incorrect final-angle and field-conversion behavior.

The sweep supports positive or negative angular direction, explicit start angle, exact requested endpoint inclusion, and validation of every planned quantized move before execution. Excessively large sweeps are rejected. Each point moves, settles, reads/averages X/Y, optionally verifies field, and publishes a bounded view. Pause is cooperative and retains the applied field; Stop releases the pause and proceeds to shutdown.

The old endpoint behavior could step the motor again before recording the last point. The committed legacy fixture documents a 180-degree label after actual motion to 225 degrees. The new code records the endpoint without that extra movement. `angle_basis="commanded_quantized"` makes clear that recorded angle follows commanded step quantization, not an encoder reading.

The old `convert_field_to_voltage` helper also disagreed with the declared default 10,000 Oe/V calibration. The new helper divides field by calibration: 100 Oe becomes 0.01 V instead of 10 V. These are intentional defect repairs; the legacy observation is not the scientific result to preserve.

**Schema and migration:** Canonical columns are `angle`, `field`, `x`, `y`; optional field readback adds `field_measured` and `field_time`. Update `arduino` to `stepper` in measurement construction, `save_dir` to `output_dir`, and misspelled `voltage_callibration` to `voltage_calibration`. The profile factory itself still names its instrument argument `arduino`; do not mechanically rename that separate API. Use `options={"readout_configuration": "configure"}` when intentionally configuring the lock-in; preserve is the default.

**Sources:** [AMR implementation](../../src/piec/measurement/magneto_transport.py), [AMR import surface](../../src/piec/measurement/amr.py), [compatibility tests](../../tests/test_measurement_amr_compatibility.py), [sweep regression tests](../../tests/test_amr_sweep_review.py), and [scientific manifest](../../tests/fixtures/measurement_compatibility/manifest.json).

## Analysis and calibration

**Summary.** Hysteresis/PUND analysis becomes DataFrame-based and reusable offline. A new calibration object keeps source-control and field-unit assumptions explicit.

`process_raw_hyst` and `process_raw_3pp` are removed from the final analysis modules. Their replacements are `process_hysteresis` and `process_pund`. They accept acquired DataFrames and metadata/explicit physical parameters, validate inputs, and return `HysteresisAnalysisResult` or `PundAnalysisResult` with data, metadata, and the effective time offset. They do not require an instrument or an intermediate measurement file. Dedicated plotting functions replace plotting embedded in the old processing path.

Both processors handle baseline removal, current calculation from shunt voltage, polarization integration and area conversion, timing, and nominal applied-voltage reconstruction. The tests include finite-input/shape validation, offset handling, alignment, and numerical compatibility. PUND additionally verifies switching and non-switching pulse windows/components. These changes separate numerical computation from artifact publication while preserving the explicitly chosen scientific references.

`FieldCalibration` stores measured `(source_output, field)` pairs with a direct sourcemeter terminal unit of V or A and an explicit field unit. It sorts by output, rejects duplicate output coordinates and non-finite values, interpolates within the measured range, and only permits inverse lookup when field values are strictly monotonic. Extrapolation and silent unit conversion are not supported. Amplifier gain belongs in the measured calibration, not an additional hidden multiplier. Portable CSV import/export preserves units and calibration name.

The older `metadata_and_data_to_csv` utility remains available, but now writes through one UTF-8 handle with flush/fsync. It still opens the target in write mode; it does **not** acquire the new atomic no-overwrite semantics merely because the standard measurement saver does.

**Sources:** [hysteresis](../../src/piec/analysis/hysteresis.py), [PUND](../../src/piec/analysis/pund.py), [field calibration](../../src/piec/analysis/field_calibration.py), [utilities](../../src/piec/analysis/utilities.py), [hysteresis analysis tests](../../tests/test_analysis_hysteresis.py), and [PUND analysis tests](../../tests/test_analysis_pund.py).

## Data schemas and saving

**Summary.** Saving moves into a shared implementation with explicit schemas, units, publication status, and recovery. A measurement is no longer treated as saved simply because acquisition or analysis finished.

### Versioned data contract

Six schema identifiers are registered at version 1: `iv_sweep`, `moke`, `discrete_waveform`, `hysteresis`, `three_pulse_pund`, and `amr`. `MagnetoTransport` uses the AMR data schema rather than introducing a seventh one.

Required metadata includes `measurement_schema`, `measurement_schema_version`, `run_id`, `outcome`, `partial`, `save_requested`, and `column_units_json`. Files use one metadata record, a blank separator, and the data table. Each saved column must have a unit entry; dimensionless indices or categories use JSON null.

| Schema | Canonical data fields | Unit interpretation |
|---|---|---|
| IV | `voltage`, `current` | V and A |
| MOKE | `time`, `cycle`, `point`, `direction`, `source_output`, `field_calibrated`, `detector_voltage` | Seconds, unitless cycle/point/direction, source V or A, declared field unit, detector V |
| Discrete waveform | `time`, `voltage` | s and V |
| Hysteresis | `time`, `voltage`, `current`, `polarization`, `applied_voltage` | s, V, A, uC/cm^2, V |
| PUND | Hysteresis fields plus four polarization components and `delta_polarization` | Polarization quantities use uC/cm^2 |
| AMR | `angle`, `field`, `x`, `y` | deg, declared field unit, V, V |

MOKE and AMR can add measured-field/time columns. Raw FE partials have different columns from analyzed polarization data, so `raw_column_units` describes them separately. Consumers should select files by schema/version and actual column metadata instead of assuming every CSV in a directory has one meaning.

### Publication and collision behavior

The writer validates metadata and units, uses a single UTF-8 handle, flushes/fsyncs, and stages in the destination directory. Completed publication uses an atomic no-replace operation so an existing result is not overwritten. Unsupported filesystem operations fail explicitly unless the caller opts into the supported fallback policy; that fallback does not license overwriting another writer's output.

Candidate reservations use ownership identifiers and guards. Release and stale-file cleanup check ownership; age alone does not authorize taking another run's reservation. An abandoned guard requires investigation, not automatic deletion by an unrelated run.

Measurements that produce plots reserve a shared basename and stage side artifacts. Side artifacts publish before the primary CSV, making the completed CSV the final publication point. This is not a single filesystem transaction covering every file: rollback and recovery preserve ownership and report cleanup problems if a later step fails.

### Partial data and recovery

`save=False` performs no persistence and does not report a fictitious filename. `save=True` requires explicit persistence configuration. `save_partial` controls partial-result publication through the engine's policy; completed and partial paths have different meanings.

If acquisition, analysis, or saving fails, available raw data stays on the measurement. Publication errors can expose `recoverable_staging_paths` on the exception, measurement, and run record metadata. A completed `filename` is assigned only after successful publication; partial results do not masquerade as completed files.

`write_partial_csv` supports deliberate updates to an owned checkpoint. This is not automatic periodic checkpoint scheduling. Cleanup helpers validate run ownership and partial metadata before removing eligible files. Existing user CSVs are not rewritten, and no general legacy converter is added.

**Sources:** [persistence implementation](../../src/piec/measurement/persistence.py), [data guide](../source/user_guide/data_and_analysis.rst), [writer tests](../../tests/test_measurement_persistence.py), [atomic publication tests](../../tests/test_measurement_persistence_atomic.py), [bundle tests](../../tests/test_measurement_persistence_bundles.py), and [recovery tests](../../tests/test_measurement_persistence_recovery.py).

## GUIs and notebooks

**Summary.** Interactive consumers move onto the same execution, shutdown, and data paths as scripts. MOKE adds new entry points; IV, FE, and AMR consumers are updated.

### Shared interaction changes

GUIs use `MeasurementRunner`, non-daemon workers, timer-based display/control polling, and terminal results. Active-run controls prevent competing hardware operations. Stop requests cancellation; closing a window waits for worker completion and an acceptable shutdown status before releasing connections. Unsafe state retains connections for recovery rather than silently closing them.

The updates also track connection ownership so cancellation, failed construction, failed connection changes, and worker startup errors do not indiscriminately close caller-owned connections or leak GUI-owned ones. Live data windows remain bounded while final plots use the complete terminal result.

### Family differences

| Consumer | Specific change |
|---|---|
| IV GUI | Uses standardized constructor/runner APIs, recovers full final plots, and reports retained/staged data after errors |
| MOKE GUI | New calibration and geometry setup, optional measured-field path, cycle views, bounded polling, runner ownership, and recovery behavior |
| FE GUI | Uses runner execution for hysteresis and PUND, restores valid selection/startup state after failures, and applies explicit analysis/plot/polarity options |
| AMR GUI | Integrates setup roles, lock-in preservation/configuration policy, excitation shutdown ownership, pause/stop, and coordinated release |

FE and AMR simulation consumers attach private materials instead of installing shared samples. MOKE uses explicit source/load/material/detector wiring. Notebook examples use the current schemas and lifecycle and remove obsolete stored outputs or physical-discovery paths from the virtual examples.

The new notebook script executes code cells from four notebooks in isolated temporary output directories: AMR testing, MOKE testing, FE testing, and the hysteresis example. It checks execution, not the scientific validity of every illustrative fit. The modified DAQ test notebook is separate from those four automated notebook checks.

**Sources:** [IV GUI](../../Measurements/DCIV/IV_sweep_GUI.py), [MOKE GUI](../../Measurements/MOKE/MOKE_GUI.py), [FE GUI](<../../Measurements/Ferroelectric Testing/FE_testing_GUI.py>), [AMR GUI](../../Measurements/AMR/amr_GUI.py), [GUI helpers](../../src/piec/measurement/gui_utils.py), and [notebook checker](../../scripts/check_measurement_notebooks.py). GUI test suites include `test_measurement_iv_gui.py`, `test_measurement_fe_gui.py`, `test_measurement_amr_gui.py`, `test_moke_gui.py`, and targeted ownership/state regressions.

## Documentation packaging and CI

**Summary.** The branch documents the new developer and user contracts, packages simulation example data, and adds reproducible offline checks to CI.

The new measurement developer guide describes subclass hooks, execution ownership, sessions, queue delivery, shutdown records, and publication. The standardization plan and handoff retain the implementation history and pending work. Public guides for data, execution, quickstart, virtual benches, MOKE, and contribution are updated. Driver audit documents explain AWG commands, DAQ pulse limitations, and DMM reads; physical validation documents provide outstanding bench protocols.

`pyproject.toml` adds package data for simulation JSON. It does not add a new mandatory runtime dependency or raise the declared Python minimum above 3.9 in this diff. The example FE material therefore ships in the wheel rather than depending on a source-tree-only file.

The test workflow now targets Python 3.9 and 3.13, fetches full Git history for immutable-baseline comparisons, and uses a headless matplotlib backend. A documentation job runs the virtual notebook checker and an offline Sphinx build with warnings treated as errors. `PIEC_DOCS_OFFLINE=1` disables intersphinx network fetches for that build.

**Sources:** [workflow](../../.github/workflows/tests.yml), [packaging](../../pyproject.toml), [Sphinx configuration](../source/conf.py), [changelog](../source/administrative/changelog.rst), [standardization plan](../../MEASUREMENT_STANDARDIZATION_PLAN.md), and [handoff](../../MEASUREMENT_HANDOFF.md).

## Compatibility and migration reference

**Summary.** Update consumers deliberately. Existing class names are largely recognizable, but old helper methods, argument conventions, and saved column labels are not generally preserved.

| Existing use or assumption | Required update |
|---|---|
| Measurement `save_dir=...` | Use `output_dir=...`; use `save=False` when files are not wanted |
| Positional experiment settings after instruments | Use keyword-only measurement parameters |
| Sourcemeter positional value calls such as `set_source_voltage(value)` | Use `set_source_voltage(channel=1, voltage=value)` |
| IV `configure_sourcemeter()`, `sweep()`, `save_data()` | Use the shared full-run API or an explicit session |
| FE `apply_and_capture_waveform()`, `save_waveform()`, and measurement-owned `analyze()` workflow | Use run/session/capture and the standalone analysis functions |
| `process_raw_hyst(path, ...)` | Read/obtain a DataFrame and call `process_hysteresis(...)` |
| `process_raw_3pp(path, ...)` | Read/obtain a DataFrame and call `process_pund(...)` |
| AMR measurement keyword `arduino` | Use `stepper`; the separate profile factory retains its own `arduino` parameter |
| AMR `voltage_callibration` | Use `voltage_calibration`, or explicit source/reader calibrations in a profile |
| AMR automatically reconfigures a manually set lock-in | Default is preserve; request explicit configure policy when intended |
| AMR can run without identifying excitation shutdown | Supply a truthful shutdown handler; name the owner for external excitation |
| Unit-bearing or uppercase result columns | Use canonical lowercase columns and `column_units_json` |
| A live display window contains the whole measurement | Use retained raw data or terminal data for the complete result |
| A returned result implies a saved CSV | Check successful publication and `filename`; partials have separate paths/status |
| A completed/failed worker automatically allows disconnection | Check worker termination and shutdown state through close coordination |
| Every virtual object uses a private material automatically | Install explicit hooks or create an owned bench/setup |
| Resetting one virtual instrument resets the entire simulated experiment | Reset the setup or bench and reconfigure instruments |

### Example of the standardized IV API

This is a virtual, in-memory example of the current API, with explicit source/load wiring:

```python
from piec.drivers.sourcemeter.virtual_sourcemeter import VirtualSourcemeter
from piec.measurement import IVSweep
from piec.simulation import ResistorLoad, VirtualBench

bench = VirtualBench(seed=7)
source = bench.add_instrument("source", VirtualSourcemeter)
bench.add_model("load", ResistorLoad, resistance=1000.0)
bench.connect_load("circuit", "source", "load")

measurement = IVSweep(
    source,
    v_start=0.0,
    v_stop=1.0,
    num_steps=11,
    current_compliance=0.01,
    dwell_time=0.0,
    ramp_delay=0.0,
)
data = measurement.run_experiment(save=False)
voltages = data["voltage"]
currents = data["current"]
record = measurement.last_run_record
```

To save, construct the measurement with `output_dir` and request `save=True`. To perform multiple interactive operations under one owner, use a session:

```python
with measurement.session(save=False) as session:
    session.configure_instruments()
    raw = session.capture_data()
# Exiting the session runs shutdown and finalization.
```

The examples illustrate API migration; they are not a physical wiring procedure or a substitute for the test results listed below.

## Validation evidence and merge review

### Evidence added by the branch

**Summary.** The branch adds 82 test/fixture files and substantially expands numerical, interface, lifecycle, fault, GUI, persistence, and simulation coverage. Test quantity alone does not establish physical readiness.

The compatibility manifest separates immutable reference observations from the desired current contract. Its baselines include master and an early MOKE feature commit because master has no MOKE implementation. Golden tables cover IV, calibrated/measured MOKE, discrete waveform, hysteresis, PUND, and AMR. Known incorrect AMR angle behavior is preserved as a labeled legacy observation, not promoted to a golden scientific result.

| Review area | Representative evidence |
|---|---|
| Commands and interfaces | AWG trigger commands; DMM overload/configuration; sourcemeter channel contracts; DAQ pulses |
| Scientific data | IV/MOKE, FE/PUND, and AMR compatibility suites and fixture manifest |
| Execution ownership | Lifecycle, engine, sessions, runner, stale-token, and ownership regressions |
| Fault handling | Acquisition/callback faults, shutdown failures, interrupted startup, and terminal snapshot regressions |
| Saving | Metadata round trips, no-replace collisions, reservations, bundle rollback, partial ownership, and staging recovery |
| GUI behavior | Connection ownership, start/stop/close, failed shutdown, recovery, and complete terminal plotting |
| Simulation | Seven virtual hook suites, role contracts, independent bench reset, and fixture migration |
| Consumer documentation | Executable developer-guide examples and offline virtual notebook checks |

### Recorded validation at the compared branch tip

The top checkpoint 33 entry in [MEASUREMENT_HANDOFF.md](../../MEASUREMENT_HANDOFF.md) records the following implementation verification:

| Check | Recorded result | Limit of the evidence |
|---|---|---|
| Full suite on Python 3.13 | 2,159 passed, 1 skipped in 63.30 seconds | Historical recorded run, not rerun for this document |
| Virtual notebook execution | Four notebooks and 36 code cells passed | Offline execution, not physical verification or certification of example fits |
| Offline Sphinx | `-W --keep-going -E` passed with zero warnings | Recorded documentation build |
| Wheel build | Successful; FE example parameter JSON included | Recorded build result |
| Python 3.9 | Not available in the recorded local environment | CI matrix coverage still needs its actual result checked |
| Remote CI | Not confirmed by that local record | Inspect the merge request jobs |
| Real SMB | Unverified; share test is opt-in | Mocked filesystem tests do not demonstrate deployed share behavior |

During this documentation pass, the commit relationship, file counts, affected implementations, API differences, and source links were checked. The application test suite was not rerun. The full-range `git diff --check master...HEAD` reports whitespace diagnostics, including trailing whitespace, committed carriage returns in `measurement/__init__.py`, and added blank lines at EOF. This differs from historical clean-diff statements that must not be used as a clean check of the whole compared range. These review documents do not modify those implementation files.

### Physical validation and excluded work

All three committed bench records remain pending: [IV and MOKE](../physical_validation_iv_moke.md), [FE](../physical_validation_fe.md), and [AMR](../physical_validation_amr.md). Completing these records requires the relevant instruments, setup checks, measured results, and operator sign-off. Virtual drivers, transport spies, and headless GUI tests do not supply that evidence.

Additional AMR resistance or voltage/current readout adapters, manual rotation workflows, and the optional later scientific additions are outside this branch's completed scope. Existing shared virtual fallbacks remain. Broad AWG model-limit certification, legacy DG1000 remote trigger launch, physical DAQ pulse timing, and full DAQ-to-scope integration should not be implied by the implemented API coverage.

### Recommended merge review

1. **Review driver prerequisites first.** Confirm command selection, channel conventions, unsupported operations, and the distinction between software trigger commands and physical synchronization.
2. **Review ownership and shutdown together.** Trace a normal run, stop-before-start, a failure after output activation, and a shutdown failure. Confirm original errors and retained data remain visible.
3. **Review persistence before consumer migration.** Check completed versus partial files, collision handling, recovery paths, and schema/unit metadata used by downstream readers.
4. **Review each scientific family.** Compare IV ramp sampling, MOKE complete-cycle averaging and field axes, FE/PUND alignment and units, and AMR final-angle/calibration corrections against the stated references.
5. **Review the GUIs with connection ownership in mind.** Check start, repeated runs, pause where supported, stop, close, failed startup, and failed shutdown without competing I/O.
6. **Confirm actual validation results.** Inspect Python 3.9/3.13 and documentation jobs, resolve the recorded whitespace findings as appropriate, and track the pending physical/SMB evidence separately from software test results.

### Reproducing the comparison

These read-only Git commands reconstruct the reviewed scope from the pinned commits even after branch names move:

```text
git rev-list --left-right --count 9d9760242f44a79401626964f0122cc91b149c18...99a8d697901468e7f7c7db275994fb1fab7a3984
git diff --stat 9d9760242f44a79401626964f0122cc91b149c18...99a8d697901468e7f7c7db275994fb1fab7a3984
git diff --name-status 9d9760242f44a79401626964f0122cc91b149c18...99a8d697901468e7f7c7db275994fb1fab7a3984
git diff --check 9d9760242f44a79401626964f0122cc91b149c18...99a8d697901468e7f7c7db275994fb1fab7a3984
```

The commands intentionally describe the implementation snapshot reviewed here; later commits and these comparison documents are not included in its totals.
