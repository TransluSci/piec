# VirtualBench

`piec.simulation.VirtualBench` creates independent virtual setups. It owns named
models, instruments, connections, a deterministic clock and random streams.
It accepts model and driver classes, creates fresh instances, and copies model
configuration containers. It never installs a model in the shared virtual sample.

```python
from piec.simulation import VirtualBench, ResistorLoad
from piec.drivers.sourcemeter.virtual_sourcemeter import VirtualSourcemeter

bench = VirtualBench(seed=42)
source = bench.add_instrument("source", VirtualSourcemeter)
load = bench.add_model("load", ResistorLoad, resistance=100.0)
bench.connect_load("wire", "source", "load")
source.configure_voltage_source(voltage=10.0, current_compliance=0.02)
source.output(on=True)
assert source.get_voltage() == 2.0
assert source.get_current() == 0.02
bench.reset()
```

The load solves both terminal quantities under compliance. The source's configured
10 V remains distinct from its effective 2 V. Current-source mode uses the same
route, with voltage compliance. A load cannot be driven by two bench routes.

## Time, ownership and reset

- Use `bench.advance(seconds)` to advance time explicitly. Driver calls do not
  sleep or invent elapsed time. Do not advance owned model clocks separately.
  A capacitor requires positive elapsed time before its first evaluation and each
  subsequent integration step. Reads at the same time and operating point share
  the sourcemeter's cached evaluation.
- Source-off isolates terminal readback; it does not simulate a discharge circuit
  or the evolution of disconnected stored charge. Stateful load evaluation uses
  the interval since its last evaluation. Schedule intervals explicitly; this is
  not a continuous circuit solver.
- Model seeds, AWG noise seeds and named `bench.rng("name")` streams derive from
  the bench seed and object names. Unrelated stream creation does not alter a
  stream's sequence. Reset replays RNG state, including unseeded benches within
  the same bench instance. Supply a seed to reproduce a setup in another process.
- `bench.reset()` attempts all instrument resets, then model resets, resets the
  clock/RNGs and clears route buffers. Connections persist. Instrument settings
  return to driver factory defaults; configure the experiment again after reset.
  `BenchResetError.errors` retains component names and original exceptions if any
  operation failed. A failed reset is not a successful safety confirmation.
- Separate benches can run concurrently. Serialize operations within a single
  bench. The read-only inventories expose owned objects for configuration, not
  copies. Do not manually replace their hooks, reseed models, or share them across
  benches if relying on bench-managed routing and replay.
- Supported drivers are VirtualSourcemeter, VirtualDMM, VirtualAwg, VirtualScope,
  VirtualCalibrator, VirtualStepper and VirtualLockin. Material-consuming fallback
  properties are disabled per instance. The historical global fallback still
  exists outside these connections and is not retired by checkpoint 29.

## MOKE plant routing

```python
from piec.analysis.field_calibration import FieldCalibration
from piec.drivers.dmm.virtual_dmm import VirtualDMM
from piec.simulation import HystereticMagneticMaterial

optics = VirtualBench(seed=7)
source = optics.add_instrument("source", VirtualSourcemeter)
detector = optics.add_instrument("detector", VirtualDMM)
optics.add_model("electrical_load", ResistorLoad, resistance=1000.0)
optics.add_model("material", HystereticMagneticMaterial)
plant_calibration = FieldCalibration([(-5.0, -500.0), (5.0, 500.0)])
optics.connect_moke(
    "optics", "source", "electrical_load", "material", "detector",
    plant_calibration, optical_gain=0.02, optical_offset=0.5, noise_std=0.0,
)
field_reader = optics.field_reader("optics")  # scalar Oe, optional gaussmeter
```

The route applies the compliant terminal voltage or current through the copied
plant calibration and updates the material. Detector voltage is offset plus gain
times normalized magnetization, with optional Gaussian voltage noise. The field
reader reports the material's field without adding detector noise. Unconfirmed
source state propagates as an error to both readers.

Calibration must include zero output, match the source mode and use the material's
declared field unit (Oe for HystereticMagneticMaterial). No extra amplifier gain or
implicit unit conversion is applied. The measurement's calibration is supplied
separately to `MokeMeasurement`; bench wiring remains outside the measurement and
generic drivers. Physical calibration and hardware validation remain separate.

## Triggered waveform routing

`connect_waveform(name, awg, scope, source_channel=1, scope_channel=1)` connects
one AWG trigger hook to one scope reader. Configure the AWG acquisition channel
to select the connected source channel before triggering. The scope receives a
copied voltage/time snapshot with the AWG's amplitude, offset and polarity applied.
An output-off trigger records zeros on the same time grid. Reads before a trigger
or on an unconnected scope channel raise. Reset clears the stored snapshot.

This route models sampled direct transport. It does not resample to scope settings,
model hardware trigger delays, apply a ferroelectric material, or advance the bench
clock by the waveform duration. FE/AMR setup wiring and fixture migration remain
the later family-specific checkpoints; no scientific model is added to a driver.

Checkpoint 29 integration tests compare IV/MOKE columns and unit metadata against
hardware-interface doubles, not physical instruments. Physical validation records
for checkpoints 17, 22 and 26 remain PENDING.
