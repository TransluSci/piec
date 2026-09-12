# Simulation Module

This module provides tools for simulating various materials and their responses. It is primarily designed to support virtual instruments and testing scenarios where physical hardware is not available.

## Role contracts (checkpoint 27)

`contracts.py` defines electrical loads and material roles. Load inputs/outputs
use V, A, Ohm and s. The FE material's native polarization is C/m^2; measurement
output may convert to uC/cm^2 explicitly. `LoadResponse.state` is a detached,
immutable snapshot of scalar/container state; apparent resistance can be infinite
or undefined at zero current.

- `reset()` restores constructor start time and the stored RNG seed, including
  replay within an instance constructed without an explicit seed. Independent
  unseeded instances need not agree. Use an explicit seed for cross-instance replay.
- Absolute role timestamps cannot move backwards outside reset. FE waveform
  timestamps are local to an acquisition; valid uniformly sampled waveforms
  advance its clock by their duration.
- `CapacitiveLoad` requires positive elapsed time. It uses backward Euler with
  interval-average current and end-step leakage. Choose a timestep small enough
  to resolve the circuit; it does not resolve sub-step compliance transitions.
- `DiodeLoad` models Shockley conduction with optional series resistance, without
  reverse breakdown. Reverse current beyond saturation reaches the supplied voltage
  compliance limit. `noise_std` is A for voltage-source readback;
  `voltage_noise_std` is V for current-source readback.
- `MagneticSample.get_voltage_response(excitation_current=...)` requires current
  in A and returns a plain `(X, Y)` tuple in V. The resistive model has Y=0;
  there is no scalar/tuple compatibility wrapper or implicit excitation current.
  The existing VirtualLockin fallback passes its declared simulation-only
  `excitation_current` setting (default 1 uA). This is not a measured sample current
  or a model of the physical lock-in output circuit.

## Driver virtual hooks (checkpoint 28a)

- `VirtualLockin` (lock-in driver family) supports generic per-instance hook injection via
  `xy_reader` or `transport_hook` (in constructor, via property, or via `set_xy_reader`).
- Injected hooks take strict precedence over the deprecated global `mag_sample` fallback.
- The generic driver contains no sample-, magnetic-, or AMR-specific logic; material behavior
  remains external to the driver.
- Declared excitation current (in A) is forwarded to hooks that accept `excitation_current`
  or a single positional argument; 0-argument hooks are supported as well.
- Invocation is selected by signature binding before calling the hook exactly once.
  Hook exceptions propagate unchanged. Callables with unavailable signatures follow
  the zero-argument contract; wrap them in a Python function to receive current.
- Excitation current accepts finite signed values and zero, including after construction.
  Reference voltage and declared sample current are independent simulation settings;
  converting oscillator output voltage to current requires an explicit external circuit model.
- Reference configuration validates amplitude, frequency, source and phase before changing
  state. `read_data()` derives phase in degrees from `atan2(Y, X)`.
- Returns plain `(X, Y)` tuples in V without compatibility wrappers. Non-sequence, wrong-length,
  or non-finite hook returns raise `TypeError` or `ValueError`.
- `reset()` restores constructor excitation current and default settings while preserving the
  injected hook. Instance assignments to `lockin.mag_sample` do not pollute global shared sample state.
  Reset does not reset a closure's RNG, time or material: that state is owned by the
  setup and must be reset there. A future VirtualBench will coordinate those resets.

## Driver virtual hooks: DMM family (checkpoint 28b)

- `VirtualDMM` (DMM driver family) supports generic per-instance hook injection via
  `voltage_reader` or `reader_hook` (in constructor, via property, or via `set_voltage_reader`).
- Injected hooks take strict precedence over the deprecated global `mag_sample` fallback.
  When an explicit hook is injected, `mag_sample` is not accessed.
- The injected path adds no sample-, sensor-, or material-specific logic; physical modeling
  remains external in the hook. The historical `current_field / 10000` fallback remains
  solely for existing shared-sample simulations; it is not a general sensor calibration.
- The hook receives coupling parameters if declared: accepts zero arguments, keyword `ac` or `coupling`,
  or positional-only `ac` or `coupling`. Callables with unavailable signatures follow the zero-argument contract.
- Named `ac` and `coupling` parameters are supplied together when both are declared,
  including mixed positional-only/keyword signatures. Optional unrelated parameters
  keep their defaults. A `**kwargs` hook also receives undeclared coupling settings.
- Invocation is selected by signature binding before calling the hook exactly once. Hook exceptions
  propagate unchanged without retries or fallback invocation.
- Returns scalar `float` voltages in Volts. Preserves IEEE 754 non-finite numbers (`inf`, `-inf`, `nan`)
  for DMM hardware overload emulation (per Checkpoint 6 contract). Rejects non-scalar collections
  (`tuple`, `list`, multi-element or non-0d `ndarray`) with `TypeError`.
- `reset()` restores default driver-owned configuration (`sense_func="VOLT"`, `coupling="DC"`,
  `sense_mode="2W"`, `sense_range=None`, `autorange=True`, `integration_time=1.0`) while preserving
  the injected hook. Instance assignments to `dmm.mag_sample` do not pollute global shared sample state.
- Driver reset does not reset setup-owned closures, external material models, clocks, or RNG seeds:
  that state is owned by the setup / fixture and must be reset there. A future VirtualBench will coordinate resets.
- Manual sense range and integration time must be positive and finite. Rejected
  configuration values leave state unchanged; non-finite voltage readings remain
  permitted by the overload contract.

## Driver virtual hooks: DC Calibrator family (checkpoint 28c)

Output notifications describe effective output: `value` uses the active electrical
mode, while `voltage`/`current` are zero for the inactive mode and both zero when
disabled. Crowbar retains the previous electrical mode in its notification.
Getters continue to expose stored setpoints, which can be restored by enabling output.
If a hook fails, `output_on` and `_output_enabled` become `None` (unconfirmed).
Errors propagate without retry; a subsequent successful command confirms state.
This applies to reset and shutdown too: failure must not be interpreted as disabled
output. Pure `*args` hooks receive the effective value as their first argument.

- `VirtualCalibrator` (DC calibrator driver family) supports generic per-instance hook injection via
  `output_hook` or `field_hook` (in constructor, via property, or via `set_output_hook`).
- Injected hooks take strict precedence over the deprecated global `mag_sample` fallback.
  When an explicit hook is injected, `mag_sample` is not accessed or mutated.
- The injected path adds no sample-, sensor-, or magnetic-specific logic; physical modeling
  remains external in the hook closure. The historical `value * 10000.0` fallback remains
  solely for existing shared-sample simulations.
- Hook receives commanded output parameters if declared: accepts single output value (positional
  or named), `mode` ("voltage" or "current"), `output_on` (boolean), or `**kwargs`.
  Zero-argument hooks are also supported.
- Invocation is selected by signature binding before calling the hook exactly once. Hook exceptions
  propagate unchanged without retries or fallback invocation.
- Declared units are `{"voltage": "V", "current": "A"}`. Output values must be finite numeric values;
  rejected values leave state unchanged.
- `reset()` restores default driver-owned configuration (`output_on=False`, `voltage=0.0`, `current=0.0`,
  `mode="voltage"`, engaging crowbar) while preserving the injected hook. If a hook is injected, it is
  notified of 0.0 V output. Instance assignments to `cal.mag_sample` do not pollute global shared sample state.
- Driver reset does not reset setup-owned closures, external material models, clocks, or RNG seeds:
  that state is owned by the setup / fixture and must be reset there. A future VirtualBench will coordinate resets.

## Driver virtual hooks: Stepper Motor family (checkpoint 28d)

Directions are validated exactly (1, 0 or -1); fractional values are never
truncated. Named motion parameters and unnamed required angle/delta arguments
can be mixed; unrelated optional arguments keep their defaults. Reset sends
the actual delta from the previous angle to zero, so delta-only models remain
consistent with absolute-angle models. Changing steps-per-revolution recalculates
the coordinate angle and notifies the setup; this is not a physical move.
Reset and scale notifications retain the same error/unknown-motion rules as step.

- `VirtualStepper` (stepper motor driver family) supports generic per-instance hook injection via
  `angle_hook`, `position_hook`, or `step_hook` (in constructor, via property, or via `set_angle_hook`).
- Injected hooks take strict precedence over the deprecated global `mag_sample` fallback.
  When an explicit hook is injected, `mag_sample` is never accessed or mutated.
- The injected path adds no sample-, stage-, or material-specific logic; physical modeling
  (such as stage orientation, sample rotation, AMR angle dependence, or Hall probes) remains external
  in the hook closure or simulation model.
- Hook receives commanded motion and position parameters via signature binding: accepts total angle
  in degrees (positional or named `angle`, `total_angle`, `target_angle`, `value`, `total`), delta angle
  (`delta_angle`, `delta`), step position (`position`, `total_steps`, `target_position`, `steps`),
  and motion status `moving` (boolean). Positional-only, pure `*args`, `**kwargs`, and zero-argument hooks
  are also supported.
- Invocation is selected by signature binding before calling the hook exactly once. Hook exceptions
  propagate unchanged without retries or fallback invocation.
- Declared units are `{"angle": "deg", "position": "steps"}`. Step counts must be finite non-negative
  integers; direction must be 1 (CW) or 0 / -1 (CCW); `steps_per_revolution` must be a positive integer.
  Rejected commands leave driver state unchanged.
- Distinguishes stored settings from effective motion state: `steps_per_revolution` and position setpoints
  are stored settings. If a hook fails during any motion or shutdown command (`step`, `stop`, `halt`,
  `set_position`, `set_zero`, `reset`), `moving` is marked `None` (unconfirmed). A failed command does not
  falsely confirm shutdown or stopped state until a subsequent command succeeds.
- `reset()` restores default driver-owned configuration (`position=0`, `angle=0.0 deg`, `moving=False`,
  and initial `steps_per_revolution`) while preserving the injected hook. If a hook is injected, it is notified
  of 0.0 deg output. Instance assignments to `stepper.mag_sample` do not pollute global shared sample state.
- Driver reset does not reset setup-owned closures, external material models, clocks, or RNG seeds:
  that state is owned by the setup / fixture and must be reset there. A future VirtualBench will coordinate resets.

## Driver virtual hooks: Oscilloscope family (checkpoint 28e)

- `VirtualScope` (oscilloscope driver family) supports generic per-instance hook injection via
  `waveform_hook`, `channel_hook`, or `data_hook` (in constructor, via property, or via `set_waveform_hook`).
- Injected hooks take strict precedence over the deprecated global `sample` (ferroelectric) fallback.
  When an explicit hook is injected, `sample` is never accessed or mutated.
- The injected path adds no material-specific or ferroelectric logic; physical modeling
  (such as dielectric polarization switching, PUND pulses, or photodiode signals) remains external
  in the hook closure or simulation model.
- Hook receives commanded acquisition parameters via signature binding: accepts `channel` (positional
  or named `channel`, `ch`), horizontal scale `tdiv`, vertical scale `vdiv`, `x_range`, `y_range`,
  `y_position`, `x_position`, `coupling`, `points`, and `state`. Positional-only, pure `*args`,
  `**kwargs`, and zero-argument hooks are supported.
- Invocation is selected by signature binding before calling the hook exactly once. Hook exceptions
  propagate unchanged without retries or fallback invocation.
- Declared units are `{"voltage": "V", "time": "s"}`. Input configurations (channel 1-4, positive finite scales,
  bounds-checked positions and trigger levels, validated coupling/slopes/modes) are validated before mutating state.
- Supports standardized waveform outputs: returns `pd.DataFrame` with `'Time'` and `'Voltage'` columns,
  handling tuples `(voltages, times)`, dictionaries, and DataFrames. Mismatched lengths, empty arrays,
  negative times, and non-finite timestamps are rejected.
- `reset()` restores default driver-owned configuration (scales, trigger, channel states) while preserving
  the injected hook intact. Instance assignments to `scope.sample` do not pollute global shared sample state.
- Driver reset does not reset setup-owned closures, external material models, clocks, or RNG seeds:
  that state is owned by the setup / fixture and must be reset there. A future VirtualBench will coordinate resets.

## Driver virtual hooks: Arbitrary Waveform Generator family (checkpoint 28f)

- `VirtualAwg` (arbitrary waveform generator driver family) supports generic per-instance hook injection via
  `waveform_hook`, `apply_hook`, or `trigger_hook` (in constructor, via property, or via `set_waveform_hook`).
- Injected hooks take strict precedence over the deprecated global `sample` (ferroelectric) fallback.
  When an explicit hook is injected, `sample` is never accessed or mutated.
- The injected path adds no material-specific or ferroelectric logic; physical modeling
  (such as Landau-Devonshire switching, prep points, PUND pulse sequences, or material response)
  remains external in the hook closure or simulation model.
- Hook receives generated synthetic waveforms and timing parameters via signature binding: accepts
  `(v, t)`, `(v, t, channel)`, named parameters (`v`, `voltages`, `waveform`, `v_applied`, `data`, `t`, `times`,
  `timestamps`, `time`, `channel`, `ch`, `freq`, `frequency`, `duration`), single-argument `(v)`,
  positional-only `(v, t, /)`, variadic `*args`/`**kwargs`, and zero-argument notifications `()`. Unrelated
  optional parameters retain their defaults.
- Invocation is selected by signature binding before calling the hook exactly once. Hook exceptions
  propagate unchanged without retries or fallback invocation.
- Declared units are `{"voltage": "V", "frequency": "Hz", "time": "s"}`. Input configurations
  (channel 1-2, positive finite frequency, finite amplitude, finite offset, valid duty cycle / symmetry
  in [0.0, 100.0], positive pulse width and non-negative pulse delay, validated polarity/slopes/modes/sources)
  are validated atomically before mutating driver state. Atomic methods `configure_waveform`,
  `configure_pulse`, and `configure_trigger` reject invalid calls leaving driver state unchanged.
- `reset()` restores default driver-owned configuration (default scales, frequencies, waveforms, channel states,
  all outputs OFF) while preserving the injected hook intact. Instance assignments to `awg.sample` do not pollute
  global shared sample state.
- Driver reset does not reset setup-owned closures, external material models, clocks, or RNG seeds:
  that state is owned by the setup / fixture and must be reset there. A future VirtualBench will coordinate resets.

## Driver virtual hooks: Sourcemeter family (checkpoint 28g)

- `VirtualSourcemeter` (sourcemeter driver family) supports generic per-instance hook injection via
  `load_hook`, `source_hook`, `measure_hook`, or `transport_hook` (in constructor, via property, or via `set_load_hook`).
- Injected hooks take strict precedence over the default unhooked fallback.
  When an explicit hook is injected, the load is evaluated under active operating mode and stimulus.
- Supports both `ElectricalLoadContract` instances (e.g. `ResistorLoad`, `DiodeLoad`, `CapacitiveLoad`)
  and general callables.
- Supports voltage-source mode (`source_func == 'VOLT'`) and current-source mode (`source_func == 'CURR'`).
- The load must solve both terminal quantities under compliance. Responses exceeding the current
  limit in voltage mode or voltage limit in current mode are rejected, including responses that
  declare a compliance flag. The driver does not clip one quantity and fabricate a new load relation.
- Clocked load contracts use their setup-owned timebase and share a cached evaluation across
  repeated reads at the same time/operating point. Advance the clock before the first capacitor
  evaluation and subsequent integration steps. The driver never advances or resets that clock.
  Output-off isolates the simulated terminal readback but does not discharge/reset external load state.
  Callable `time`/`t` arguments use the callable's timebase when provided, otherwise `None`.
- Distinguishes stored settings from effective terminal output:
  - `source_voltage`, `source_current`, `voltage_compliance`, and `current_compliance` are stored setpoints
    available in `state` and via SCPI queries (`:SOUR:VOLT:LEV?`, `:SOUR:CURR:LEV?`).
  - Effective output: when `output_on` is `False`, effective terminal voltage is 0.0 V, current is 0.0 A,
    `compliance_tripped` is `False`, and `effective_voltage` / `effective_current` properties report 0.0 V / 0.0 A.
    When a hook is injected, `get_voltage()`, `get_current()`, and `quick_read()` report 0.0 V / 0.0 A when output is off.
    (Unhooked fallback preserves historical return values for existing Level 2 contract tests).
- Unconfirmed state on failure:
  - If a hook raises an exception during output enable/disable (`output()`), setpoint updates
    (`set_source_voltage()`, `set_source_current()`), convenience configuration (`configure_voltage_source()`,
    `configure_current_source()`), or `reset()`, `state['output_on']` and `_output_enabled` become `None` (unconfirmed).
  - Unconfirmed output causes measurement/effective-output/compliance readbacks to raise until
    an explicit output command succeeds; it is never reported as confirmed zero.
  - Exceptions propagate unchanged without retries or masking.
- Flexible signature binding:
  - Binds `(mode, stimulus, compliance)`, `(v, i)`, named parameters (`mode`, `source_func`, `stimulus`, `value`,
    `voltage`, `current`, `v`, `i`, `compliance`, `output_on`, `channel`, `time`), single-arg `(stimulus)`,
    zero-arg `()`, positional-only, `*args`, and `**kwargs`.
  - Unrelated optional parameters retain their defaults.
- Normalizes and validates return values: `LoadResponse`, `(v, i)` tuple, complete voltage/current dict mapping, or scalar numeric.
  `None` is allowed only for output-off notification; it cannot provide active measurements.
  Rejects non-numeric types with `TypeError` and non-finite numbers with `ValueError`.
- Declared units are `{"voltage": "V", "current": "A", "resistance": "Ohm", "time": "s"}`.
  Validates channel, numeric types, finiteness, and positive compliance before mutating state.
- `reset()` restores default factory driver-owned configuration (`output_on=False`, `source_func='VOLT'`,
  `source_voltage=0.0`, `source_current=0.0`, `sense_func='VOLT'`, `voltage_compliance=210.0`,
  `current_compliance=1.05`, `compliance_tripped=False`) while preserving the injected hook intact.
  Notifies hook of 0.0 stimulus / output disabled. Instance assignments to `sourcemeter.sample` or
  `sourcemeter.mag_sample` do not pollute global shared sample state.
- Driver reset does not reset setup-owned closures, external load/material models, clocks, or RNG seeds:
  that state is owned by the setup / fixture and must be reset there. A future VirtualBench will coordinate resets.

## Virtual driver family audit & Checkpoint 28 completion (checkpoint 28h)

The comprehensive audit of all virtual drivers in PIEC confirmed:
- All 7 driver families consuming shared virtual sample state (`sample` / `mag_sample`)
  or participating in Section 11.2 generic hooks are fully completed:
  1. `VirtualLockin` (28a): X/Y transport hook (`xy_reader`, `transport_hook`).
  2. `VirtualDMM` (28b): DC voltage reader hook (`voltage_reader`, `reader_hook`).
  3. `VirtualCalibrator` (28c): commanded field/output hook (`output_hook`, `field_hook`).
  4. `VirtualStepper` (28d): mechanical angle/motion hook (`angle_hook`, `position_hook`, `step_hook`).
  5. `VirtualScope` (28e): high-speed waveform hook (`waveform_hook`, `channel_hook`, `data_hook`).
  6. `VirtualAwg` (28f): high-speed excitation waveform hook (`waveform_hook`, `apply_hook`, `trigger_hook`).
  7. `VirtualSourcemeter` (28g): two-terminal electrical load hook (`load_hook`, `source_hook`, `measure_hook`, `transport_hook`).
- Remaining virtual drivers (`VirtualDaq`, `VirtualPulser`, `VirtualRFSource`) do not consume shared
  sample state (`sample`, `mag_sample`), require no material decoupling, and participate in no measurement families.
- DAQ-to-AWG and DAQ-to-Scope adapters (`DaqAsAwg`, `DaqAsOscilloscope`) expose no defects in their contract
  and trigger test suites.
- No remaining virtual-driver families require per-instance hook implementation. Checkpoint 28 is complete.
- Next milestone is Checkpoint 29: VirtualBench (multi-instrument wiring, reset isolation, deterministic time/noise).

## Contents

### Waveform hook review clarifications (28e/28f)

Scope timestamps are relative to a trigger: negative pre-trigger times are valid,
but duplicate/decreasing/non-finite timestamps are not. Voltage arrays must be
finite and one-dimensional. Labeled responses must explicitly identify time and
voltage (or the requested channel); the scope never guesses from column order.
Bundled scope configurations reject invalid settings without partial state changes.

AWG `seed=` selects per-instance waveform-noise randomness; reset replays that
driver-owned RNG sequence. Hook-owned model/RNG state is still reset by the setup.
Arbitrary waveforms apply amplitude, offset and polarity and require finite 1D
data. State snapshots detach arbitrary-waveform arrays. Trigger hooks receive the
synthesized waveform plus output metadata; they are not a physical shutdown
verification or a continuous-time circuit transport. Other waveform approximations
and historical fallback prep handling remain unchanged.

The core logic is implemented in `fe_material.py` and includes:

*   **`Material`**: Base class for all material simulations.
*   **`Resistor`**: Simulates an ideal ohmic resistor ($V = IR$).
*   **`Dielectric`**: Simulates an ideal linear dielectric material.
*   **`Ferroelectric`**: Implements a Landau-Devonshire model for ferroelectric materials, including:
    *   Hysteresis loop calculation.
    *   Temperature dependence ($T_0$).
    *   Strain effects from substrate mismatch.
    *   Parasitic effects (linear dielectric background and leakage/loss).

## Usage

Classes can be imported directly from the module. The primary method for interaction is typically `voltage_response` or `apply_waveform`.

### Example: Simulating a Resistor

```python
import numpy as np
from piec.simulation.fe_material import Resistor

# Create a resistor
r = Resistor(resistance=2000)

# Define a waveform
t = np.linspace(0, 1e-3, 1000)
v = np.sin(2 * np.pi * 1000 * t)

# Calculate response
i_response, t_out = r.voltage_response(v, t)
```

### Example: Simulating a Ferroelectric Capacitor

The `Ferroelectric` class requires a material property dictionary for initialization.

```python
from piec.simulation.fe_material import Ferroelectric

# Define material properties (or use defaults from virtual_instrument.py)
material_props = {
    'ferroelectric': {
        'a0': 8.248e5, 'b': -8.388e8, 'c': 7.764e9, 'T0': 388,
        'Q12': -0.034, 's11': 1.27e-11, 's12': -4.2e-12,
        'lattice_a': 4.02e-10, 'film_thickness': 10e-9,
        'epsilon_r': 400, 'leakage_resistance': 1e4
    },
    'substrate': {'lattice_a': 3.905e-10},
    'electrode': {'screening_lambda': 5e-11, 'permittivity_e': 8.0, 'area': 4e-10}
}

fe_sample = Ferroelectric(material_dict=material_props)
fe_sample.apply_waveform(v, t)
output_voltage, time = fe_sample.get_voltage_response()
```
