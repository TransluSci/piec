# IV and MOKE Physical Validation Record (Checkpoint 17)

Physical validation: **PENDING**. The template is complete; physical execution is not.

- Template prepared: 2026-09-10. Physical execution date and operator: **PENDING**.
- Software reference: `6b8cd9682a715acef7d37b551bc18dcc33914359` on `measuremnt-standarization`. Record the exact tested commit when executing.
- Gemini reported that `pyvisa.ResourceManager().list_resources()` returned `()`. This describes that discovery result; it does not prove no instruments exist or that every interface was searched.

Automated and virtual tests do not prove physical safety. Section 13 of `MEASUREMENT_STANDARDIZATION_PLAN.md` requires actual dated execution.

## 1. Bench setup and acceptance criteria

The operator must complete these fields before execution. This template supplies no universal numerical tolerances or instrument certification.

| Required record | Value |
|---|---|
| Operator, execution date, repository commit and driver versions | PENDING |
| Source, detector, optional field reader: model, serial/asset ID, firmware, address and supported driver/adapter | PENDING |
| Independent monitoring equipment and measurement uncertainty | PENDING |
| Wiring, source channel, load ratings and geometry | PENDING |
| Source mode, range, compliance, ramp step/delay, dwell and transport timeouts | PENDING |
| Amplifier/magnet ratings, established limits and interlock | PENDING |
| Manual emergency procedure and approved fault-injection method | PENDING |
| Calibration identity, measured points, units, valid range and geometry | PENDING |
| Acceptance limits and their basis in specifications, calibration uncertainty and bench requirements | PENDING |

Physical field validation requires a measured calibration for the actual source/amplifier/magnet setup and geometry. `Measurements/MOKE/example_calibration.csv` is explicitly illustrative and is **not a hardware calibration**. Any synthetic mapping used for dummy-load software checks must be identified as such and cannot support a field-accuracy claim.

Confirm support in the chosen driver/adapter. The current MOKE GUI uses a separate DMM and voltage-to-field conversion for physical measured-field input; a generic digital gaussmeter is not automatically interchangeable with that path.

## 2. Staged execution

Complete the benign electrical stage before amplifier/magnet testing, as required by Section 13. All setup values and numerical acceptance limits remain PENDING until established for the bench.

1. **IV/MOKE benign electrical load:** use a known, suitably rated load, source and detector with independent output monitoring (oscilloscope for MOKE transitions). Record commanded versus observed outputs, compliance, ramp transitions, completion, Stop and window-close behavior.
2. **MOKE amplifier/magnet:** use established limits, interlock and manual emergency procedure. Record calibrated and measured-field results using the actual calibration and independent field observations. Record final source output, output-enable state and residual field separately.
3. **MOKE optical bench:** record sample, geometry, detector settings and expected reference response. Verify raw, last-cycle and average displays, responsiveness and published data. Detector voltage alone does not establish calibrated Kerr rotation.

Stop requests cooperative cancellation. Record time to stop acquisition, complete shutdown and release connections separately. Shutdown timing depends on configured ramp settings, in-flight instrument calls and timeouts; there is no universal 500 ms requirement or immediate-abort guarantee. Independently observe physical output: an output-disable command alone does not prove relay position or zero residual field.

## 3. Fault behavior and observation log

Use the bench-approved fault-injection method, beginning on a benign load. Record the fault, primary error, each shutdown attempt, `RunState`, `SafetyStatus`, physical output and connection ownership.

- A detector/read failure can produce `FAILED` with successful `SAFE` shutdown. GUI-owned connections may then be released after worker exit.
- Required shutdown action failures produce `UNSAFE`: retain connections for recovery and defer normal window closing. Output disable is attempted; delivery cannot be guaranteed through a failed source transport.
- A physical interlock is not automatically a software error source. Record its detection path, if any, and actual hardware/software observations.
- Stop before instrument I/O can produce `ABORTED` with `NOT_NEEDED` safety.

| Check | Acceptance criterion | Evidence / result | Status |
|---|---|---|---|
| IV readback and compliance | Operator-defined limits and documented basis | PENDING | PENDING |
| IV/MOKE Stop and window-close timing | Bench-specific budget; worker-exit and safety gates respected | PENDING | PENDING |
| MOKE ramp transitions and residual electrical output | Bench-specific transient and residual-output limits | PENDING | PENDING |
| Output-enable state and residual field | Independent observations against bench-specific limits | PENDING | PENDING |
| Calibrated versus measured field | Actual calibration range and uncertainty-based tolerance | PENDING | PENDING |
| Acquisition failure with successful shutdown | Error reported; connections releasable after worker exit and SAFE | PENDING | PENDING |
| Shutdown failure / source transport failure | UNSAFE reported; connections retained; recovery recorded | PENDING | PENDING |
| Interlock / manual emergency procedure | Bench-defined physical behavior and software observations | PENDING | PENDING |
| Optical response, geometry and averages | Reference response and agreement with raw-data processing | PENDING | PENDING |
| CSV publication and recovery | Standard schema; actual failure stage and remaining files recorded | PENDING | PENDING |

Recovery checks must distinguish publication failure after staging from inability to create/write staging. A write-protected destination does not by itself guarantee a complete recoverable file. Verify the files that actually remain.

## 4. Evidence and next action

- Historical software validation at `6b8cd96`: **1249 passed, 1 skipped, 2 xfailed** in 26.53s with Matplotlib Agg. This is not a new test run or physical validation.
- Physical traces, files, anomalies, pass/fail decisions and operator sign-off: **PENDING**.
- Keep checkpoint 17 PENDING until actual execution and its record are complete. This template does not authorize hardware operation or advance implementation.
- Stop at this handoff; do not start checkpoint 18 until requested by the user. The plan allows later offline work while physical validation remains pending.
