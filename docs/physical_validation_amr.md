# AMR Physical Validation Record (Checkpoint 26)

Physical validation: **PENDING**. The protocol template is complete; physical execution is not.

- Template prepared: 2026-09-11. Physical execution date and operator: **PENDING**.
- Software reference: commit on `measuremnt-standarization` (Checkpoint 25 / 26). Record the exact tested commit SHA when executing on hardware.
- Execution environment discovery: `pyvisa.ResourceManager().list_resources()` returned `()`. This records that no VISA instruments were discovered in this automated software environment; it does not prove instruments do not exist in the physical laboratory.

> [!IMPORTANT]
> **Automated and virtual tests do not prove physical safety.**  
> In accordance with Section 13 of `MEASUREMENT_STANDARDIZATION_PLAN.md`, virtual drivers and mock benches validate interfaces, schema adherence, thread synchronization, and numerical algorithms, but they do NOT substitute for physical hardware validation.  
> Checkpoint 26 remains explicitly marked **PENDING** until actual physical execution is conducted on laboratory hardware.

---

## 1. Bench Setup and Acceptance Criteria

Before physical execution, the operator must complete and sign these bench setup parameters. This document specifies no synthetic or universal pass criteria; acceptance limits must derive from instrument specifications, sensor calibrations, and laboratory safety standards.

| Required Record | Field / Setting | Status / Recorded Value |
|---|---|---|
| **Operator & Date** | Name, date, time of execution | PENDING |
| **Software Baseline** | Git commit SHA, branch, Python environment | PENDING |
| **Field Source** | Model, serial/asset ID, firmware, interface (GPIB/RS-232/USB) | PENDING |
| **Field Readback** | DMM / Gaussmeter model, serial/asset ID, firmware, probe type | PENDING |
| **Transport Readout** | Lock-in model (SR830 / 7265), serial/asset ID, firmware | PENDING |
| **Orientation Controller** | Stepper motor controller (Geos_Stepper / Arduino), serial ID, motor specs | PENDING |
| **Sample & Geometry** | Thin-film material, stripe dimensions, contact layout, stage geometry | PENDING |
| **Field Calibration** | V-to-Field factor (Oe/V) or calibration curve, linear range, polarity | PENDING |
| **Motion Limits** | Angular range (min/max deg), max step rate, gear ratio (steps/deg) | PENDING |
| **Excitation Policy** | Internal oscillator vs. external source; declared physical shutdown procedure | PENDING |
| **Safety Interlocks** | Coil over-temperature switch, stage limit switches, manual E-stop button | PENDING |
| **Manual Emergency Procedure**| Documented procedure to safely de-energize coil and isolate sample | PENDING |

---

## 2. Staged Execution Protocol (Mandatory)

In accordance with Section 13 of `MEASUREMENT_STANDARDIZATION_PLAN.md`:  
**"AMR validates motion and field roles independently before combining them."**

### Stage 1: Motion Role Validation (Orientation Controller Alone)
*Goal: Verify angular accuracy, step scaling, directional consistency, emergency stopping, and repair of defect AMR-ANGLE-001 without energizing magnetic field or sample excitation.*

1. **Setup**: Connect only the stepper motor / orientation controller to the bench. Do not connect magnet power supply or lock-in excitation.
2. **Angle Conversion**: Verify `steps_per_degree` matches the physical gear reduction of the goniometer/rotation stage.
3. **Forward Sweep ($0^\circ \to 180^\circ$, step $10^\circ$)**:
   - Verify stage advances incrementally by commanded step size.
   - Verify motor halts immediately after reaching final angle ($180.0^\circ$).
   - **AMR-ANGLE-001 Verification**: Confirm zero extra post-measurement motor steps occur. Stage position must remain strictly at the commanded endpoint.
4. **Reverse Sweep ($180^\circ \to 0^\circ$, step $-10^\circ$)**:
   - Verify directional handling and endpoint arrival at $0.0^\circ$.
5. **Stop Latency**: Issue cooperative `Stop` command mid-sweep; measure latency from command to motor deceleration and halt.
6. **Disconnection / Timeout Fault**: Disconnect serial communication cable during motor motion; verify driver raises communication error cleanly without infinite UI hang.

### Stage 2: Field Role Validation (Field Source + Field Readback Alone)
*Goal: Verify voltage-to-field calibration, zero and negative field handling, and attempt-all de-energization safing without sample excitation or stage movement.*

1. **Setup**: Connect magnet power supply (calibrator) and field readback sensor (calibrated DMM reading Hall probe or digital gaussmeter) centered in magnet pole gap.
2. **Calibration Check**:
   - Apply test voltages corresponding to calibrated field points (e.g. 0 Oe, 50 Oe, 100 Oe, 500 Oe).
   - Verify `AMR-FIELD-001` repair: default calibration of $10000\text{ Oe/V}$ produces $0.01\text{ V}$ for $100\text{ Oe}$.
   - Verify field readback matches commanded field within calibrated tolerance ($|H_{\text{read}} - H_{\text{target}}| \le \text{tol}_{\text{abs}} + \text{tol}_{\text{rel}} |H_{\text{target}}|$).
3. **Bipolar / Negative Field Sweep**:
   - Sweep field from $-500\text{ Oe} \to +500\text{ Oe} \to 0\text{ Oe}$.
   - Verify polarity transitions are smooth and hysteresis in magnet core is documented.
4. **Safing & Residual Field**:
   - Trigger cooperative Stop and completed run shutdown.
   - Verify field source returns to 0.000 V command.
   - Measure residual field with independent Gaussmeter probe; verify residual field is within laboratory safety threshold.

### Stage 3: Transport Readout & Excitation Safing Role Validation (Lock-In Alone)
*Goal: Verify manual lock-in settings preservation, declared physical excitation shutdown, and connection retention under unsafe conditions.*

1. **Setup**: Connect lock-in amplifier to a known benign reference resistor (e.g. 1.000 kΩ metal film) on the test bench.
2. **Settings Preservation**:
   - Manually set sensitivity, time constant, and frequency on the lock-in front panel.
   - Run a test measurement with `initialize_lockin=False` (`readout_configuration="preserve"`).
   - Verify front-panel settings remain completely unmodified; zero configuration commands sent to lock-in.
3. **Excitation Shutdown Policy**:
   - Provide an explicit physical excitation shutdown handler (e.g. reducing oscillator amplitude to 0.000 V or switching off external source).
   - Verify that upon experiment completion, the excitation amplitude is physically verified as 0.000 V.
4. **Fault Injection & UNSAFE Retention**:
   - Inject a deliberate fault into the excitation shutdown handler (e.g. disconnecting lock-in communication prior to shutdown).
   - Verify system transitions to `SafetyStatus.UNSAFE`.
   - Verify GUI retains all open instrument connections in `self._instruments` for manual bench inspection.
   - Verify GUI run button is locked (`state='disabled'`) and window closing is prevented until connections are safely cleared.

### Stage 4: Integrated Low-Field AMR Measurement (Combined Roles)
*Goal: Execute full multi-instrument AMR measurement on a reference sample and verify data integrity.*

1. **Setup**: Mount reference AMR thin-film sample (e.g. 20 nm NiFe stripe) on rotation stage in electromagnet pole gap. Connect 4-terminal lock-in leads.
2. **Measurement**: Run a $0^\circ \to 180^\circ$ rotation sweep with $H = 100\text{ Oe}$, $5^\circ$ step.
3. **Presentation & Persistence**:
   - Verify bounded `raw_window` live display updates smoothly without UI lag.
   - Verify authoritative final terminal plot reflects complete dataset.
   - Verify atomic publication of canonical CSV under schema `amr` v1 with metadata units (`{'angle': 'deg', 'field': 'Oe', 'x': 'V', 'y': 'V'}`).
   - Verify characteristic $\Delta R / R \propto \cos^2(\theta)$ anisotropic response.

---

## 3. Physical Validation Checklist & Observation Log (PENDING)

The following checklist must be completed and signed by the test operator before Checkpoint 26 can transition from `PENDING` to `COMPLETED`:

| Item # | Verification Parameter | Target Specification | Observed Physical Result | Status |
|---|---|---|---|---|
| 1 | **Stage 1: Stepper Endpoint Accuracy (AMR-ANGLE-001)** | Motor halts at final commanded angle with 0 extra steps | *Pending bench execution* | PENDING |
| 2 | **Stage 1: Stepper Stop Latency** | Deceleration and full halt within < 500 ms of Stop click | *Pending bench execution* | PENDING |
| 3 | **Stage 1: Stepper Disconnect Resilience** | Disconnect mid-rotation raises error without software lockup | *Pending bench execution* | PENDING |
| 4 | **Stage 2: Field Calibration Accuracy (AMR-FIELD-001)** | Calibrated field vs. Hall readback within bench tolerance | *Pending bench execution* | PENDING |
| 5 | **Stage 2: Bipolar Zero-Crossing** | Smooth transition through 0 Oe across negative fields | *Pending bench execution* | PENDING |
| 6 | **Stage 2: Field Safing Residual Field** | Source commanded to 0 V; residual field <= bench limit | *Pending bench execution* | PENDING |
| 7 | **Stage 3: Manual Lock-In Settings Preservation** | Front-panel sensitivity/time constant unchanged by run | *Pending bench execution* | PENDING |
| 8 | **Stage 3: Physical Excitation Shutdown** | Excitation amplitude physically drops to 0.000 V on safe exit | *Pending bench execution* | PENDING |
| 9 | **Stage 3: UNSAFE Connection Retention** | Shutdown failure retains handles, locks Run, defers window close | *Pending bench execution* | PENDING |
| 10 | **Stage 4: Integrated Angle Sweep Fidelity** | $\cos^2(\theta)$ AMR curve observed on standard Permalloy film | *Pending bench execution* | PENDING |
| 11 | **Stage 4: Schema v1 CSV Publication** | Atomic publish with plain columns and declared units | *Pending bench execution* | PENDING |
| 12 | **Stage 4: Emergency Stop Interlock** | Manual E-stop cutoff halts motion and de-energizes coil safely | *Pending bench execution* | PENDING |

---

## 4. Evidence and Next Action

- **Current Status**: **PENDING**
- **Automated / Headless Verification**:
  - Full repository test suite (Agg backend): **1621 passed, 1 skipped** in 62.07s on Python 3.13.2.
  - Focused AMR/Magneto suite (8 files, 215 tests): **215 passed** in 34.69s.
  - Headless GUI interaction audit suite (`tests/test_measurement_amr_gui.py`): **35 passed** in 26.91s.
- **Next Steps**:
  - Physical execution will be scheduled when physical bench instruments (stepper, electromagnet, lock-in) are physically cabled and operational.
  - Offline work proceeds per roadmap to **Checkpoint 24d onward** (additional AMR electrical adapters) or **Checkpoint 27** (role-specific simulation contracts).
