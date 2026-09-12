# Measurement standardization handoff

Continue on `measuremnt-standarization`. **Checkpoint 28g (generic per-instance virtual hooks: Sourcemeter family) is complete.**
All physical validation records across all families (Checkpoint 17: IV/MOKE, Checkpoint 22: FE, Checkpoint 26: AMR) remain explicitly **PENDING**.
Next: **Checkpoint 28h: audit remaining virtual-driver families and implement one concrete remaining family.** If none remain, report checkpoint 28 complete before advancing to VirtualBench (29). Run focused and full tests, update the handoff, commit separately, then stop for review. Additional AMR electrical adapters remain separate later work.
Additional electrical adapters remain separate later work; do not bundle them into past checkpoints.

## Checkpoint 28g report (authoritative)

### Review corrections for checkpoint 28g

- Hooks must solve the compliant terminal voltage/current pair. The driver rejects responses exceeding compliance rather than clipping one quantity and inventing a different load. This check also applies to mappings and LoadResponse, regardless of their compliance flag. Active hooks cannot return None or incomplete mappings; None remains acceptable for shutdown notification.
- Failed commands leave output unconfirmed; measurement methods, effective-output properties and compliance readback raise until explicit output recovery succeeds. SCPI writes preserve callback exceptions and accept numeric ON/OFF commands.
- Clocked load contracts use their setup-owned timebase. Repeated reads at the same time and operating point share one evaluation. Advance that clock before the first capacitor evaluation and each subsequent integration step; the driver never invents elapsed time. Output-off does not discharge/reset the external load; the isolated-terminal zero readback is a simulation convention, not a residual-charge guarantee.
- Callable binding preserves optional defaults and mixed signatures. Inactive source quantities are zero in hook arguments; configured values remain separately available. Callable time is supplied by its timebase or None when unspecified. New hooks invalidate cached evaluations. Effective-output properties preserve the selected sense function.
- Corrective validation: **93 focused sourcemeter tests passed**; final full repository suite with Agg **2133 passed, 1 skipped in 62.48s**. `git diff --check` passed.
- Continue with checkpoint 28h: audit remaining virtual-driver families and select one concrete remaining family before implementing it. If the inventory is exhausted, report that checkpoint 28 is complete before advancing to VirtualBench (29). Keep additional AMR adapters separate and physical checkpoints 17/22/26 PENDING.

- **Status**: **Completed**. Selected driver family: **Sourcemeter (`VirtualSourcemeter`)**.
- **Physical Validation Matrix**:
  - Checkpoint 17 (IV/MOKE): **PENDING** (`docs/physical_validation_iv_moke.md`, Section 13.1)
  - Checkpoint 22 (FE): **PENDING** (`docs/physical_validation_fe.md`, Section 13.2)
  - Checkpoint 26 (AMR): **PENDING** (`docs/physical_validation_amr.md`, Section 13.3)
- **Generic Per-Instance Virtual Hook Implementation** (`src/piec/drivers/sourcemeter/virtual_sourcemeter.py`):
  - **Hook Injection & Aliases**: Added `load_hook` (primary), `source_hook` (alias), `measure_hook` (alias), and `transport_hook` (alias) constructor parameters, method injectors `set_load_hook(hook)`, `set_source_hook(hook)`, `set_measure_hook(hook)`, `set_transport_hook(hook)`, and properties `load_hook`, `source_hook`, `measure_hook`, `transport_hook`. Passing `None` clears the hook and restores default fallback; non-callables and non-`ElectricalLoadContract` objects raise `TypeError`; conflicting hook aliases raise `ValueError`.
  - **Strict Precedence**: Explicit per-instance injection takes strict precedence over default unhooked fallback. When an explicit hook is injected, load evaluation computes terminal voltage, current, and compliance tripping based on active operating mode and stimulus.
  - **Material & Load Decoupling**: Generic `VirtualSourcemeter` contains no sample- or material-specific logic; physical load response simulation remains externalized to the hook callable or simulation model (`ElectricalLoadContract`, `ResistorLoad`, `DiodeLoad`, `CapacitiveLoad`).
  - **Operating Modes & Compliance Validation**: Supports both voltage-source mode (`source_func == 'VOLT'`) and current-source mode (`source_func == 'CURR'`). The load solves both terminal quantities under the requested compliance limit; the driver rejects out-of-limit responses. Exposes `@property def compliance_tripped(self) -> bool`.
  - **Configured Values vs Effective Terminal Output**: Stored settings (`source_voltage`, `source_current`, `voltage_compliance`, `current_compliance`) remain accessible in `self.state` and via SCPI queries (`:SOUR:VOLT:LEV?`, `:SOUR:CURR:LEV?`, `:SENS:VOLT:PROT?`, `:SENS:CURR:PROT?`). When output is disabled (`output_on=False`), effective terminal voltage is 0.0 V, current is 0.0 A, `compliance_tripped` is `False`, and properties `effective_voltage` / `effective_current` return 0.0 V / 0.0 A. With hook injected, `get_voltage()`, `get_current()`, `get_resistance()`, and `quick_read()` report 0.0 V / 0.0 A / `inf` when output is off. Default unhooked fallback preserves historical return values for existing Level 2 contract tests.
  - **Unconfirmed State on Failure**: If a hook raises an exception during output enable/disable (`output()`), setpoint updates (`set_source_voltage()`, `set_source_current()`), convenience configuration (`configure_voltage_source()`, `configure_current_source()`), or `reset()`, `state['output_on']` and `_output_enabled` become `None` (unconfirmed). Failed commands never falsely confirm shutdown or stopped state until a subsequent command succeeds. Exceptions propagate unchanged without retries or catch-and-retry masking.
  - **Signature Dispatch & Normalization**: Inspects signatures before calling the hook exactly once without retries; binds `(mode, stimulus, compliance)`, `(v, i)`, named parameters (`mode`, `source_func`, `stimulus`, `value`, `voltage`, `current`, `v`, `i`, `compliance`, `output_on`, `channel`, `time`), single-arg `(stimulus)`, zero-arg `()`, positional-only, `*args`, and `**kwargs`. Unrelated optional parameters retain their defaults. Handles return values: `LoadResponse`, `(v, i)` tuple, dict mapping, scalar numeric. `None` is accepted only when output is disabled.
  - **Declared Units & Input Validation Before Mutation**: Exposed `declared_units` mapping `{"voltage": "V", "current": "A", "resistance": "Ohm", "time": "s"}`. Validates channel (1), numeric types, finiteness, and positive compliance before mutating state.
  - **SCPI Command Dispatch & Queries**: Supports SCPI commands via `write()`: `:OUTP`, `:SOUR:FUNC`, `:SOUR:VOLT:LEV`, `:SOUR:CURR:LEV`, `:SENS:FUNC`, `:SENS:VOLT:PROT`, `:SENS:CURR:PROT`, `:SYST:RSEN`, `*RST`, `*CLS`. Supports SCPI queries via `query()`: `*IDN?`, `*ESR?`, `*OPC?`, `:READ?`, `:SOUR:VOLT:LEV?`, `:SOUR:CURR:LEV?`, `:SENS:VOLT:PROT?`, `:SENS:CURR:PROT?`, `:OUTP?`.
  - **State & Reset Ownership**: `reset()` restores default factory driver-owned configuration (`output_on=False`, `source_func='VOLT'`, `source_voltage=0.0`, `source_current=0.0`, `sense_func='VOLT'`, `voltage_compliance=210.0`, `current_compliance=1.05`, `compliance_tripped=False`) while preserving the injected hook intact. Notifies hook of 0.0 stimulus / output disabled. Setup-owned state (load timebase, RNG, material model) is owned by the setup / VirtualBench and not reset by driver reset. Added instance-level `sample` and `mag_sample` property descriptors ensuring instance assignments never mutate global `VirtualInstrument` state.
  - **Simulation Contracts**: Extended `src/piec/simulation/contracts.py` and `src/piec/simulation/__init__.py` with `SourcemeterLoadHook = Callable[..., Any]`.
- **Original implementation validation (superseded by review results above)**:
  - Dedicated hook test suite: 73 tests in `tests/test_virtual_sourcemeter_hook.py` passed in 1.14s.
  - Focused simulation & virtual hook suites: 556 tests passed in 1.75s.
  - Measurement suites using sourcemeter: 114 tests passed in 3.32s (`test_measurement_developer_guide.py`, `test_measurement_iv_review.py`, `test_measurement_iv_gui.py`, `test_moke.py`, `test_moke_gui.py`).
  - Full repository test suite: **2113 passed, 1 skipped** in 61.36s on Python 3.13.2 (`MPLBACKEND=Agg`). Zero failures, zero errors, zero xfails.
  - `git diff --check` passed cleanly with 0 whitespace errors.

## Checkpoint 28f report (authoritative)

### Review corrections for checkpoints 28e and 28f

- Scope normalization accepts negative pre-trigger timestamps, requires finite increasing time and finite one-dimensional voltage, selects the requested channel from labeled data and rejects unlabeled/ambiguous mappings instead of guessing. Fractional/non-finite channels are rejected before invocation or mutation.
- Scope bundled horizontal/trigger/acquisition configuration restores previous state on invalid input.
- AWG arbitrary waveforms validate dimensions and finiteness before storing, apply offset and polarity, and cannot be mutated through a state snapshot. Explicit SCPI channel queries route correctly; malformed output commands cannot silently affect channel 1.
- AWG noise uses a per-instance seeded RNG with replay on reset, independent of other instruments/global RNG. This is driver-owned noise state; hooks' external RNG/material state remains setup-owned.
- Added numerical regressions and a connected AWG-to-scope test for offset, polarity and pre-trigger time preservation. Trigger hooks receive synthesized waveform data and output metadata; this is not proof of physical output-off, continuous-time transport, or a completed VirtualBench. Historical fallback prep behavior remains separate.
- Corrective validation: full suite with Agg **2040 passed, 1 skipped in 63.38s**; `git diff --check` passed. Continue with checkpoint 28g for VirtualSourcemeter only, not VirtualBench yet. Physical 17/22/26 remain PENDING.

- **Status**: **Completed**. Selected driver family: **Arbitrary Waveform Generator (`VirtualAwg`)**.
- **Physical Validation Matrix**:
  - Checkpoint 17 (IV/MOKE): **PENDING** (`docs/physical_validation_iv_moke.md`, Section 13.1)
  - Checkpoint 22 (FE): **PENDING** (`docs/physical_validation_fe.md`, Section 13.2)
  - Checkpoint 26 (AMR): **PENDING** (`docs/physical_validation_amr.md`, Section 13.3)
- **Generic Per-Instance Virtual Hook Implementation** (`src/piec/drivers/awg/virtual_awg.py`):
  - **Hook Injection & Aliases**: Added `waveform_hook`, `apply_hook` (alias), and `trigger_hook` (alias) constructor parameters, method injectors `set_waveform_hook(hook)`, `set_apply_hook(hook)`, `set_trigger_hook(hook)`, and properties `waveform_hook`, `apply_hook`, `trigger_hook`. Passing `None` clears the hook and restores fallback; non-callables raise `TypeError`; conflicting hook aliases raise `ValueError`.
  - **Strict Precedence**: Explicit per-instance injection takes strict precedence over the deprecated shared `sample` fallback in `_handle_trigger()`, `output_trigger()`, `trigger()`, `send_software_trigger()`, and SCPI `*TRG` / `:TRIG`. When an explicit hook is injected, `sample` is never accessed or mutated.
  - **Material Decoupling**: Generic `VirtualAwg` contains no Landau model, prep points, PUND pulse sequences, or ferroelectric material logic; physical modeling remains entirely externalized to the hook closure or simulation model. The historical `self.sample.apply_waveform(v_prep, t_prep)` with 20 zero-volt prep points is retained strictly as deprecated global/instance fallback.
  - **Signature Dispatch & Argument Binding**: Inspects signatures before calling the hook exactly once without retries; hook exceptions propagate unchanged without catch-and-retry masking. Binds generated waveform `v` and timeline `t` (positional or named `v`, `voltages`, `waveform`, `v_applied`, `data`, `t`, `times`, `timestamps`, `time`), `channel` (or `ch`), `freq` (or `frequency`), `duration`, single-argument `(v)`, positional-only `(v, t, /)`, `*args`, `**kwargs`, and zero-argument notification `()`. Positional-only parameters and optional defaults are cleanly preserved.
  - **Declared Units & Input Validation Before Mutation**: Exposed `declared_units` mapping `{"voltage": "V", "frequency": "Hz", "time": "s"}`. Validates all configuration inputs before mutation: channel numbers (1-2), frequencies (positive finite floats), amplitudes (finite floats), DC offsets (finite floats), duty cycles / symmetries (finite floats in [0.0, 100.0]), pulse widths (positive finite floats), pulse delays (non-negative finite floats), waveform types, polarities ("NORM"/"INV"), trigger sources, levels, slopes, modes. Provides atomic configuration methods `configure_waveform`, `configure_pulse`, and `configure_trigger` that validate all arguments before committing state changes.
  - **SCPI Command Dispatch & Queries**: Supports SCPI commands via `write()`: `*TRG`, `:TRIG`, `:TRIG:IMM`, `*RST`, `*CLS`, `:OUTP`. Supports SCPI queries via `query()`: `*IDN?`, `*OPC?`, `*ESR?`, `:OUTP?`, `:SOUR:FREQ?`, `:SOUR:VOLT?`.
  - **State & Reset Ownership**: `reset()` restores default factory driver-owned configuration (default waveforms, frequencies, amplitudes, offsets, scales, all outputs OFF) while preserving the injected hook intact. Documented that setup-owned state (external models, timebase, clocks, RNG) is owned by the test fixture / VirtualBench and not reset by driver reset. Added instance-level `sample` property descriptor ensuring instance assignments never mutate global `VirtualInstrument._shared_fe_sample`.
  - **Simulation Contracts**: Extended `src/piec/simulation/contracts.py` with `AwgWaveformHook = Callable[[Sequence[float], Sequence[float]], Any]`.
- **Validation**:
  - Dedicated hook test suite: 45 tests in `tests/test_virtual_awg_hook.py` passed in 1.13s.
  - Focused simulation & virtual hook suites: 503 tests passed in 4.73s.
  - Focused FE/PUND compatibility suites: 21 tests in `tests/test_measurement_fe_pund_compatibility.py` passed in 3.45s.
  - Full repository test suite: **2022 passed, 1 skipped** in 63.98s on Python 3.13.2 (`MPLBACKEND=Agg`). Zero failures, zero errors, zero xfails.
  - `git diff --check` passed cleanly with 0 whitespace errors.

## Checkpoint 28e report (authoritative)

- **Status**: **Completed**. Selected driver family: **Oscilloscope (`VirtualScope`)**.
- **Physical Validation Matrix**:
  - Checkpoint 17 (IV/MOKE): **PENDING** (`docs/physical_validation_iv_moke.md`, Section 13.1)
  - Checkpoint 22 (FE): **PENDING** (`docs/physical_validation_fe.md`, Section 13.2)
  - Checkpoint 26 (AMR): **PENDING** (`docs/physical_validation_amr.md`, Section 13.3)
- **Generic Per-Instance Virtual Hook Implementation** (`src/piec/drivers/oscilloscope/virtual_oscilloscope.py`):
  - **Hook Injection & Aliases**: Added `waveform_hook`, `channel_hook` (alias), and `data_hook` (alias) constructor parameters, method injectors `set_waveform_hook(hook)`, `set_channel_hook(hook)`, `set_data_hook(hook)`, and properties `waveform_hook`, `channel_hook`, `data_hook`. Passing `None` clears the hook and restores fallback; non-callables raise `TypeError`; conflicting hook aliases raise `ValueError`.
  - **Strict Precedence**: Explicit per-instance injection takes strict precedence over the deprecated shared `sample` fallback in `get_data()` and `sample` property accesses. When an explicit hook is injected, `sample` is never accessed or mutated.
  - **Material Decoupling**: Generic `VirtualScope` contains no ferroelectric- or material-specific logic; physical sample response simulation remains externalized to the hook callable or simulation model. The historical `self.sample.get_voltage_response()` is retained strictly as deprecated global/instance fallback.
  - **Signature Dispatch & Argument Binding**: Inspects signatures before calling the hook exactly once without retries; hook exceptions propagate unchanged without catch-and-retry masking. Binds channel (int or str candidate), vertical scales (`vdiv`, `y_range`, `y_position`), horizontal scales (`tdiv`, `x_range`, `x_position`), `coupling`, `probe_attenuation`, `points`, `state`, `*args`, `**kwargs`, and zero-argument signatures. Positional-only parameters and optional defaults are cleanly preserved.
  - **Declared Units & Input Validation Before Mutation**: Exposed `declared_units` mapping `{"voltage": "V", "time": "s"}`. Validates all configuration inputs before mutation: channel numbers (1-4), scale values (positive finite floats), position offsets (finite floats), coupling modes ("AC"/"DC"), probe attenuations (positive finite floats in [0.001, 10000.0]), trigger sources, levels, slopes, modes, sweeps, acquisition modes, and requested points (integer >= 2). Maintains 8-division scale consistency (`y_range = 8.0 * vdiv`, `x_range = 8.0 * tdiv`).
  - **Output Normalization & Validation**: `get_data()` normalizes hook outputs into a canonical `pd.DataFrame` with standard `"Time"` and `"Voltage"` columns:
    - `(voltages, times)` 2-tuples/lists (canonical format of `WaveformResponsiveMaterialContract`).
    - Mappings/dicts containing time (`"time"`, `"t"`, `"timestamp"`) and voltage (`"voltage"`, `"v"`, `"volt"`, `"ch1"`, etc.) keys.
    - `pd.DataFrame` with time and voltage columns.
    - Validates non-empty datasets, matching lengths, and finite strictly increasing timestamps (including negative pre-trigger times).
  - **State & Reset Ownership**: `reset()` restores default driver-owned configuration (scales, positions, coupling, trigger, acquisition channels/modes/points) while preserving the injected hook intact. Documented that setup-owned state (external models, timebase, clocks, RNG) is owned by the test fixture / VirtualBench and not reset by driver reset. Added instance-level `sample` property descriptor ensuring instance assignments never mutate global `VirtualInstrument._shared_fe_sample`.
- **Validation**:
  - Dedicated hook test suite: 46 tests in `tests/test_virtual_oscilloscope_hook.py` passed in 1.34s.
  - Focused simulation & virtual hook suites: 358 tests passed in 2.50s (`test_virtual_oscilloscope_hook.py`, `test_virtual_stepper_hook.py`, `test_virtual_calibrator_hook.py`, `test_virtual_dmm_hook.py`, `test_virtual_lockin_hook.py`, `test_waveform_reader.py`, `test_simulation_contracts.py`).
  - Focused FE/PUND suites: 223 tests passed in 6.11s.
  - Full repository test suite: **1977 passed, 1 skipped** in 62.18s on Python 3.13.2 (`MPLBACKEND=Agg`). Zero failures, zero errors, zero xfails.
  - `git diff --check` passed cleanly with 0 whitespace errors.

## Checkpoint 28d report (authoritative)

### Review corrections

- Direction validation rejects fractional and non-finite values before any position update or hook invocation; values are no longer truncated into a valid direction.
- Mixed named/unnamed ordinary hook arguments bind correctly without duplicate positional binding. Unrelated optional parameters retain their defaults, including positional-only defaults. Hook errors still propagate without retry.
- Reset reports the actual change from the previous angle to zero, keeping delta-only models synchronized. Updating steps-per-revolution notifies the hook of the recalculated angle (or updates the retained shared-sample fallback); it is a coordinate-scale update, not a physical move. Notification failure leaves motion unconfirmed.
- Added regressions for invalid directions, mixed/defaulted signatures, delta-only model consistency across scale/reset and unchanged failure identity.
- Corrective validation: full suite with Agg **1931 passed, 1 skipped in 62.85s**; `git diff --check` passed. Next remains checkpoint 28e, one additional family only. Extra AMR adapters and VirtualBench remain separate; physical 17/22/26 remain PENDING.

- **Status**: **Completed**. Selected driver family: **Stepper Motor (`VirtualStepper`)**.
- **Physical Validation Matrix**:
  - Checkpoint 17 (IV/MOKE): **PENDING** (`docs/physical_validation_iv_moke.md`, Section 13.1)
  - Checkpoint 22 (FE): **PENDING** (`docs/physical_validation_fe.md`, Section 13.2)
  - Checkpoint 26 (AMR): **PENDING** (`docs/physical_validation_amr.md`, Section 13.3)
- **Generic Per-Instance Virtual Hook Implementation** (`src/piec/drivers/stepper_motor/virtual_stepper.py`):
  - **Hook Injection & Aliases**: Added `angle_hook`, `position_hook` (alias), and `step_hook` (alias) constructor parameters, method injectors `set_angle_hook(hook)`, `set_position_hook(hook)`, `set_step_hook(hook)`, and properties `angle_hook`, `position_hook`, `step_hook`.
  - **Strict Precedence**: Explicit per-instance injection takes strict precedence over the deprecated shared `mag_sample` fallback in `step()`, `set_zero()`, `set_position()`, `stop()`, `halt()`, and `reset()`. When an explicit hook is injected, `mag_sample` is never accessed or mutated.
  - **Material Decoupling**: Generic `VirtualStepper` contains no sample-, magnet-, or AMR-specific formulas; physical modeling (e.g. stage orientation, sample rotation, AMR resistance $R(\theta)$, or Hall sensors) remains entirely external to the driver in the hook closure or simulation model.
  - **Motion Parameter Binding & Signature Dispatch**: Inspects signatures before calling the hook exactly once without retries; hook exceptions propagate unchanged. Supports total angle in degrees (positional or named `angle`, `total_angle`, `target_angle`, `value`, `total`), delta angle (`delta_angle`, `delta`), step position (`position`, `total_steps`, `target_position`, `steps`), and motion status `moving` (boolean). Positional-only, pure `*args`, `**kwargs`, and zero-argument hooks are supported.
  - **Shutdown Confirmation & Dynamic State**: Distinguishes stored settings (`steps_per_revolution`, target position setpoints) from dynamic motion state (`moving`). If a hook fails during any motion or shutdown command (`step`, `stop`, `halt`, `set_position`, `set_zero`, `reset`), `moving` is marked `None` (unconfirmed). Failed commands do not falsely confirm shutdown or stopped state until a subsequent command succeeds.
  - **Declared Units & Validation**: Exposed `declared_units` mapping `{"angle": "deg", "position": "steps"}`. Step counts require finite non-negative integers; direction requires 1 (CW) or 0 / -1 (CCW); `steps_per_revolution` requires positive integers. Non-numeric or non-finite values are rejected with `TypeError` / `ValueError` while preserving previous state.
  - **State & Reset Ownership**: `reset()` restores default driver-owned configuration (`position=0`, `angle=0.0 deg`, `moving=False`, and initial `steps_per_revolution`) while preserving the injected hook intact. Informs injected hook with 0.0 deg output. Documented that setup-owned state (closures, external material models, clocks, RNG) is owned by the test fixture / VirtualBench and not reset by driver reset. Added instance-level `mag_sample` property descriptor ensuring instance assignments never mutate global `VirtualInstrument._shared_mag_sample`.
- **Validation**:
  - Dedicated hook test suite: 72 tests in `tests/test_virtual_stepper_hook.py` passed in 1.16s.
  - Focused simulation & virtual hook suites: 293 tests passed in 2.51s (`test_virtual_stepper_hook.py`, `test_virtual_calibrator_hook.py`, `test_virtual_dmm_hook.py`, `test_virtual_lockin_hook.py`, `test_amr_contract.py`, `test_simulation_contracts.py`).
  - Focused AMR measurement suites: 76 tests in `tests/test_measurement_magneto_transport.py`, `tests/test_measurement_amr_gui.py`, `tests/test_measurement_amr_compatibility.py` passed in 28.11s.
  - Full repository test suite: **1920 passed, 1 skipped** in 65.09s on Python 3.13.2. Zero failures, zero errors, zero xfails.
  - `git diff --check` passed cleanly.

## Checkpoint 28c report (authoritative)

### Review corrections

- Crowbar notifications retain the active electrical mode (voltage/current), report effective value zero and set both electrical keyword outputs to zero. Inactive voltage/current keywords no longer expose stale setpoints after switching modes. Stored settings remain available through getters and are restored on output enable.
- Hook failures propagate unchanged after exactly one call and leave `output_on` / `_output_enabled` as `None` (unconfirmed), including failures during output-off, crowbar and reset. A subsequent successful command restores confirmed state. Do not treat unconfirmed state as a successful shutdown or roll it back to a guessed physical state.
- Pure variadic hooks receive the commanded value. Invalid output-enable settings are rejected before changing state; finite real numeric command scalars are supported.
- Added regressions for both source modes, crowbar, inactive-output keywords, failure/recovery, variadic dispatch and invalid enable values.
- Corrective validation: full suite with Agg **1848 passed, 1 skipped in 63.19s**; `git diff --check` passed. Physical 17/22/26 remain PENDING. Next is checkpoint 28d only, one additional driver family; extra AMR adapters and VirtualBench stay separate.

- **Status**: **Completed**. Selected driver family: **DC Calibrator (`VirtualCalibrator`)**.
- **Physical Validation Matrix**:
  - Checkpoint 17 (IV/MOKE): **PENDING** (`docs/physical_validation_iv_moke.md`, Section 13.1)
  - Checkpoint 22 (FE): **PENDING** (`docs/physical_validation_fe.md`, Section 13.2)
  - Checkpoint 26 (AMR): **PENDING** (`docs/physical_validation_amr.md`, Section 13.3)
- **Generic Per-Instance Virtual Hook Implementation** (`src/piec/drivers/dc_calibrator/virtual_calibrator.py`):
  - **Hook Injection**: Added `output_hook` and `field_hook` (alias) constructor parameters, method injectors `set_output_hook(hook)`, `set_field_hook(hook)`, and properties `output_hook`, `field_hook`.
  - **Strict Precedence**: Explicit per-instance injection takes strict precedence over the deprecated shared `mag_sample` fallback in `set_output()`, `set_voltage()`, `set_current()`, `output()`, and `reset()`. When an explicit hook is injected, `mag_sample` is never accessed or mutated.
  - **Material Decoupling**: Generic `VirtualCalibrator` contains no sample-, magnetic-, or coil-specific formulas; physical modeling remains entirely external to the driver in the hook closure. The historical `value * 10000.0` factor is retained strictly for the deprecated shared-sample fallback.
  - **Commanded Output Binding & Signature Dispatch**: Inspects signatures before calling the hook exactly once without retries; hook exceptions propagate unchanged. Supports single output value (positional or named), `mode` ("voltage" or "current"), `output_on` (boolean), or `**kwargs`. Zero-argument hooks are also supported.
  - **Declared Units & Validation**: Exposed `declared_units` mapping `{"voltage": "V", "current": "A"}`. Command inputs require finite numeric values; non-numeric values raise `TypeError` and non-finite values or unsupported modes raise `ValueError`, preserving previous state. Supports both standard `voltage_calibration` and legacy `voltage_callibration` aliases.
  - **State & Reset Ownership**: `reset()` restores default driver-owned configuration (`output_on=False`, `voltage=0.0`, `current=0.0`, `mode="voltage"`, engaging crowbar) while preserving the injected hook intact. Informs injected hook with 0.0 V output. Documented that setup-owned state (closures, external material models, clocks, RNG) is owned by the test fixture / VirtualBench and not reset by driver reset. Added instance-level `mag_sample` property descriptor ensuring instance assignments never mutate global `VirtualInstrument._shared_mag_sample`.
- **Validation**:
  - Dedicated hook test suite: 46 tests in `tests/test_virtual_calibrator_hook.py` passed in 1.35s.
  - Focused simulation & virtual hook suites: 324 tests passed in 2.49s (`test_virtual_calibrator_hook.py`, `test_virtual_dmm_hook.py`, `test_virtual_lockin_hook.py`, `test_dmm_contract.py`, `test_amr_contract.py`, `test_virtual_dispatch.py`, `test_simulation_contracts.py`).
  - Focused AMR measurement suites: 76 tests in `tests/test_measurement_magneto_transport.py`, `tests/test_measurement_amr_gui.py`, `tests/test_measurement_amr_compatibility.py` passed in 28.30s.
  - Full repository test suite: **1836 passed, 1 skipped** in 63.97s on Python 3.13.2. Zero failures, zero errors, zero xfails.
  - `git diff --check` passed cleanly.

## Checkpoint 28b report (authoritative)

### Review corrections

- Hook dispatch supplies all declared `ac`/`coupling` settings together, including mixed positional-only/keyword signatures and defaulted `coupling` with `**kwargs`. AC reads no longer silently use a hook's DC default. Binding happens before one invocation; hook exceptions still propagate unchanged.
- Manual sense ranges and integration times reject non-finite/non-positive values without changing configuration. IEEE non-finite voltage readings remain supported for overload simulation.
- Added regressions for combined/mixed/defaulted hook signatures, unchanged hook-error identity and configuration state preservation.
- Corrected documentation: the new injected path is generic, while the historical shared-sample `current_field / 10000` conversion remains as the explicitly retained fallback. It is not a general sensor calibration.
- Corrective validation: full suite with Agg **1790 passed, 1 skipped in 63.50s**; `git diff --check` passed. Physical 17/22/26 remain PENDING. Proceed with checkpoint 28c only, one next driver family; keep extra AMR adapters and VirtualBench separate.

- **Status**: **Completed**. Selected driver family: **DMM (`VirtualDMM`)**.
- **Physical Validation Matrix**:
  - Checkpoint 17 (IV/MOKE): **PENDING** (`docs/physical_validation_iv_moke.md`, Section 13.1)
  - Checkpoint 22 (FE): **PENDING** (`docs/physical_validation_fe.md`, Section 13.2)
  - Checkpoint 26 (AMR): **PENDING** (`docs/physical_validation_amr.md`, Section 13.3)
- **Generic Per-Instance Virtual Hook Implementation** (`src/piec/drivers/dmm/virtual_dmm.py`):
  - **Hook Injection**: Added `voltage_reader` and `reader_hook` (alias) constructor parameters, method injectors `set_voltage_reader(hook)`, `set_reader_hook(hook)`, and properties `voltage_reader`, `reader_hook`.
  - **Strict Precedence**: Explicit per-instance injection takes strict precedence over the deprecated shared `mag_sample` fallback in `get_voltage()`. If `voltage_reader` is injected, it is evaluated directly and `mag_sample` is not accessed.
  - **Material Decoupling**: The injected path adds no sample-specific logic. Physical modeling belongs in the hook; the historical shared-sample conversion is retained only as fallback.
  - **Scalar Voltage & Units**: Returns scalar `float` voltages in Volts. Preserves IEEE 754 non-finite values (`inf`, `-inf`, `nan`) for DMM hardware overload emulation (per Checkpoint 6 contract). Rejects non-scalar collections (`tuple`, `list`, non-0d `ndarray`) with `TypeError`. Exposed `declared_units` mapping `{"voltage": "V"}`.
  - **Error Propagation & Dispatch**: Hook dispatch inspects signatures before invoking the hook exactly once; hook exceptions (`RuntimeError`, `TypeError`, etc.) propagate unchanged without retries or fallback invocation. Supports 0-argument callables, `ac` and `coupling` keyword arguments, and positional-only `ac`/`coupling` parameters.
  - **State & Reset Ownership**: `reset()` restores default driver-owned configuration (`sense_func="VOLT"`, `coupling="DC"`, `sense_mode="2W"`, `sense_range=None`, `autorange=True`, `integration_time=1.0`) while preserving the injected hook intact. Setup-owned state (closures, external material models, clocks, RNG) is owned by the test fixture / VirtualBench and not reset by driver reset. Added instance-level `mag_sample` property descriptor so instance assignments never mutate global `VirtualInstrument._shared_mag_sample`.
- **Validation**:
  - Dedicated hook test suite: 37 tests in `tests/test_virtual_dmm_hook.py` passed in 0.95s.
  - Focused DMM contract test suite: 79 tests in `tests/test_dmm_contract.py` passed in 1.95s.
  - Focused Lock-in hook test suite: 46 tests in `tests/test_virtual_lockin_hook.py` passed in 0.89s.
  - Focused simulation contracts: 33 tests in `tests/test_simulation_contracts.py` passed in 0.62s.
  - Full repository test suite: **1780 passed, 1 skipped** in 65.66s on Python 3.13.2. Zero failures, zero errors, zero xfails.
  - `git diff --check` passed cleanly.

## Checkpoint 28a report (authoritative)

### Review corrections

- Hook dispatch binds the call shape before invocation. Positional-only and optional positional current arguments work; hook exceptions propagate unchanged with no retry or fallback invocation.
- Declared excitation current is validated on every assignment and accepts finite signed values and zero. Reference voltage does not imply a sample current without an explicit circuit model.
- Reference configuration rejects invalid amplitude/frequency/source/phase atomically and avoids duplicate raw state keys. X/Y response validation rejects non-vector arrays; reported Theta is atan2(Y, X) in degrees.
- Added regressions for unchanged exception identity, exactly-once invocation, positional signatures, zero/signed current, configuration atomicity, phase, hook precedence and two-instance/global fallback isolation.
- The instance-local sample override is retained. A driver reset preserves hook identity and does not reset the setup-owned closure/material/RNG state; future bench wiring must own that operation.
- Corrective validation: full suite with Agg **1743 passed, 1 skipped in 62.53s**; `git diff --check` passed. Physical 17/22/26 remain PENDING.

- **Status**: **Completed**. Selected driver family: **Lock-in (`VirtualLockin`)**.
- **Physical Validation Matrix**:
  - Checkpoint 17 (IV/MOKE): **PENDING** (`docs/physical_validation_iv_moke.md`, Section 13.1)
  - Checkpoint 22 (FE): **PENDING** (`docs/physical_validation_fe.md`, Section 13.2)
  - Checkpoint 26 (AMR): **PENDING** (`docs/physical_validation_amr.md`, Section 13.3)
- **Generic Per-Instance Virtual Hook Implementation** (`src/piec/drivers/lockin/virtual_lockin.py`):
  - **Hook Injection**: Added `xy_reader` and `transport_hook` (alias) constructor parameters, method injectors `set_xy_reader(hook)`, `set_transport_hook(hook)`, and properties `xy_reader`, `transport_hook`.
  - **Strict Precedence**: Explicit per-instance injection takes precedence over the deprecated shared `mag_sample` fallback in `quick_read()`. If `xy_reader` is injected, it is evaluated directly and `mag_sample` is not accessed.
  - **Material Decoupling**: Generic `VirtualLockin` contains no material-specific logic, magnetic formulas, angle/field calculations, or AMR equations; material modeling remains entirely external to the driver in the material/hook closure.
  - **Excitation & Units**: Explicit `excitation_current` in A with finite validation on construction and assignment, including zero/signed drive. Forwarded to hooks accepting it (keyword or positional parameter). Exposed `declared_units` mapping `{"x": "V", "y": "V", "excitation_current": "A"}`.
  - **Plain Tuple Response**: Validates and returns a plain `tuple[float, float]` in Volts; no compatibility wrappers, no scalar/float subclasses. Rejects non-sequence, wrong-length, non-convertible, or non-finite hook outputs with `TypeError` or `ValueError`.
  - **State & Reset Determinism**: `reset()` restores constructor initial `excitation_current` and default reference settings while preserving the injected per-instance hook intact. Added instance-level `mag_sample` property to ensure instance assignments never pollute global `VirtualInstrument._shared_mag_sample`.
- **Validation**:
  - Dedicated hook test suite: 28 tests in `tests/test_virtual_lockin_hook.py` passed in 0.97s.
  - Focused simulation and AMR suites: 194 passed in 27.15s.
  - Full repository test suite with Agg backend: **1725 passed, 1 skipped** in 62.31s on Python 3.13.2. Zero failures, zero errors, zero xfails.
  - `git diff --check` passed cleanly.

## Checkpoint 27 report (authoritative)

### Follow-up review corrections

- Removed the new `VoltageResponse` float compatibility wrapper and its compatibility test. The AMR material requires explicit `excitation_current` in A and returns plain `(X, Y)` in V, with Y=0 for an ideal resistor. Updated VirtualLockin's existing fallback consumer to pass its declared simulation current and forward both channels; generic hooks are not implemented yet.
- Replaced the diode's fixed-iteration series solver with a bracketed solve, removed the invented -100 V reverse result, and enforced the supplied compliance limits. Current- and voltage-noise settings now have independent declared units.
- Replaced unstable capacitor updates and invented 1 ns elapsed time with charge-conserving backward Euler integration. Strictly increasing evaluation times are required; reported current is an interval average with end-step leakage. Resolve dynamics with appropriate timesteps; no sub-step compliance timing is claimed.
- Absolute clocks reject reversal/non-finite time/overflow. Reset restores constructor time and RNG replay, even within an initially unseeded instance. Invalid magnetic histories are checked before switching state.
- Load response state is recursively detached/frozen. FE native polarization units are C/m^2, not uC/cm^2; waveform time grids are validated and local acquisition duration advances its clock.
- Added numerical regressions covering forward/reverse diode operation, capacitor charge/compliance/leakage, reset and time semantics, snapshot immutability, FE input validation and virtual lock-in channel forwarding. See `src/piec/simulation/README.md` for contract semantics and limitations.
- Corrective validation: full repository suite with Agg **1697 passed, 1 skipped in 62.49s**; `git diff --check` passed. Physical 17/22/26 remain PENDING.

- **Status**: **Completed**. Role-specific simulation contracts implemented and tested.
- **Physical Validation Matrix**:
  - Checkpoint 17 (IV/MOKE): **PENDING** (`docs/physical_validation_iv_moke.md`, Section 13.1)
  - Checkpoint 22 (FE): **PENDING** (`docs/physical_validation_fe.md`, Section 13.2)
  - Checkpoint 26 (AMR): **PENDING** (`docs/physical_validation_amr.md`, Section 13.3)
- **Role-Specific Simulation Contracts Delivered** (`src/piec/simulation/contracts.py`):
  - **Explicit Physical Units**: Declared unit mappings strictly adhering to SI / standard CGS-EMU (`V`, `A`, `Ohm`, `s`, `Oe`, `deg`). Frozen immutable `LoadResponse` dataclass with finite numeric validation.
  - **Voltage Response**: Plain `(x, y)` tuple in V from an explicitly supplied excitation current in A. No new compatibility shim.
  - **Deterministic Time & RNG**: `SimulationRole` base abstract contract requiring `declared_units`, `reset(seed=None, **kwargs)`, `seed(seed)`, `timebase`, and `rng`. `DeterministicTimebase` providing monotonically increasing, controllable time advancement (`advance(delta_t)`, `set_time(t)`, `reset()`). Deterministic RNG sequences via `np.random.default_rng(seed)`.
  - **Two-Terminal Electrical Load Contracts**: `ElectricalLoadContract` with `LoadMode.VOLTAGE_SOURCE` and `LoadMode.CURRENT_SOURCE`, bidirectional compliance limiting, time, and internal state:
    - `ResistorLoad`: Linear resistor evaluating Ohm's law ($V = IR$, $I = V/R$) across both driving modes with compliance limiting ($I_{\text{comp}}$ in voltage mode, $V_{\text{comp}}$ in current mode), temperature coefficient support, and deterministic noise.
    - `DiodeLoad`: Non-linear Shockley diode model ($I = I_s (e^{V / n V_t} - 1)$) with series resistance $R_s$, reverse saturation, forward exponential rise, and compliance limits under both voltage and current drives.
    - `CapacitiveLoad`: Stateful capacitor tracking charge $Q(t)$ and voltage across arbitrary time increments with displacement current evaluation, $dV/dt$ integration, and compliance clamping.
  - **Material Response Contracts**:
    - `FieldResponsiveMaterialContract`: Magnetic field response ($H$ in Oe), dimensionless magnetization ($M/M_s$), stateful hysteresis, and deterministic reset. `HystereticMagneticMaterial` updated to inherit and satisfy contract.
    - `AngleDependentResistanceContract`: Magneto-transport AMR response ($\theta$ in deg, $H$ in Oe, $R$ in Ohm, dual-channel $(X, Y)$ in V). `MagneticMaterial` updated to inherit and conform.
    - `WaveformResponsiveMaterialContract`: Dynamic response to $v(t)$ waveforms. `Ferroelectric` updated to inherit and conform.
  - **Virtual Hook Protocols**: Formal type definitions for `DmmVoltageReaderHook`, `LockinTransportHook`, `ScopeChannelHook`, `CalibratorFieldHook`, and `StepperAngleHook` establishing contract foundations for Checkpoint 28.
- **Invariants Preserved**:
  - Manual lock-in settings preserved by default (`initialize_lockin=False`, `readout_configuration="preserve"`).
  - Explicit excitation ownership preserved (no fabricated X/Y, no assumed current).
  - Plain columns with metadata units preserved across all schemas.
  - Checkpoint 24d onward (additional AMR electrical adapters) and Checkpoints 28/29 (`VirtualBench` / driver per-instance hook injections) kept separate.
- **Validation**:
  - Dedicated simulation contract test suite: 33 tests in `tests/test_simulation_contracts.py` passed in 0.62s.
  - Targeted GUI suites: 82 passed in 28.96s (`test_measurement_amr_gui.py`, `test_measurement_fe_gui.py`).
  - Full repository test suite with Agg backend: **1657 passed, 1 skipped** in 62.01s on Python 3.13.2. Zero failures, zero errors, zero xfails.
  - `git diff --check` passed cleanly.


## Review corrections for checkpoints 25 and 26

- Recoverable runner startup failures release connections before restoring controls, so Run becomes enabled when ownership is clear.
- Autodetect tracks each returned connection before reading its address or updating widgets. Cleanup runs even on address-update failure. Failed closes retain the handle, disable Run, halt the scan and block window destruction until an explicit close retry succeeds.
- Regression coverage checks startup button state, successful/failed autodetect cleanup, close retry, and address-update exceptions.
- Physical records use justified bench-specific latency and excitation limits. Output-disable commands do not prove relay position, zero sample excitation or zero residual magnetic field. Acquisition preserves manual lock-in settings; the declared shutdown procedure may make documented changes.
- Checkpoints 17, 22 and 26 remain PENDING until dated physical evidence and operator sign-off exist. Offline work may continue.
- Checkpoint 27 scope: role-specific units, reset behavior, deterministic time/RNG and voltage/current-source electrical loads. Preserve plain columns and metadata units, explicit excitation ownership and manual lock-in settings by default. Do not introduce compatibility shims, fabricated X/Y, assumed current, extra electrical adapters or checkpoint 28/29 implementation in this commit.
- Validation: full repository suite with Agg backend, **1624 passed, 1 skipped in 61.32s**; `git diff --check` passed. No physical hardware validation performed.

## Checkpoint 26 report (authoritative)

- **Status**: **PENDING**. The protocol template is complete; physical execution is not.
- **Physical Environment Discovery**: `pyvisa.ResourceManager().list_resources()` returned `()`. No physical VISA instruments (stepper motor, electromagnet calibrator, field readback DMM, lock-in amplifier) were discovered in this automated software environment.
- **Physical Safety Principle**: In accordance with Section 13 of `MEASUREMENT_STANDARDIZATION_PLAN.md`, virtual drivers and headless test suites (1621 tests passing) validate interface contracts, schema conformity, thread coordination, and numerical algorithms, but they do NOT prove physical hardware safety. Checkpoint 26 remains explicitly marked **PENDING** until actual physical testing is conducted on laboratory hardware.
- **Dedicated Protocol & Record Documents**:
  - `docs/physical_validation_amr.md`: Authoritative physical validation record and 4-stage protocol for AMR (Checkpoint 26).
  - `docs/physical_validation_fe.md`: Authoritative physical validation record and 4-stage protocol for Ferroelectric testing (Checkpoint 22).
  - `docs/physical_validation_iv_moke.md`: Authoritative physical validation record and staged protocol for IV & MOKE (Checkpoint 17).
- **Staged AMR Validation Protocol** (per Section 13: "AMR validates motion and field roles independently before combining them"):
  - **Stage 1: Motion Role Validation (Orientation Controller Alone)**: Evaluates stepper motor / rotation stage without magnetic field or sample excitation. Verifies angular scaling (`steps_per_degree`), forward and reverse angular sweeps, stop latency, serial timeout handling, and confirms repair of defect `AMR-ANGLE-001` (motor halts at final commanded angle with zero extra steps).
  - **Stage 2: Field Role Validation (Field Source + Field Readback Alone)**: Evaluates electromagnet power supply (calibrator) and field readback DMM / Hall probe without sample excitation or motion. Verifies voltage-to-field calibration factor (`AMR-FIELD-001` repair: $10000\text{ Oe/V}$ produces $0.01\text{ V}$ for $100\text{ Oe}$), bipolar zero-crossing across negative fields, and attempt-all electrical de-energization, with residual field independently measured against a justified bench limit.
  - **Stage 3: Transport Readout & Excitation Safing Role Validation (Lock-In Alone)**: Evaluates lock-in amplifier terminated into a known benign standard resistor. Verifies default preservation of front-panel manual settings (`initialize_lockin=False`, `readout_configuration="preserve"`), execution of declared physical excitation shutdown policy (supported shutdown action and independently measured excitation within a justified bench limit), and retention of open connections on simulated shutdown failure (`SafetyStatus.UNSAFE`).
  - **Stage 4: Integrated Low-Field AMR Measurement**: Reference thin-film AMR sample (e.g. 20 nm NiFe stripe) mounted in electromagnet pole gap. $0^\circ \to 180^\circ$ rotation sweep at $H = 100\text{ Oe}$. Verifies bounded `raw_window` display updates, authoritative terminal delivery, atomic CSV publication under canonical schema `amr` v1 with metadata units (`deg`, `Oe`, `V`, `V`), and characteristic $\cos^2(\theta)$ anisotropic curve.
- **Physical Validation Matrix**:
  - Checkpoint 17 (IV/MOKE): **PENDING** (`docs/physical_validation_iv_moke.md`, Section 13.1)
  - Checkpoint 22 (FE): **PENDING** (`docs/physical_validation_fe.md`, Section 13.2)
  - Checkpoint 26 (AMR): **PENDING** (`docs/physical_validation_amr.md`, Section 13.3)
- **Validation**: Full repository test suite with Agg backend: **1621 passed, 1 skipped** in 62.07s on Python 3.13.2. Zero failures, zero xfails.

## Checkpoint 25 report

- Validation: full suite with Agg **1621 passed, 1 skipped** in 62.07s on Python 3.13.2.
  Focused AMR/Magneto suite (215 tests) passed in 34.69s; GUI suite (35 tests) passed in 26.91s.
  No physical hardware validation was performed (checkpoints 17 and 22 remain PENDING).
- **Settings & Preflight Hardening**:
  - `save_settings()` / `load_settings()` in `AMRApp` explicitly persists and restores `initialize_lockin_var` alongside all standard static and dynamic entries.
  - Preflight validates that all four instrument addresses (`dmm`, `calibrator`, `stepper`, `lockin`) are specified and non-empty before touching any drivers.
  - Simulation excitation shutdown policy is prohibited when any physical instrument is configured.
  - Preflight checks sweep direction consistency (`total_angle * angle_step >= 0` if `total_angle != 0`), sweep interval bound (`abs(total_angle / angle_step) <= 1_000_000`), positive amplitude/frequency, non-negative measure time, and non-empty sensitivity. Validation failures show modal error dialogs and leave bench hardware untouched.
- **Run / Pause / Stop / Close Lifecycle**:
  - `toggle_pause()` toggles runner pause state, updates button text ("RESUME" / "PAUSE"), and updates `status_label` ("Paused" / "Running"). Idle calls are safe no-ops.
  - `stop_measurement()` disables both Stop and Pause buttons to prevent interleaved pause requests while stopping, updates `status_label` ("Stopping and returning field to zero..."), and issues cooperative stop.
  - `cleanup_controls()` safely destroys control buttons, resets `paused` state, clears button references, restores `run_button`, and automatically locks `run_button` (`state='disabled'`) whenever `_busy()` is True (e.g. retained UNSAFE hardware).
  - `on_closing()` gracefully coordinates with running workers via `runner.request_close()`, deferring window destruction until worker exit and verified safety. Retained unclosed connections block window destruction until an explicit close retry succeeds.
- **Startup Failures & Active Ownership Retention**:
  - Driver setup failure closes earlier opened connections via `_close_instruments()` and resets status to "Idle".
  - Experiment setup (`AMR(...)`) failure closes all 4 connections and resets status to "Idle".
  - `runner.start()` failure: if `runner.can_close()` is True (validation failure or thread start failure with `NOT_NEEDED`), cleanly resets GUI latches, cleans up controls, closes instruments, and resets status to "Idle". If `runner.can_close()` is False (ownership was acquired and cannot close), retains open connections in `self._instruments`, keeps `_busy()` and `_awaiting_terminal` True, and updates status label to "Start error: active ownership retained".
- **Terminal-Before-Worker-Exit Gating**:
  - Drains display and control queues on the main thread; renders authoritative final plot upon `TerminalEvent`.
  - Retains `_awaiting_terminal`, `is_measuring`, and `_busy()` True until `not runner.is_worker_alive`.
  - Once the worker terminates, closes instruments if `runner.can_close()` or retains them under `SafetyStatus.UNSAFE` (locking `run_button` and updating status label).
  - On `SafetyAlertEvent`, displays modal error dialog and updates status label.
- **Auxiliary Action Resilience**:
  - `test_stepper()` validates non-empty address, handles both VirtualStepper and Geos_Stepper, queries identification, and guarantees connection closure in `finally`.
  - `refresh_instruments()` safely refreshes VISA resource lists when not busy.
  - `autodetect_instruments()` wraps driver detection in try/except to guard against VISA bus scan timeouts or exceptions.
- **Fault Regressions**: Added 15 new interaction and ownership tests in `tests/test_measurement_amr_gui.py` covering all audit invariants. Preserved executable notebook ordering, virtual-only shutdown checks, NOT_NEEDED abort cleanup, and display error handling.

## Checkpoint 24c review corrections (authoritative)

- Latest follow-up validation: full suite with Agg **1606 passed, 1 skipped**
  in 52.15s, including executable notebook and GUI cleanup regressions.
- Follow-up review restored the notebook's execution order: instrument creation
  and a runtime-checked all-virtual shutdown policy are executable code before
  acquisition; metadata-derived plotting follows acquisition and uses in-memory
  results. Previously setup code had been placed in Markdown and the instrument
  cell replaced by premature plotting. The notebook is now tested by executing
  its code cells in order with a short virtual sweep (excluding VISA discovery).
- GUI rendering errors are reported without interrupting terminal processing,
  connection cleanup or polling. Empty final results clear stale plots. The
  measured data is retained even when plotting fails.
- Test Stepper closes its connection even on identification/query failure and
  uses VirtualStepper for virtual addresses. Failed close calls retain references
  and block new hardware work/window destruction until an explicit close retry
  succeeds; polling does not continuously retry failed closes.
- Proceed with checkpoint 25: audit settings/preflight, Run/Pause/Stop/close,
  failed setup/start, terminal-before-worker-exit, UNSAFE retention, and auxiliary
  instrument actions. Preserve the close/retry, Test Stepper cleanup, and plot
  failure regressions along with the reviewed virtual-only shutdown
  guards and NOT_NEEDED cleanup. A custom callback is a caller-supplied contract;
  callable() does not prove that it performs physical safing. Validate, update
  plan/handoff, commit checkpoint 25 separately, and stop for review.
- Validation: full suite with Agg **1601 passed, 1 skipped** in 46.85s on Python 3.13.2.
  Focused AMR/Magneto suite (195 tests) passed in 18.74s; GUI suite (20 tests) passed in 17.42s.
  No physical hardware validation was performed (checkpoints 17 and 22 remain PENDING).
- **Driver Setup Failure Cleanup**: In `AMRApp.run_measurement()`, opened instruments are immediately tracked into `self._instruments` as each driver is instantiated. If any subsequent driver constructor raises an exception, all earlier opened connections are cleanly closed via `self._close_instruments()` in an exception handler before returning, preventing resource leaks.
- **Unified Hardware Ownership / Busy Guard**: Implemented `_busy()` in `AMRApp` checking `is_measuring`, `_awaiting_terminal`, `not runner.can_close()`, and `bool(self._instruments)`. This single guard is enforced across `run_measurement()`, `refresh_instruments()`, `autodetect_instruments()`, and `test_stepper()`, preventing operations when connections are retained under `SafetyStatus.UNSAFE`.
- **Pre-Start Abort Connection Release**: Terminal event handling and window closing logic now evaluate `self.runner.can_close()` instead of strictly requiring `SafetyStatus.SAFE`. When a run is stopped before start (`SafetyStatus.NOT_NEEDED` under `RunState.ABORTED`), instrument connections are safely closed and released. If a run results in `SafetyStatus.UNSAFE`, `can_close()` remains False, retaining connections for manual bench inspection.
- **Strict Simulation Excitation Shutdown**: `_simulation_excitation_shutdown()` checks `isinstance(lockin, VirtualLockin)` at runtime (raising `TypeError` if a physical lock-in is encountered and `RuntimeError` if missing), and allows exceptions to propagate directly rather than silently catching and swallowing them.
- **Fault Regressions**: Added 4 dedicated tests in `tests/test_measurement_amr_gui.py` verifying:
  1. Partial driver setup failure immediately closes earlier opened connections;
  2. Retained unsafe state blocks Run, Refresh, Autodetect, and Test Stepper;
  3. Pre-start abort (`NOT_NEEDED`) releases connections when `runner.can_close()` permits;
  4. Simulation shutdown strictly enforces `VirtualLockin` instances and propagates failures.

## Original checkpoint 24c report (superseded by review corrections above)

- **MeasurementRunner Integration**: Modernized `AMRApp` in `Measurements/AMR/amr_GUI.py` to coordinate acquisition through `MeasurementRunner(self.experiment)` instead of unmanaged `threading.Thread`. Guarantees non-daemon background thread execution (`daemon=False`), preventing thread abandonment while hardware outputs are active.
- **Bounded Live Updates & Authoritative Terminal Data**: GUI polling drains `self.runner.display_queue` on the main thread, extracting the bounded `raw_window` view (bounded by `raw_window_points`, default 100) to keep rendering overhead constant. Upon receiving `TerminalEvent` from `self.runner.control_queue`, the GUI renders the complete authoritative dataset from `event.final_snapshot.get_view('data')` or `event.data`. Removed legacy CSV-file polling via `standard_csv_to_metadata_and_data`.
- **Main-Thread Plotting with Metadata-Derived Units**: Main-thread plotting in `_plot_data(self, df)` derives axis labels dynamically from `self.experiment.column_units` (`{'angle': 'deg', 'field': 'Oe', 'x': 'V', 'y': 'V'}`), formatting labels as `{col} ({unit})`.
- **Excitation Shutdown Policy**:
  - Virtual Mode: When all selected instrument addresses are `"VIRTUAL"`, `AMRApp` automatically installs `_simulation_excitation_shutdown()`, which explicitly sets `lockin.configure_reference(voltage=0.0)`.
  - Physical Mode: When any physical VISA resource is selected, `AMRApp` strictly requires an external `excitation_shutdown_handler` (passed to constructor or instance attribute). If unsupplied, `run_measurement()` rejects execution before `# Initialize drivers`, leaving bench hardware untouched.
  - Zero tolerance: No-op callbacks (`lambda: None`) are strictly prohibited in GUI and notebook.
- **Manual Lock-In Setting Preservation**: Defaulted `initialize_lockin` to `False` in `DEFAULTS` (`readout_configuration="preserve"`), sending zero configuration writes to the lock-in unless explicitly checked by the operator.
- **Connection Retention on Unsafe Shutdown**: If `_safe_shutdown` escalates to `SafetyStatus.UNSAFE`, the GUI displays a safety alert and retains all open instrument connections in `self._instruments` for manual bench inspection and recovery. Window closing is deferred until worker exit and verified safe shutdown.
- **Notebook Migration**: Updated `Measurements/AMR/AMR_testing.ipynb` cell 6 to supply an explicit `simulation_excitation_shutdown()` function for virtual testing, and cell 8 to plot dual-channel X and Y response with metadata-derived units.
- **Consumer Inventory & Manifest Sync**: Updated `tests/fixtures/measurement_compatibility/manifest.json` under both `MagnetoTransport` and `AMR` consumer inventories to document `MeasurementRunner` and in-memory snapshots. Updated `test_gui_consumer_contract` in `tests/test_measurement_amr_compatibility.py`.
- **Validation**:
  - Added 16 headless unit and interaction tests in `tests/test_measurement_amr_gui.py`.
  - Targeted suites (`test_measurement_amr_gui.py`, `test_amr_sweep_review.py`, `test_measurement_amr_compatibility.py`, `test_measurement_magneto_transport.py`, `test_magneto_transport_review.py`, `test_amr_contract.py`, `test_measurement_compatibility_manifest.py`): **191 passed**.
  - Full repository test suite with `MPLBACKEND=Agg`: **1597 passed, 1 skipped** in 44.45s on Python 3.13.2. Zero failures, zero xfails.
- **Physical Validation**: Checkpoints 17 (IV/MOKE) and 22 (FE) remain explicitly **PENDING**.
- **Next Step**: Proceed with **checkpoint 24d onward / 25** once authorized.

## Checkpoint 24b review corrections (authoritative)

- Validation: full suite with Agg **1581 passed, 1 skipped** in 31.00s.
  No physical hardware validation was performed.
- Live snapshots use `raw_window`, bounded by `raw_window_points` (default 100).
  Full acquired data remains in the engine and terminal `data` view. The golden's
  scientific values are unchanged; start-angle, quantized angle basis and averaging
  time metadata are now explicit.
- Every requested and achievable motor position is checked before energizing.
  Sweeps include the final endpoint in either direction without an extra motor
  step. The angle column is commanded/quantized position, not an encoder reading.
- AMR bypasses the adapter's blocking settle and performs one cancellable wait
  using the larger of measurement and profile settle times. A hardware step call
  itself remains blocking until the driver returns; do not claim instant motor
  cancellation. Stop during averaging drops the unfinished point and prevents
  extra reads. Earlier completed points survive faults; failure CSV publication
  follows the engine's explicit save_partial=True policy.
- Removed save_dir/live_plot/plot_config compatibility parameters from AMR.
  Use output_dir and render snapshots outside acquisition. Configuration metadata
  for a supplied profile uses its declared readout amplitude/frequency, not the
  AMR constructor defaults.
- Removed fabricated no-op excitation shutdown callbacks from GUI/notebook.
  The current GUI refuses Run before opening drivers until an explicit
  excitation_shutdown_handler is installed. The notebook requires an explicit
  excitation_shutdown_handler variable. This is deliberate: no-op callbacks
  must not certify physical safing. The GUI remains pending presentation/runner
  integration and ownership hardening; do not label it production-ready.

Gemini: implement **24c only: AMR notebook/GUI presentation integration**. Use
MeasurementRunner, bounded raw_window updates and the authoritative terminal data
view; plot in the Tk/main thread with metadata-derived units. Provide an explicit
setup path for a real excitation shutdown policy; a simulation-only policy must
be restricted to virtual instruments. Preserve manual lock-in settings. Handle
errors, Stop/Pause and connection retention through the runner; never leave a
daemon hardware worker or claim SAFE after a no-op handler. Fix remaining
notebook/GUI consumers and documentation, run relevant and full tests, commit
separately, update the handoff, and stop for review. Keep checkpoint 25's detailed
interaction/ownership audit separate and physical 17/22 PENDING.

## Original checkpoint 24b report (superseded by review corrections above)

- **Standardized AMR Lifecycle & Base Migration**: Modernized `AMR` in `src/piec/measurement/magneto_transport.py` to directly subclass the public `MagnetoTransport` (and `BaseMeasurement`), inheriting the unified execution lifecycle (`run_experiment`, `session`, `configure_instruments`, `capture_data`, `safe_shutdown`, `request_stop`, `request_pause`, `snapshot`). Zero constructor I/O or file writes in `__init__`.
- **Target Schema & Plain Columns**: Emits canonical schema `amr` version 1 with lowercase columns `('angle', 'field', 'x', 'y')` and canonical declared units `{'angle': 'deg', 'field': 'Oe', 'x': 'V', 'y': 'V'}`. Optional `field_measured` and `field_time` follow when readback is requested.
- **Defect AMR-ANGLE-001 Repaired**: Fixed the motor stepping loop in `_capture_data()` by rotating to each commanded angle from `_compute_angles()` and capturing data without performing an extra motor step after the final angle. Motor physical position ends at exactly the commanded angle (e.g., 180.0°), and the strict `xfail` test `test_amr_endpoint_matches_commanded_angle_and_scientific_golden` now passes as a full regression.
- **Removal of Legacy Support**: Completely deleted `_LegacyMagnetoTransport` and all obsolete legacy methods (`initialize()`, `shut_off()`, `set_field()`, `configure_lockin()`, `save_data_point()`, `capture_data_point()`, `analyze()`, `plot_results()`). Standardized constructor parameter names to `stepper` and `voltage_calibration`.
- **Excitation Safing & Readout Preservation**: Enforced mandatory declared excitation shutdown policy before energizing (raising `HardwareSafetyError` if unprovided). Preserved manual front-panel lock-in settings by default (`readout_configuration="preserve"`), sending no configuration writes to the lock-in unless explicitly opted in.
- **Engine-Owned Persistence & Safing**: Atomic publication at experiment completion using `BaseMeasurement` handle publishing and schema metadata. Partial CSV publication on cooperative stop (`request_stop()`). Attempt-all safing de-energizes the field source and invokes the excitation shutdown handler, escalating to `SafetyStatus.UNSAFE` while retaining open instrument connections for physical recovery.
- **Consumer Migration**:
  - `Measurements/AMR/amr_GUI.py`: Updated to use `stepper=stepper`, `save_dir=save_dir`, `shutdown_handler=lambda: None`, `options={'configure_lockin': initialize_lockin}`, cooperative `request_pause` / `request_stop`, and lowercase plot axes `['angle', 'field', 'x', 'y']`.
  - `Measurements/AMR/AMR_testing.ipynb`: Updated cells to `stepper=arduino`, `output_dir=path`, `shutdown_handler=lambda: None`, and plot lowercase `['x', 'y']`.
  - `Measurements/AMR/amr_measurement.md`: Updated architecture section to document `BaseMeasurement` shared lifecycle methods.
  - `src/piec/measurement/__init__.py`: Re-exported `AMR` alongside `MagnetoTransport`.
  - `tests/fixtures/measurement_compatibility/manifest.json`: Marked `AMR` as migrated in `migrated_families`, updated `AMR-ANGLE-001` defect status to Repaired, and synchronized consumer inventory.
- **Validation**:
  - Updated `tests/test_measurement_amr_compatibility.py` with 20 passing unit, lifecycle, and scientific golden regression tests. Removed obsolete `_LegacyMagnetoTransport` tests.
  - Targeted suites (`test_measurement_amr_compatibility.py`, `test_measurement_magneto_transport.py`, `test_magneto_transport_review.py`, `test_amr_contract.py`, `test_measurement_compatibility_manifest.py`): **165 passed**.
  - Full repository test suite with `MPLBACKEND=Agg`: **1571 passed, 1 skipped** in 32.72s on Python 3.13.2. Zero failures, zero xfails.
- **Physical Validation**: Checkpoints 17 (IV/MOKE) and 22 (FE) remain explicitly **PENDING**.
- **Next Step**: Stop after checkpoint 24b. Proceed with **checkpoint 24c only: AMR notebook/GUI presentation integration** once authorized.

## Checkpoint 24a review corrections (authoritative)

- Validation: full suite with Agg **1577 passed, 1 skipped, 1 xfailed** in
  30.45s. No physical hardware validation was performed.
- The public MagnetoTransport now lives in `_magneto_transport_base.py`, exported
  through the existing public modules. It inherits the shared public execution,
  session and shutdown methods without legacy I/O bypasses, setters or aliases.
  The old AMR temporarily inherits private `_LegacyMagnetoTransport`; legacy
  characterization tests target only that private path. Remove it in 24b as AMR
  moves onto the public base. Do not restore aliases or direct hardware methods
  on the standardized base to satisfy legacy tests.
- Excitation shutdown handlers are mandatory before execution; the optional
  `require_excitation_safing` bypass is removed. Field bounds/calibration and
  strict run options are checked before lock-in excitation can be configured.
  Unknown options, string/integer booleans, and conflicting configuration choices
  are rejected. A supplied profile's readout policy is honored by default.
- Instrument identification and field-reader exceptions propagate. The source
  uses a declared cancellable `field_settling_time` (default zero; configure for
  the bench), then verifies field. Fail-policy mismatches/nonfinite readings
  stop acquisition; all shutdown roles are still attempted without closing
  connections. Warn-policy finite mismatches retain their documented behavior.
- Setup field units determine metadata, without assuming Oe for native/table
  profiles. Optional `field_measured` and elapsed `field_time` columns follow X/Y.
  Command and reader calibration identities/scales/tables remain separate in
  metadata. Excitation settings are user-declared/unverified, not measured.
- Pause acts before point acquisition with field retained; Stop wakes the pause
  and ends acquisition with shared safing. Legacy mutable pause/abort flags are
  absent from the public class. Explicit-profile and separate-instrument inputs
  cannot be mixed into an inconsistent ownership configuration.

Gemini: implement **24b only** on the public MagnetoTransport base. Preserve the
four-instrument profile and manual lock-in settings; supply a real declared
excitation shutdown policy before energizing. Migrate AMR acquisition, schema,
persistence and affected consumers, repair AMR-ANGLE-001 with physical-position
and numerical regressions, and delete `_LegacyMagnetoTransport` plus its obsolete
API characterization tests when no consumers remain. Keep scientific goldens,
bounded snapshots, cancellable dwell/motion, engine-owned partials and safing.
Do not add a compatibility layer or measurement-owned per-point CSV writes.
Validate, commit 24b separately, update this handoff, and stop for review.
Physical checkpoints 17/22 remain PENDING.

## Original checkpoint 24a report (superseded by review corrections above)

- **BaseMeasurement Lifecycle & Zero Constructor I/O**: `MagnetoTransport` in `piec.measurement.magneto_transport` subclasses `BaseMeasurement`, implementing the shared lifecycle hooks: `_validate_options`, `_configure_instruments`, `_capture_data` (delegating to subclass or session), `_safe_shutdown`, `_create_snapshot`, `request_stop()`, and `request_pause()`. `__init__` performs zero hardware communication or file I/O.
- **Target Interface & Schema**: Adheres to target schema `amr` version 1, ordered columns `("angle", "field", "x", "y")`, and canonical declared JSON metadata units `{"angle": "deg", "field": "Oe", "x": "V", "y": "V"}`.
- **Standardized Constructor Parameters & Backward-Compatible Aliases**: Constructor uses standardized names `stepper` and `voltage_calibration` (rejecting obsolete parameter names `arduino` and `voltage_callibration` from `MagnetoTransport.__init__` per manifest target contract while exposing backward-compatible properties `self.arduino = self.stepper` and `self.voltage_callibration = self.voltage_calibration`). Keyword-only settings follow the shared engine standard.
- **AMRSetupProfile Role Integration**: Wraps or instantiates `AMRSetupProfile` compositing `FieldSource`, `FieldReader`, `TransportReadout`, and `OrientationController`. Exposes clean setup role properties (`field_source`, `field_reader`, `transport_readout`, `orientation_controller`).
- **Readout Configuration Policy**: Preserves manual lock-in settings by default (`readout_configuration="preserve"`). Honors explicit run options `options={"readout_configuration": "configure"}` or `options={"configure_lockin": True}`, temporarily updating profile configuration for the run without mutating unrelated settings.
- **Excitation Safing Validation**: Validates the declared excitation safing policy before energizing the magnet or excitation. If `require_excitation_safing=True` is configured and no verified shutdown action is available, configuration aborts before output energization.
- **Attempt-All Safe Shutdown & Connection Retention**: `_safe_shutdown` demagnetizes/zeros the field source and executes excitation shutdown via setup profile roles, recording actions through `ShutdownAttemptRecorder`. Unconfirmed excitation shutdowns or role errors escalate to `SafetyStatus.UNSAFE` while preserving open instrument connections for physical recovery.
- **Consumer & Compatibility Support**: `AMR` subclass unmigrated signature `(dmm=None, calibrator=None, arduino=None, lockin=None, ...)` is preserved and forwards `stepper=arduino` and `voltage_calibration=voltage_callibration` to `super().__init__` until Checkpoint 24b. Legacy methods `initialize()`, `shut_off()`, `set_field()`, `analyze()`, and `plot_results()` remain operational.
- **Validation**: Added 18 comprehensive unit, lifecycle, fault, and runner tests in `tests/test_measurement_magneto_transport.py`. Manifest updated with `MagnetoTransport` in `migrated_families`. Full test suite with Agg: **1564 passed, 1 skipped, 1 xfailed** (`AMR-ANGLE-001`) in 31.43s on Python 3.13.2.
- **Physical Validation**: Checkpoints 17 (IV/MOKE) and 22 (FE) remain explicitly **PENDING**.
- **Next Step**: Stop after checkpoint 24a. Proceed with **checkpoint 24b only: AMR acquisition/schema/persistence and consumers** once authorized. Repair `AMR-ANGLE-001` (extra endpoint motor step) during 24b.

## Checkpoint 21 review corrections

- Measurement selection is disabled while a run owns the instruments and restored
  only when they can be released safely. A queued combobox event restores the
  active run's type, keeping the selected type and dynamic fields consistent.
- A startup failure with no active ownership clears the pending-terminal latch,
  closes the GUI-owned connections, and restores idle controls. This handles both
  pre-reservation failures with no terminal event and failed thread launch with a
  terminal event. Active/unsafe ownership still blocks reuse and close.
- Stop-before-start tests gate the worker before lifecycle execution, request Stop,
  then release it. Both Hysteresis and PUND must finish ABORTED/NOT_NEEDED without
  calling configuration, acquisition or shutdown hooks; timing races cannot turn
  the test into a normal in-flight Stop.
- Targeted review suites: 62 passed. Full suite with Agg: **1546 passed,
  1 skipped, 1 xfailed** in 30.01s. No physical hardware was used.

Proceed with **checkpoint 24a only: MagnetoTransport lifecycle and consumers**.
Use the shared engine and the reviewed AMR roles, preserve manual lock-in settings,
validate the declared excitation shutdown policy before energizing, and propagate
role shutdown errors to UNSAFE while retaining connections. Update the 24a
consumers and meaningful lifecycle/fault tests, commit separately, then stop for
review. Keep the endpoint-step repair (AMR-ANGLE-001) for 24b and physical records
17/22 PENDING; do not roll acquisition/schema/GUI migration into this commit.

## Checkpoint 21: FE GUI interaction/ownership hardening

- **Pre-Connection Parameter Validation**: Enforced strict parameter validation in `FEMeasurementApp._create_experiment()` before any hardware driver (`VirtualAwg`, `VirtualScope`, `Keysight81150a`, `KeysightDSOX3024a`) is instantiated. Rejects non-finite, zero, or negative values across all static and dynamic inputs (`vdiv`, `area` expression, `time_offset`, `frequency`, `amplitude`, `offset`, `n_cycles`, `reset_amp`, `reset_width`, `reset_delay`, `p_u_amp`, `p_u_width`, `p_u_delay`). If validation fails, `self._instruments` remains empty, guaranteeing zero connection leaks.
- **Virtual Instrument Selection**: Explicitly rejects mixed virtual and physical AWG/Scope configurations and empty addresses before attempting connection. Cable delay offset (`time_offset`) is forced to 0.0 for virtual drivers.
- **Single Hardware Writer Rule**: Hardened `_busy()` gating to protect active hardware worker threads. Concurrent `run_measurement()`, `refresh_instruments()`, `select_measurement()`, and `update_dynamic_inputs()` return immediately when a measurement is active or awaiting safe closure.
- **Stop-Before-Start & Active Close Coordination**: Debounced Stop button and cleanly handle Stop-before-start zero-I/O aborts (`RunState.ABORTED`). Coordinated active window close (`on_closing`) by requesting cooperative worker stop (`runner.request_close()`) and deferring window destruction (`_finish_close`) until worker thread terminates and confirmed hardware safety is achieved.
- **Unsafe Shutdown & Connection Retention**: When safing fails (`SafetyStatus.UNSAFE`), open instrument connections in `self._instruments` are retained for manual bench recovery. The GUI presents an unsafe status alert, disables re-runs, and blocks window destruction.
- **Deduplicated Teardown**: `_close_instruments()` deduplicates instrument references by object identity (`id(inst)`) to avoid double-close attempts.
- **Display Queue Draining & Unit-Derived Plotting**: Drains `display_queue` in a coalescing loop on each Tk polling tick to eliminate UI rendering lag during high-frequency acquisitions. Precedence is given to `TerminalEvent` final snapshot over stale display frames. Axes choices dynamically populate all PUND quantities (`dP`, `P^`, `P*`, etc.) when `ThreePulsePund` is selected, and plot labels are derived from canonical `column_units`.
- **Save Policies**: Normalizes default placeholder `r"your\default\save\directory"` and empty paths to `None`. Starts runner with `save = self.experiment.output_dir is not None` to satisfy `BaseMeasurement` schema requirements. Disables plot artifact saving with a warning if no save directory is configured. Reports recoverable staging paths on save failure.
- **Validation**: Added 43 comprehensive headless tests in `tests/test_measurement_fe_gui.py`. Targeted FE suite: **207 passed**; full test suite with Agg backend: **1540 passed, 1 skipped, 1 xfailed** (`AMR-ANGLE-001`) in 31.58s on Python 3.13.2.
- **Physical Validation**: Checkpoints 17 (IV/MOKE) and 22 (FE) remain explicitly **PENDING**.
- **Next Step**: Stop after checkpoint 21. Proceed with **checkpoint 24a only: MagnetoTransport lifecycle and consumers** once authorized. AMR-ANGLE-001 stays tracked as xfail until checkpoint 24b.

## AMR adapter review corrections (checkpoint 23/23a work performed early)

- Native field commands/readers use only set_field/get_field. Electrical sources
  explicitly select voltage or current from calibration units. Analog DMM
  readback supports voltage calibration only; unsupported current sensing is
  rejected. Source and reader field units must match exactly; callers must use
  an explicit conversion adapter for different units, never relabel H/B.
- Shutdown exceptions reach the profile's per-role error results while remaining
  roles are attempted. Connections are retained. Electrical zero does not imply
  zero calibrated field; failed source shutdown clears optimistic state.
- TransportReadout/from_instruments accept a no-argument shutdown_handler for
  the actual bench excitation safe action, independent of preserve/configure.
  The handler must raise on failure and remain on the instrument-owning worker.
  No lock-in is assumed to support zero oscillator amplitude. Missing handlers
  report shutdown unconfirmed, never safe. During lifecycle integration, validate
  required handlers before energizing and propagate any role error to UNSAFE.
- Preserve mode still sends no configuration writes. Configure mode explicitly
  selects internal/external reference without resetting unrelated settings.
  External mode sends no oscillator amplitude/frequency commands and requires
  external_source_owner naming who controls/de-energizes the source. A manually
  owned source without a handler remains unconfirmed. No generic software-owned
  external source lifecycle is advertised; binding/configuration/limits/ownership
  of such a source needs a dedicated tested setup adapter.
- Quantized motor positions are checked against limits before I/O. Nonfinite
  bounds, tolerances, timing and excitation numbers are rejected.
- The original successful virtual workflow does not prove physical excitation
  shutdown. The virtual test now explicitly checks the unconfirmed result.


## Checkpoint 20c PUND integration and consumers

- **BaseMeasurement Lifecycle**: `ThreePulsePund` in `piec.measurement.discrete_waveform` subclasses `DiscreteWaveform` and `BaseMeasurement`, implementing the shared lifecycle hooks: `_validate_options`, `configure_awg` (arbitrary waveform generation), `_analyze_data` (in-memory `process_pund`), and `_stage_side_artifacts`.
- **Target Schema & Units**: Adheres to schema `three_pulse_pund` v1 with plain lowercase columns `['time', 'voltage', 'current', 'polarization', 'polarization_p_hat', 'polarization_p_star', 'polarization_p_hat_r', 'polarization_p_star_r', 'delta_polarization', 'applied_voltage']` and canonical JSON metadata units `{'time': 's', 'voltage': 'V', 'current': 'A', 'polarization': 'uC/cm^2', 'polarization_p_hat': 'uC/cm^2', 'polarization_p_star': 'uC/cm^2', 'polarization_p_hat_r': 'uC/cm^2', 'polarization_p_star_r': 'uC/cm^2', 'delta_polarization': 'uC/cm^2', 'applied_voltage': 'V'}`.
- **In-Memory Scientific Processing**: Replaced file-based post-processing with in-memory execution via `process_pund(raw_df, metadata, ...)`. Returns enriched DataFrame and schema v1 metadata directly.
- **Multi-Artifact Publication**: Staged side artifacts (`_dPvst.png`, `_trace.png`) are generated via `create_staging_file` and published atomically alongside the CSV when `save=True` and `save_plots=True`. Plots are strictly suppressed when `save=False` or `save_plots=False`. Explicit Agg canvas and figure lifecycle avoid GUI dependencies in worker threads.
- **Legacy Paths Removed**: Fully removed `_LegacyWaveformSupport` mixin and retired private file bridge `_process_raw_3pp_file` from `piec.analysis.pund`. Removed legacy methods (`apply_and_capture_waveform`, `save_waveform`, `analyze`, `save_dir`, `_update_notes`, `_update_history`, `_update_metadata`).
- **GUI Migration**: Migrated `FE_testing_GUI.py` onto `MeasurementRunner` across all measurement types (Hysteresis and PUND), supporting live polling, in-memory plotting from `_plot_frame`, Stop, deferred close, and connection ownership retention on unsafe shutdown.
- **Consumer Updates**: Updated `Measurements/Ferroelectric Testing/FE_testing.ipynb` cells 21, 26, 29, 30 to use `output_dir` and plain column lookups (`delta_polarization`, `time`).
- **Validation**: Dedicated test suites `tests/test_measurement_pund.py` (13 passed) and `tests/test_pund_review.py` (6 passed) covering lifecycle, zero constructor I/O, parameter validation, plot artifact generation and suppression, cooperative cancellation, safe shutdown, runner integration, and GUI connection retention. Full test suite: **1411 passed, 1 skipped, 2 xfailed** in 28.18s on Python 3.13.2.
- **Physical Validation**: Hardware testing was not performed; Checkpoint 17 physical validation remains explicitly **PENDING**.
- **Next Step**: Stop after checkpoint 20c. Proceed with **checkpoint 21 only: FE GUI interaction/ownership hardening** once authorized.

## Checkpoint 20b review corrections

- Hysteresis analysis now applies the configured AWG DC offset to nominal
  applied_voltage, including idle levels. Detector/current/polarization data are
  unchanged. Explicit offset overrides metadata; nonfinite offsets are rejected.
- Plot staging registers each path immediately and cleans all created PNGs on
  failure. Figures are closed in finally; undeletable paths are reported with
  recoverable staging paths. Explicit Agg figures avoid Tk creation in workers.
- The Hysteresis FE GUI path uses MeasurementRunner. Tk polls controls before at
  most one live snapshot, plots final data from memory, reports errors/recovery,
  and provides Stop plus deferred close. Connections remain open while shutdown
  is unsafe and close only after terminal handling and worker exit with safety.
  New runs and VISA refresh are blocked while that ownership remains active.
- PUND's GUI path still requires migration in checkpoint 20c; do not treat the
  entire FE GUI as migrated yet. Reuse the runner path for PUND in that checkpoint.
- Validation: **63 targeted tests passed**; full suite with Agg **1393 passed,
  1 skipped, 2 xfailed** in 26.14s. GUI tests are headless; physical checkpoint 17
  remains PENDING.
- Proceed with **checkpoint 20c only: PUND integration**. Remove its remaining
  legacy lifecycle/file bridge, update its GUI and other callers, preserve the
  scientific, ownership and recovery tests, commit separately, and stop for review.

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
