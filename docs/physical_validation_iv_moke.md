# IV and MOKE Physical Validation Record (Checkpoint 17)

Status: **PENDING**  
Date: 2026-09-10  
Repository Commit: `6b8cd9682a715acef7d37b551bc18dcc33914359` (branch `measuremnt-standarization`)  
Execution Environment: Headless/Automated CI environment (Windows 11, Python 3.13.2)  

> [!IMPORTANT]
> **Automated and virtual tests do not prove physical safety.**  
> In accordance with Section 13 of `MEASUREMENT_STANDARDIZATION_PLAN.md`, virtual benches and software mocks validate interface contracts, thread coordination, data schemas, and mathematical algorithms, but they do NOT substitute for physical hardware validation.  
> Physical instruments were not detected in this environment (`pyvisa.ResourceManager().list_resources()` returned `()`). Therefore, Checkpoint 17 remains explicitly marked **PENDING** until actual physical testing is conducted on laboratory hardware.

---

## 1. Physical Hardware Requirements and Specification

To satisfy Checkpoint 17, physical execution must be carried out on laboratory hardware meeting the specifications below, and this record must be updated with actual measured data, dates, and operator signatures.

### 1.1 IV Sweep Hardware Setup
- **Sourcemeter**: Keithley 2400 (or certified Keithley 2400-compatible SMU)
  - Asset / Serial Number: *PENDING*
  - Firmware Revision: *PENDING*
  - Interface: GPIB / RS-232 / USB-to-Serial
- **Calibration Load**:
  - Known benign resistive standard (e.g. 1.000 kΩ ± 0.1% metal-film resistor)
  - Verification diode / test device (e.g. 1N4148 silicon diode)
- **Monitoring Equipment**:
  - Calibrated 6.5-digit DMM or dual-channel digital storage oscilloscope (DSO) placed across output terminals to observe transitions independently.

### 1.2 MOKE Measurement Hardware Setup
- **Electromagnet Current/Voltage Source**:
  - Keithley 2400 or certified bipolar magnet power supply
  - Asset / Serial Number: *PENDING*
  - Firmware Revision: *PENDING*
- **Detector DMM**:
  - Agilent 34410A, Keithley 2000, or Keithley 193a
  - Asset / Serial Number: *PENDING*
  - Firmware Revision: *PENDING*
- **Field Reader (Optional / Measured-field mode)**:
  - Calibrated digital Gaussmeter with analog or digital readback
  - Asset / Serial Number: *PENDING*
- **Optical Bench & Magnet System**:
  - Laser diode source, polarizer, analyzer, photodiode detector
  - Electromagnet coil with known calibration curve (`example_calibration.csv` or bench-specific calibration)
  - Physical thermal interlock on coil and amplifier heat sink

---

## 2. Staged Validation Protocol (Mandatory)

Per Section 13 of the standardization plan, MOKE hardware validation must be staged to prevent hardware damage from uncontrolled field/current transitions:

### Stage 1: Benign Electrical Dummy Load (Source + DMM + Oscilloscope)
- **Procedure**:
  1. Terminate the sourcemeter into a benign resistive load (e.g. 100 Ω, 10 W power resistor or 1 kΩ load) rather than the electromagnet coil.
  2. Connect the DMM input across the load (or a separate sense resistor) to simulate the detector.
  3. Monitor the source output on an independent oscilloscope.
  4. Run a multi-cycle MOKE sweep with `output_min = -2.0 V`, `output_max = 2.0 V`, `max_output_step = 0.1 V`, `ramp_delay = 0.05 s`.
- **Validation Criteria**:
  - Smooth, monotonic voltage transitions without voltage spikes or inductive ringing.
  - Zero-ramp returns output voltage to 0.000 V (within ±1 mV) upon completion.
  - Pressing **STOP** triggers an immediate abort, halts forward steps, ramps output to 0 V, and opens the output relay (`:OUTP OFF`).
  - Window close request (`WM_DELETE_WINDOW`) defers closure until the worker terminates and safing is confirmed `SAFE`.

### Stage 2: Magnet and Bipolar Amplifier Integration
- **Procedure**:
  1. Verify physical interlocks: over-temperature cutoff and maximum current limit.
  2. Connect source to bipolar amplifier / magnet coil.
  3. Place a calibrated Hall probe in the pole gap.
  4. Run calibrated-field sweep and measured-field sweep.
- **Validation Criteria**:
  - Commanded field matches Hall probe readback across the full sweep range within calibration tolerance.
  - Paced ramping respects coil inductance limits without tripping amplifier fault protection.
  - Deliberate simulated fault (e.g. disconnecting DMM cable or tripping interlock) engages attempt-all safing, disables source output, retains connections for inspection, and alerts the operator.

### Stage 3: Full Optical Bench Integration
- **Procedure**:
  1. Energize laser, optical path, and photodiode detector.
  2. Mount a standard reference magnetic thin film (e.g. 20 nm NiFe or CoFeB).
  3. Execute in-plane and out-of-plane loops through the MOKE GUI.
- **Validation Criteria**:
  - Expected hysteresis loop shape, coercive field, and Kerr rotation observed.
  - Live GUI display shows real-time raw points, last completed cycle, and cycle average without UI freezing.
  - Final CSV publication succeeds with standard 1-row metadata, valid units, and no file collisions.

---

## 3. Physical Validation Checklist & Observation Log (PENDING)

The following checklist must be completed and signed by the test operator before Checkpoint 17 can transition from `PENDING` to `COMPLETED`:

| Item # | Verification Parameter | Target Specification | Observed Physical Result | Status |
|---|---|---|---|---|
| 1 | **IV Output Voltage Accuracy** | Commanded vs. DMM readback within ±0.1% + 1 mV across ±5 V | *Pending bench execution* | PENDING |
| 2 | **IV Current Compliance Limit** | Current clamp activates within ±1% of compliance setpoint (e.g. 10 mA) | *Pending bench execution* | PENDING |
| 3 | **IV Stop Button Latency** | Output voltage reaches 0 V and `:OUTP OFF` within < 500 ms of Stop click | *Pending bench execution* | PENDING |
| 4 | **IV Window Close Coordination** | Window close during active sweep waits for zero-ramp and worker exit | *Pending bench execution* | PENDING |
| 5 | **IV Transport Fault Safing** | Cable disconnect mid-sweep transitions to `FAILED`, flags `UNSAFE`, alerts user | *Pending bench execution* | PENDING |
| 6 | **MOKE Stage 1 Waveform Quality** | Oscilloscope verifies smooth paced ramping without overshoot on dummy load | *Pending bench execution* | PENDING |
| 7 | **MOKE Stage 1 Residual Output** | Final output voltage <= 1 mV, output relay open (`:OUTP OFF`) | *Pending bench execution* | PENDING |
| 8 | **MOKE Stage 2 Field Accuracy** | Calibrated field vs. Hall probe readback within ±2% of full scale | *Pending bench execution* | PENDING |
| 9 | **MOKE Stage 2 Emergency Cutoff** | Manual emergency cutoff immediately de-energizes coil without software lockup | *Pending bench execution* | PENDING |
| 10 | **MOKE Stage 3 Loop Fidelity** | Standard reference sample reproduces expected hysteresis parameters | *Pending bench execution* | PENDING |
| 11 | **MOKE Multi-cycle Averaging** | Published CSV cycle average matches processed raw data | *Pending bench execution* | PENDING |
| 12 | **Staging Path Recovery** | Deliberate filesystem write-protect retains uncorrupted raw staging file | *Pending bench execution* | PENDING |

---

## 4. Sign-Off & Status Summary

- **Current Status**: **PENDING**
- **Automated / Headless Test Results**:
  - Full repository test suite (Agg backend): **1249 passed, 1 skipped, 2 xfailed** in 26.53s on Python 3.13.2.
  - All unit, GUI, runner, session, persistence, and mathematical simulation tests are fully passing.
- **Next Steps**:
  - Physical execution will be scheduled on available laboratory hardware.
  - As permitted by Section 1 ("Hardware checkpoints are independent manual release gates, not a reason to stop offline work on other families"), offline work proceeds to **Checkpoint 18** (In-memory hysteresis processing).
