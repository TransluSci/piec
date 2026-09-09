# DMM Voltage Configuration and Reading Audit

## 1. Overview and Scope

This audit fulfills the requirements of **Section 9.2** and **Checkpoint 6** of `MEASUREMENT_STANDARDIZATION_PLAN.md` prior to the MOKE and AMR vertical slices:

> Before the MOKE slice, contract-test voltage configuration and reading across every advertised DMM intended for that setup: sense-function selection, DC coupling, optional range/integration settings, `get_voltage()`, and finite/non-finite return handling. Unsupported optional configuration is capability-gated explicitly; it is not inferred by catching arbitrary driver errors. `VirtualDMM` must obey the same call and scalar-return contract.

The four advertised DMM drivers in the repository are:
1. `VirtualDMM` (`piec.drivers.dmm.virtual_dmm.VirtualDMM`)
2. `Agilent34410A` (`piec.drivers.dmm.agilent_34410a.Agilent34410A`)
3. `Keithley2000` (`piec.drivers.dmm.keithley_2000.Keithley2000`)
4. `Keithley193a` (`piec.drivers.dmm.keithley193a.Keithley193a`)

---

## 2. Manufacturer References and Hardware Specifications

Hardware-level command claims in this audit are grounded in official manufacturer programming and user documentation:

1. **Agilent 34410A / 34411A 6½ Digit Multimeter**:
   - *User's Guide*, Agilent Technologies, Publication Number 34410-90001, Edition 4, June 2008.
   - **Command Interface**: IEEE 488.2 / SCPI-1999 standard.
   - **Function commands**: `CONF:VOLT:DC`, `CONF:VOLT:AC`, `CONF:CURR:DC`, `CONF:CURR:AC`, `CONF:RES`, `CONF:FRES`, `CONF:FREQ`, `CONF:PER`, `CONF:CAP` (Chapters 3 and 4).
   - **Range configuration**: `[SENSe:]VOLTage:DC:RANGe:AUTO {OFF|ON}` and `[SENSe:]VOLTage:DC:RANGe <range>` (p. 88).
   - **Integration time**: `[SENSe:]VOLTage:DC:NPLC {0.006|0.02|0.06|0.2|1|2|10|100}` (p. 91). Valid only for DCV, DCI, and resistance functions; AC functions use bandwidth filtering (`DET:BAND`), and frequency uses aperture (`FREQ:APER`).
   - **Overload indication**: Over-range / overflow returns `+9.90000000E+37` (or `-9.90000000E+37` for negative overflow) (p. 48).

2. **Keithley Model 2000 6½-Digit Multimeter**:
   - *User's Manual*, Keithley Instruments, Document Number 2000-900-01 Rev. J, August 2010.
   - **Command Interface**: IEEE 488.2 / SCPI-1991 standard.
   - **Function commands**: `:SENSe:FUNCtion '<function>'` where function strings are `'VOLTage:DC'`, `'VOLTage:AC'`, `'CURRent:DC'`, `'CURRent:AC'`, `'RESistance'`, `'FRESistance'`, `'FREQuency'`, `'PERiod'`, `'TEMPerature'` (Section 3, Section 5).
   - **Range configuration**: `:SENSe:<function>:RANGe:AUTO <bep>` and `:SENSe:<function>:RANGe <n>` (Section 5, p. 5-14).
   - **Integration time**: `:SENSe:<function>:NPLC <n>` (Section 5, p. 5-16). Valid for DCV, DCI, RES, FRES, and TEMP; AC functions do not support NPLC.
   - **Overload indication**: Over-range / overflow returns `+9.99999900E+37` (or `-9.99999900E+37` for negative overflow) (Section 3, p. 3-19).

3. **Keithley Model 193A System DMM**:
   - *Instruction Manual*, Keithley Instruments, Document Number 193A-901-01 Rev. B, June 1986.
   - **Command Interface**: Device-Dependent Commands (DDC) with `X` execution terminator (not SCPI; sending SCPI commands causes IDDC errors).
   - **Function commands**: `F0` (DCV), `F1` (ACV), `F2` (2-Wire Ohms), `F3` (DCA with Model 1930/1931 option), `F4` (ACA with Model 1930/1931 option), `F6` (Temperature °C via RTD) (Section 3, p. 3-8).
   - **Range configuration**: `R0` (Autorange); manual ranges `R1`–`R7` require range mapping and are not implemented in the current driver.
   - **Integration rate**: `S0` (318 µs, 3½ digits), `S1` (2.59 ms, 4½ digits), `S2` (Line cycle, 5½ digits), `S3` (Line cycle, 6½ digits) (Section 3, p. 3-9).
   - **4-Wire Sensing**: 4-terminal ohms sensing is automatic when external sense leads are physically connected to the OHMS SENSE HI/LO terminals; there is no software command to toggle 2W vs 4W.
   - **Overload indication**: Over-range is indicated by the prefix `OVOL`, `OCUR`, or `OOHM` followed by `+999.9999E+30` (or `-999.9999E+30`) (Section 3, p. 3-10).

> [!NOTE]
> Mock assertions in `tests/test_dmm_contract.py` verify that the Python drivers correctly emit these documented commands to the transport layer and correctly parse responses. They do not constitute physical hardware validation, which remains tracked under Section 13.

---

## 3. Capability Matrix and Audit Inventory

| Capability / Method | `VirtualDMM` | `Agilent34410A` | `Keithley2000` | `Keithley193a` |
|---|---|---|---|---|
| **Protocol** | Virtual in-memory | SCPI (IEEE 488.2) | SCPI (IEEE 488.2) | DDC (Device-Dependent Commands) |
| **Autodetect ID** | `"Virtual DMM"` | `"34410A"` | `"MODEL 2000"` | `["Keithley 193A", "NDCV"]` |
| **Sense function selection** | `set_sense_function` updates state (`VOLT`, `CURR`, `RES`) | `CONF:VOLT:DC`, `CONF:CURR:DC`, `CONF:RES`, `CONF:FRES`, etc. | `:SENS:FUNC 'VOLT:DC'`, `'CURR:DC'`, `'RES'`, `'FRES'`, etc. | `F0X` (DCV), `F3X` (DCA), `F2X` (Ohms) |
| **Default coupling / mode** | `coupling='DC'`, `sense_mode='2W'` | `coupling='DC'`, `sense_mode='2W'` | `coupling='DC'`, `sense_mode='2W'` | `DC` (F0), `2W` (F2) |
| **DC/AC coupling** | `set_measurement_coupling` updates state (`DC`, `AC`) | `CONF:VOLT:DC` / `CONF:VOLT:AC` (or `CONF:CURR:...`) | `:SENS:FUNC 'VOLT:DC'` / `'VOLT:AC'` | `F0X` (DCV) / `F1X` (ACV) |
| **4-Wire / 2-Wire mode** | `set_sense_mode` updates state (`2W`, `4W`) | `CONF:RES` (2W) / `CONF:FRES` (4W) | `:SENS:FUNC 'RES'` (2W) / `'FRES'` (4W) | 2-Wire command only; `4W` raises `NotImplementedError` |
| **Autorange** | `set_sense_range(auto=True)` | `[SENSe:]<func>:RANGe:AUTO ON` | `:SENS:<func>:RANG:AUTO ON` | `R0X` |
| **Manual range** | `set_sense_range(range_val=V, auto=False)` | `[SENSe:]<func>:RANGe V` | `:SENS:<func>:RANG V` | Unsupported in software; `auto=False` raises `NotImplementedError` |
| **Integration time (NPLC)** | `set_integration_time(nplc)` | `[SENSe:]<func>:NPLC <nplc>` (DCV, DCI, RES, FRES); non-DC raises `NotImplementedError` | `:SENS:<func>:NPLC <nplc>` (DCV, DCI, RES, FRES, TEMP); non-DC raises `NotImplementedError` | Rate commands: `<0.01` -> `S0X`, `<0.1` -> `S1X`, `<1.0` -> `S2X`, `>=1.0` -> `S3X` |
| **`get_voltage(ac=False)`** | Updates state; returns scalar float | `CONF:VOLT:DC` + `READ?` -> float | `:SENS:FUNC 'VOLT:DC'` + `:READ?` -> float | `F0X` + read `NDCV...` -> float |
| **`get_voltage(ac=True)`** | Updates state; returns scalar float | `CONF:VOLT:AC` + `READ?` -> float | `:SENS:FUNC 'VOLT:AC'` + `:READ?` -> float | `F1X` + read `NACV...` -> float |
| **`quick_read()`** | Delegates to `get_voltage(ac=coupling=='AC')` | `READ?` -> float | `:READ?` -> float | `get_voltage()` -> float |
| **Getter state synchronization** | Synchronizes state dictionary | Updates `_scpi_sense_func` to active function | Updates `_scpi_sense_func` to active function | Hardware function switched via DDC command |
| **Scalar float return** | Strictly enforced via `float()` | Strictly enforced via `float()` | Strictly enforced via `float()` | Strictly enforced via `float()` |
| **Overload / non-finite handling** | Direct IEEE 754 non-finite pass-through (`inf`, `-inf`, `nan`); no SCPI magic numbers | Normalizes `SCPI_OVERLOAD_THRESHOLD` (9.9e37) to `float('inf')` / `float('-inf')` | Normalizes `SCPI_OVERLOAD_THRESHOLD` (9.9e37) to `float('inf')` / `float('-inf')` | Detects `DDC_OVERLOAD_PREFIXES` / `DDC_OVERLOAD_THRESHOLD` (9.9e30) and normalizes to `float('inf')` / `float('-inf')` |
| **`get_frequency()`** | Not supported (inherits `@optional`) | Supported (`CONF:FREQ` + `READ?`) | Supported (`:SENS:FUNC 'FREQ'` + `:READ?`) | Not supported (inherits `@optional`) |
| **`get_temperature()`** | Not supported (inherits `@optional`) | Not supported (inherits `@optional`) | Supported (`:SENS:FUNC 'TEMP'` + `:READ?`) | Supported (`F6X` RTD + read) |
| **`get_capacitance()`** | Not supported (inherits `@optional`) | Supported (`CONF:CAP` + `READ?`) | Not supported (inherits `@optional`) | Not supported (inherits `@optional`) |
| **Reset / Clear** | Resets state dict / no-op | `*RST` (restores function cache to `'VOLT:DC'`) / `*CLS` | `*RST` (restores function cache to `'VOLT:DC'`) / `*CLS` | `L0X` / IEEE-488 Selected Device Clear |

---

## 4. Analysis of Driver Defects, Overload Handling, and State Synchronization

### 4.1 Overload Representation and Finite Float Hazard
In standard SCPI instruments (Agilent 34410A, Keithley 2000), input overload is signaled by returning `+9.90000000E+37` or `+9.99999900E+37`. In Keithley 193A, it is signaled by an `OVOL` prefix followed by `+999.9999E+30`.

In IEEE 754 floating-point arithmetic, `9.9e37` is a **finite** number (finite floats extend up to \(pprox 1.8 	imes 10^{308}\)). Consequently:
```python
np.isfinite(9.9e37)  # Returns True!
```
If a driver returns `9.9e37` as a literal float, measurement validation checks such as:
```python
voltage = float(self.dmm.get_voltage())
if not np.isfinite(voltage):
    raise ValueError("DMM returned a non-finite detector voltage")
```
will **fail to detect the overload**, allowing catastrophic \(10^{37}\) V readings to enter the dataset without triggering safety shutdown!

**Correction**:
- **Physical Hardware Drivers**: Drivers implement `_parse_reading` using documented manufacturer thresholds (`SCPI_OVERLOAD_THRESHOLD = 9.9e37` on Agilent 34410A and Keithley 2000; `DDC_OVERLOAD_PREFIXES` and `DDC_OVERLOAD_THRESHOLD = 9.9e30` on Keithley 193A) to map instrument over-range responses into IEEE 754 non-finite floats (`float("inf")` or `float("-inf")`).
- **`VirtualDMM`**: As a pure software simulation, `VirtualDMM` does not perform SCPI hardware sentinel sniffing. Injected callables return IEEE 754 non-finite values (`float("inf")`, `float("-inf")`, `float("nan")`) directly.
As a result:
- `np.isfinite(voltage)` evaluates to `False`.
- MOKE and other measurement loops cleanly reject overload readings with `ValueError("DMM returned a non-finite detector voltage")`.
- The measurement's `shut_off()` runs in the `finally` block, safely de-energizing the source.

### 4.2 Getter and Reset Function Tracking Synchronization
In both `Agilent34410A` and `Keithley2000`, reading methods (`get_voltage()`, `get_current()`, `get_resistance()`, `get_frequency()`, `get_capacitance()`, `get_temperature()`) send commands to configure and query the instrument (e.g. `CONF:VOLT:DC`, `:SENS:FUNC 'VOLT:DC'`).

Previously, these getters changed the instrument's hardware function without updating internal function tracking (`_scpi_sense_func`). Consequently:
- Calling `set_sense_function("CURR")`, then `get_voltage()`, then `set_measurement_coupling("AC")` sent a `CURR:AC` command because the driver's cached function was still `CURR`.
- In `Keithley2000`, range and integration setters (`set_sense_range`, `set_integration_time`) rely on the cached function to format `:SENS:<func>:RANG:AUTO` and `:SENS:<func>:NPLC`. Calling them after `get_voltage()` configured range/NPLC for the stale pre-read function rather than voltage.
- Calling `reset()` emitted `*RST` to restore hardware factory defaults (`VOLT:DC`), but left `_scpi_sense_func` pointing to whatever non-voltage function had been queried before reset.

**Correction**:
1. All getters in `Agilent34410A` and `Keithley2000` now explicitly update `_scpi_sense_func` to reflect the newly selected function. Subsequent coupling, range, and integration commands operate on the current hardware function.
2. Both `Agilent34410A` and `Keithley2000` override `_initialize_state()` and `reset()` to restore `self._scpi_sense_func = "VOLT:DC"`. Calling `reset()` and then configuring coupling, range, or integration cleanly operates on the factory default DC voltage mode without stale state errors.

### 4.3 Explicit Capability Gating vs Silent Ignoring
Section 9.2 requires:
> Unsupported optional configuration is capability-gated explicitly; it is not inferred by catching arbitrary driver errors.

Previously, unsupported configurations were either silent no-ops (e.g. `Keithley193a.set_sense_range(auto=False)` had a `pass` stub, `set_sense_mode('4W')` merely printed to stdout, and `Agilent34410A.set_integration_time` silently skipped writing NPLC when in AC mode).

**Correction**:
- `Keithley193a.set_sense_range(range_val=..., auto=False)` explicitly raises `NotImplementedError`.
- `Keithley193a.set_sense_mode("4W")` explicitly raises `NotImplementedError`.
- `Agilent34410A.set_integration_time` and `Keithley2000.set_integration_time` explicitly raise `NotImplementedError` when called while the active function does not support NPLC (e.g. AC voltage/current, frequency, capacitance).

---

## 5. MOKE Integration and Overload Rejection Verification

Real `MokeMeasurement` runs are verified across all four DMM drivers in `tests/test_dmm_contract.py`:
1. **Instrument Configuration**:
   `moke.configure_instruments()` executes `dmm.set_sense_function(sense_func="VOLT")` and `dmm.set_measurement_coupling(coupling="DC")`.
2. **Standard Measurement Execution**:
   Running `moke.capture_data()` with finite detector voltages completes the commanded cycles, populates `moke.data` with calibrated fields and measured detector voltages, and executes safing (`source.output(channel=1, on=False)`).
3. **Overload Rejection and Safing**:
   When any DMM returns an overload response (`+9.90000000E+37` for Agilent 34410A, `+9.99999900E+37` for Keithley 2000, `OVOL+999.9999E+30` for Keithley 193A, or `float('inf')` for VirtualDMM):
   - `get_voltage()` returns `float('inf')`.
   - `moke.capture_data()` detects `not np.isfinite(voltage)` and raises `ValueError("DMM returned a non-finite detector voltage")`.
   - The sourcemeter output is confirmed disabled (`output_on == False`) after the exception.
