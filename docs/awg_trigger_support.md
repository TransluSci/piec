# AWG trigger command support

This describes Python command implementations, not completed physical validation.
The driver command tests use fake transports. Physical validation remains PENDING.

## Implemented mappings

| Driver / model | Source and external edge | EDGE / LEV | Software initiation |
|---|---|---|---|
| Agilent33220A | `TRIG:SOUR IMM/EXT/BUS`, `TRIG:SLOP POS/NEG` | `BURS:MODE TRIG/GAT` | `*TRG` |
| Agilent33500 | `TRIG<n>:SOUR IMM/EXT/BUS`, `TRIG<n>:SLOP POS/NEG` | `SOUR<n>:BURS:MODE TRIG/GAT` | `*TRG` |
| RigolDG1000, DG1000Z dialect | `TRIG<n>:SOUR INT/EXT/BUS`, `TRIG<n>:SLOP POS/NEG` | `SOUR<n>:BURS:MODE TRIG/GAT` | `*TRG` |
| RigolDG1000, legacy dialect | `TRIG:SOUR IMM/EXT/BUS`, `TRIG:SLOP POS/NEG`; channel 1 only | `BURS:MODE TRIG/GAT`; channel 1 only | Unverified; raises `NotImplementedError` |
| RigolDG4000 | `SOUR<n>:BURS:TRIG:SOUR INT/EXT/MAN`, `SOUR<n>:BURS:TRIG:SLOP POS/NEG`; use `SWE` for sweep | `SOUR<n>:BURS:MODE TRIG/GAT` | `*TRG` |

`MAN` and `BUS` API inputs both select the model's remote software source.
`INT` and `IMM` both select its internal/immediate source. Inputs are case-insensitive.
`EDGE` / `LEV` mean triggered / externally gated **burst**, not oscilloscope modes.
The external edge setter does not set gate polarity.

These methods configure an already prepared burst/sweep. They do not select a
waveform, enable burst/sweep, change output enable, reset the instrument, or enable
a physical trigger-output connector. `output_trigger()` sends one device-wide
bus trigger to the channels already armed for it; it does not promise channel
isolation or synchronization across separate instruments. The experiment must
enable the intended output channels and burst/sweep and apply its own shutdown.

For DG4000, pass `trigger_function="sweep"` to `configure_trigger`,
`set_trigger_source`, or `set_trigger_slope` for sweep settings. The default is
`"burst"`. Passing `trigger_mode` together with sweep is rejected.
Other models share the source/edge subsystem between burst and sweep.

On 33500, `set_trigger_level` writes `TRIG<n>:LEV` with a finite value from
0.9 to 3.8 V. This is the **programmed output trigger level**; the manufacturer
specifies an external input threshold of half that value. It is not a direct
input-threshold parameter. On the other newly implemented drivers, no adjustable
external trigger-level command is established here: requesting one raises
`NotImplementedError`. Counter trigger thresholds are unrelated and are not used.
The class's channel list still needs to match the connected model (33500 models
can have one or two channels); model-specific frequency/output limits are not
comprehensively validated by this trigger change.

`None` in `configure_trigger` leaves a setting alone. Validation rejects unknown
sources, modes, functions and channels before any configuration writes. Transport
errors propagate; successful earlier writes are not rolled back after an I/O
failure. Software validation does not replace instrument error-queue checks.

## Rigol dialect selection and related corrections

`RigolDG1000` selects a dialect from a read-only `*IDN?` query on its first
operation and caches it. Known legacy model IDs are DG1012, DG1022, DG1022A and
DG1022U; `DG1xxxZ` selects the Z dialect. An unknown ID raises instead of guessing.
Callers with a verified setup can pass `protocol="dg1000"` or `"dg1000z"` to the
constructor to avoid the query. An explicit protocol must match the connected model.

The older models use unprefixed channel-1 commands and `:CH2` suffixes for channel
2. Z models use `SOUR<n>` / `OUTP<n>`. The existing driver always used Z-style
commands; output, frequency, amplitude, offset, phase, waveform and pulse command
routing now respects the selected dialect. Legacy pulse-transition commands were
not documented in the reviewed reference and now raise instead of sending guessed
Z commands. Z rise/fall setters change only the requested edge; the combined
setter uses `TRAN:BOTH`.

The older DG1000 reference lists only `*IDN?` in its IEEE 488.2 command section.
It documents BUS source selection but does not establish a remote trigger launch
command. Consequently, legacy `output_trigger()` is explicitly unverified; use
external or front-panel triggering until a model/firmware-specific command is
documented and tested. This is not a claim that the hardware lacks manual triggering.

On 33500, the common `USER` waveform now maps to its documented `ARB` token,
and `set_pulse_edge_time` sets both leading and trailing transitions instead of
only the default leading edge.

The DAQ adapter's operating code is unchanged. The generic DAQ contract has no
trigger-arming/firing interface to delegate to; adding external synchronization
requires a specific DAQ backend and timing contract. Existing Keysight81150a and
SDG2000X trigger implementations are retained. Their mock command tests are not
a new full hardware/protocol certification.

## Manufacturer references

- [Agilent 33220A User's Guide, edition 4](https://www.keysight.com/no/en/assets/9018-04437/user-manuals/9018-04437.pdf): burst and trigger commands, printed pages 225–233.
- [Keysight Trueform Operating and Service Guide](https://www.batronix.com/files/Keysight/Funktionsgeneratoren/33500B%2633600A/33500-33600-Manual.pdf): manufacturer-authored manual mirrored by Batronix; trigger commands, pages 400–403, plus FUNCtion and BURSt reference sections.
- [Rigol DG1000 Programming Guide](https://beyondmeasure.rigoltech.com/acton/attachment/1579/f-0038/1/-/-/-/-/file.pdf): IEEE 488.2 section 2-2, channel commands, trigger section 2-46 and burst section 2-49.
- [Rigol DG1000Z Programming Guide](https://beyondmeasure.rigoltech.com/acton/attachment/1579/f-0493/1/-/-/-/-/DG1000Z%20Programming%20Guide.pdf): `*TRG`, `:TRIGger`, `:SOURce:BURSt`, and pulse transition sections.
- [Rigol DG4000 Programming Guide](https://beyondmeasure.rigoltech.com/acton/attachment/1579/f-00b8/1/-/-/-/-/file.zip): official ZIP containing a CHM reference; `*TRG`, SOURce BURSt/SWEep TRIGger, and BURSt MODE entries. These Rigol links are published on the [manufacturer's download page](https://www.rigolna.com/support/downloads/).

Tests: `tests/test_awg_trigger_commands.py` and `tests/test_awg_contract.py`.
Further waveform upload, model-limit and physical synchronization audits should
land separately, with their own numerical/command tests and hardware records.
