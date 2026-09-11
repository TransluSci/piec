# Ferroelectric (FE) Physical Validation Record (Checkpoint 22)

Physical validation: **PENDING**. The protocol template is complete; physical execution is not.

- Template prepared: 2026-09-11. Physical execution date and operator: **PENDING**.
- Software reference: commit on `measuremnt-standarization` (Checkpoint 21 / 22). Record the exact tested commit SHA when executing on hardware.
- Execution environment discovery: `pyvisa.ResourceManager().list_resources()` returned `()`. This records that no VISA instruments were discovered in this automated software environment; it does not prove instruments do not exist in the physical laboratory.

> [!IMPORTANT]
> **Automated and virtual tests do not prove physical safety.**  
> In accordance with Section 13 of `MEASUREMENT_STANDARDIZATION_PLAN.md`, virtual drivers and mock benches validate interfaces, schema adherence, thread synchronization, and numerical algorithms, but they do NOT substitute for physical hardware validation.  
> Checkpoint 22 remains explicitly marked **PENDING** until actual physical execution is conducted on laboratory hardware.

---

## 1. Bench Setup and Acceptance Criteria

Before physical execution, the operator must complete and sign these bench setup parameters. This document specifies no synthetic or universal pass criteria; acceptance limits must derive from instrument specifications, calibration uncertainty, and laboratory electrical safety guidelines.

| Required Record | Field / Setting | Status / Recorded Value |
|---|---|---|
| **Operator & Date** | Name, date, time of execution | PENDING |
| **Software Baseline** | Git commit SHA, branch, Python environment | PENDING |
| **AWG Model** | Model (Keysight 81150A / SDG2000X / Agilent 33220A/33500 / Rigol), serial, firmware | PENDING |
| **Oscilloscope Model**| Model (Keysight InfiniiVision / Tektronix), serial, firmware | PENDING |
| **HV Amplifier (if used)** | Model (Trek / PiezoDrive), gain, max output voltage/current, slew rate | PENDING |
| **Calibration Standard** | Linear capacitor (e.g. 10.0 nF ± 1% PPS) and precision shunt resistor (e.g. 50.0 Ω ± 0.1%) | PENDING |
| **FE Sample Details** | Material (PZT, BFO, HZO), top electrode area ($cm^2$), film thickness ($nm$) | PENDING |
| **Independent Monitoring** | High-voltage differential probe, calibrated DMM for DC offset | PENDING |
| **Voltage Limits** | Max amplitude ($V$), pulse width ($\mu s$), repetition frequency ($Hz$) | PENDING |
| **Safety Interlocks** | HV enclosure interlock, discharge stick, physical emergency stop | PENDING |
| **Manual Emergency Procedure**| Documented procedure to shut off AWG output and discharge sample | PENDING |

---

## 2. Staged Execution Protocol (Mandatory)

In accordance with Section 13 of `MEASUREMENT_STANDARDIZATION_PLAN.md`:  
**"FE begins at low amplitude into an explicitly known impedance."**

### Stage 1: Benign Known Impedance at Low Amplitude
*Goal: Validate instrument communications, strict trigger sequencing, WaveformReader acquisition, and attempt-all safing using a non-saturating linear capacitor standard before applying high fields or connecting ferroelectric samples.*

1. **Setup**: Connect AWG output Channel 1 to a linear reference capacitor ($C_{\text{ref}} \approx 10.0\text{ nF}$) in series with a precision non-inductive shunt resistor ($R_{\text{shunt}} = 50.0\text{ }\Omega$). Connect Scope Channel 1 across the total circuit (applied voltage $V$) and Channel 2 across the shunt resistor (proportional to current $I$).
2. **Low-Amplitude Sweep**: Set AWG peak amplitude to a benign low level ($V_{\text{peak}} \le 1.0\text{ V}$, frequency $1\text{ kHz}$).
3. **Trigger Sequencing Verification**:
   - Verify strict trigger order: scope is armed (`RUN` / `SINGLE`) $\to$ AWG output is enabled (`:OUTP ON`) $\to$ AWG trigger is fired.
   - Verify WaveformReader reads Channel 1 and Channel 2 data without format errors or channel crossing.
4. **Linear Dielectric Verification**:
   - Run in-memory hysteresis analysis (`process_hysteresis`).
   - Confirm linear dielectric ellipse/straight line with zero remanent polarization ($P_r \approx 0.00\text{ }\mu\text{C/cm}^2$) and zero coercive voltage ($V_c \approx 0.00\text{ V}$).
5. **Safing Verification**:
   - Verify that upon cycle completion, AWG output relay immediately disengages (`:OUTP OFF`).
   - Issue cooperative Stop mid-run; verify AWG output relay is disengaged immediately without lingering excitation.

### Stage 2: PUND Pulse-Sequence Verification on Linear Capacitor
*Goal: Validate Three-Pulse PUND timing, polarity, in-memory subtraction, and artifact staging on a benign linear load.*

1. **Setup**: Retain linear capacitor ($10\text{ nF}$) and shunt setup from Stage 1.
2. **Pulse Sequence**: Run ThreePulsePund with low voltage ($V \le 1.0\text{ V}$, pulse width $10\text{ }\mu\text{s}$, delay $100\text{ }\mu\text{s}$).
3. **Polarity Check**:
   - Verify nominal pulse polarities on scope match commanded AWG waveform.
   - Verify auto_timeshift aligns current peaks with pulse onset.
4. **Subtraction Accuracy**:
   - Run in-memory PUND processing (`process_pund`).
   - On a purely linear capacitor, switching pulse response ($\hat{P}$) and non-switching pulse response ($P^*$) must be identical within measurement noise.
   - Verify $\Delta P = \hat{P} - P^* \approx 0.00\text{ }\mu\text{C/cm}^2$.
5. **Artifact Staging**: Verify multi-artifact plot generation (`_dPvst.png`, `_trace.png`) without file-handle leaks.

### Stage 3: Reference Ferroelectric Capacitor Integration
*Goal: Execute standardized HysteresisLoop and ThreePulsePund on a known physical ferroelectric test capacitor.*

1. **Setup**: Connect reference ferroelectric sample (e.g. standard PZT test capacitor). Set established amplitude limits well below dielectric breakdown.
2. **Hysteresis Loop Execution**:
   - Run bipolar sweep through `FEMeasurementApp` GUI.
   - Verify in-memory plotting displays classic saturated P-V ferroelectric loop.
   - Verify extracted remanent polarization ($P_r$), saturation polarization ($P_s$), and coercive field ($E_c$) match reference sample datasheet.
   - Verify atomic publication of canonical schema `hysteresis` v1 CSV with units (`s`, `V`, `A`, `uC/cm^2`, `V`).
3. **PUND Execution**:
   - Run three-pulse PUND sequence.
   - Verify clean separation of switching displacement from non-switching background dielectric displacement ($\Delta P > 0$).
   - Verify atomic publication of canonical schema `three_pulse_pund` v1 CSV with all 10 standard columns and declared units.

### Stage 4: Fault Handling & Safety Shutdown
*Goal: Validate emergency stop, trigger timeout recovery, and UNSAFE state retention.*

1. **Trigger Timeout Injection**: Disconnect scope external trigger cable; trigger measurement.
2. **Safing Precedence**: Verify acquisition timeout propagates, attempt-all safing disengages AWG output, and primary timeout error is not masked.
3. **Shutdown Failure / UNSAFE Retention**: Inject communication fault during AWG shutdown. Verify GUI transitions to `SafetyStatus.UNSAFE`, retains open connections, disables run button, and blocks window destruction.

---

## 3. Physical Validation Checklist & Observation Log (PENDING)

The following checklist must be completed and signed by the test operator before Checkpoint 22 can transition from `PENDING` to `COMPLETED`:

| Item # | Verification Parameter | Target Specification | Observed Physical Result | Status |
|---|---|---|---|---|
| 1 | **Stage 1: Strict Trigger Sequencing** | Scope armed $\to$ AWG output enabled $\to$ trigger fired | *Pending bench execution* | PENDING |
| 2 | **Stage 1: WaveformReader Data Integrity** | Finite, non-empty arrays with declared units ('s', 'V') | *Pending bench execution* | PENDING |
| 3 | **Stage 1: AWG Output Safing on Completion** | AWG output relay opens (`:OUTP OFF`) immediately | *Pending bench execution* | PENDING |
| 4 | **Stage 1: Linear Capacitor Hysteresis** | $P_r \approx 0.00\text{ }\mu\text{C/cm}^2$, $V_c \approx 0.00\text{ V}$ on 10 nF standard | *Pending bench execution* | PENDING |
| 5 | **Stage 2: PUND Pulse Polarity and Timing** | Scope trace matches commanded amplitudes, widths, delays | *Pending bench execution* | PENDING |
| 6 | **Stage 2: Linear Capacitor PUND Subtraction** | $\Delta P = \hat{P} - P^* \approx 0.00\text{ }\mu\text{C/cm}^2$ within noise floor | *Pending bench execution* | PENDING |
| 7 | **Stage 2: Multi-Artifact Plot Staging** | `_dPvst.png` and `_trace.png` staged and saved cleanly | *Pending bench execution* | PENDING |
| 8 | **Stage 3: Ferroelectric Hysteresis Fidelity** | Well-formed P-V loop with expected $P_r$ and $V_c$ on sample | *Pending bench execution* | PENDING |
| 9 | **Stage 3: Ferroelectric PUND Fidelity** | Measurable switching polarization $\Delta P = P_{sw} - P_{nsw}$ | *Pending bench execution* | PENDING |
| 10 | **Stage 3: Schema v1 CSV Publication** | Atomic publish with plain columns and canonical metadata | *Pending bench execution* | PENDING |
| 11 | **Stage 4: Scope Trigger Timeout Safing** | Trigger timeout aborts run and disables AWG output | *Pending bench execution* | PENDING |
| 12 | **Stage 4: UNSAFE Connection Retention** | AWG shutdown failure retains handles, defers window close | *Pending bench execution* | PENDING |

---

## 4. Evidence and Next Action

- **Current Status**: **PENDING**
- **Automated / Headless Verification**:
  - Full repository test suite (Agg backend): **1621 passed, 1 skipped** in 62.07s on Python 3.13.2.
  - Focused FE/PUND suite (analysis, lifecycle, GUI): **207 passed** in 31.58s.
  - Headless GUI interaction audit suite (`tests/test_measurement_fe_gui.py`): **43 passed**.
- **Next Steps**:
  - Physical execution will be scheduled when physical bench instruments (AWG, oscilloscope, high-voltage amplifier) are cabled and verified.
  - Offline work continues per roadmap.
