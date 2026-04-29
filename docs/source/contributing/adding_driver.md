# Adding a Driver

This page explains the recommended workflow for creating a new instrument driver for piec. The majority of the implementation work is handled by an AI coding assistant — your job is to gather the right materials, provide them clearly, and then review and validate the output.

The **Code Rules Reference** at the bottom of this page defines every architectural rule the driver must follow. Read it before starting.

---

## Step 1: Gather your materials

Before opening an AI session, collect the following:

1. **The instrument programming manual** — the PDF (or equivalent) that documents all remote-control commands for the instrument.

2. **The parent class file** — identify which instrument category your instrument belongs to (e.g. AWG, oscilloscope, sourcemeter, lock-in amplifier) and locate its interface file in `src/piec/drivers/`. Examples:

   | Instrument type | Parent file |
   |---|---|
   | Arbitrary Waveform Generator | `drivers/awg/awg.py` |
   | Oscilloscope | `drivers/oscilloscope/oscilloscope.py` |
   | Source Meter | `drivers/sourcemeter/sourcemeter.py` |
   | Lock-in Amplifier | `drivers/lockin/lockin.py` |
   | Digital Multimeter | `drivers/dmm/dmm.py` |

3. **A convenience base class (optional)** — piec provides convenience classes that handle common low-level communication boilerplate. Using one is optional — a driver that inherits only from the instrument-type parent is perfectly valid.

   | Class | File | Use when |
   |---|---|---|
   | `Scpi` | `drivers/scpi.py` | The instrument communicates over VISA (GPIB, USB-TMC, Ethernet) and follows the SCPI-99 standard. Gives you `idn()`, `reset()`, `clear()`, `error()`, `wait()`, etc. for free. |
   | `Digilent` | `drivers/digilent.py` | The instrument is an MCC/Digilent DAQ device using the Universal Library (`mcculw`). Replaces VISA entirely with UL board-number addressing. |

   ```python
   # With Scpi convenience class
   from .awg import Awg
   from ..scpi import Scpi

   class RigolDg1000(Awg, Scpi):
       ...

   # With Digilent convenience class
   from .daq import Daq
   from ..digilent import Digilent

   class Usb231(Daq, Digilent):
       ...

   # No convenience class — implement everything directly
   from .awg import Awg

   class MyCustomAwg(Awg):
       ...
   ```

   If you are unsure which applies, describe the instrument's communication interface in the AI prompt and let it determine the right inheritance.

4. **`DRIVER_DEVELOPMENT_GUIDE.md`** — this file (included at the bottom of this page) is the ruleset the AI must follow. Attach it to every session.

---

## Step 2: Create the file skeleton

Before running the AI session, create an empty driver file in the correct location:

```text
src/piec/drivers/<category>/<model_name>.py
```

For example, a Rigol DG1000 AWG would go in `src/piec/drivers/awg/rigol_dg1000.py`.

Use `src/piec/drivers/example/specific_example.py` as a reference for the expected structure — class definition, `AUTODETECT_ID`, class attributes, and method stubs.

---

## Step 3: Run the AI coding session

Open your preferred AI coding assistant (e.g. Google Gemini, GitHub Copilot, Claude) and attach the following files:

| File | Why |
|---|---|
| `DRIVER_DEVELOPMENT_GUIDE.md` | The rules the driver must follow |
| `drivers/<category>/<category>.py` | The parent interface to implement |
| `drivers/scpi.py` or `drivers/digilent.py` | **Optional** — include the relevant convenience class file only if your instrument uses it |
| Instrument programming manual | The primary source of all command strings and device capabilities |
| Instrument user manual | **Optional** — attach alongside the programming manual if you need to extract hardware specs or features not covered there (e.g. channel count, voltage ranges). The programming manual usually covers this. |

Then provide the following prompt, filling in the blanks:

---

### Primary prompt (implementation)

```
You are tasked with creating a new instrument driver for the piec Python package.

**Instrument:** <Manufacturer> <Model Number> (e.g. Rigol DG1000)
**Instrument type:** <Type> (e.g. Arbitrary Waveform Generator)
**Parent class:** <ClassName> from the attached parent file (e.g. Awg)
**Uses SCPI protocol:** <Yes / No>

**Attached files:**
- DRIVER_DEVELOPMENT_GUIDE.md — read this first. It defines every rule the driver must follow.
- <category>.py — the parent class. Implement every method defined in it.
- scpi.py — include only if the instrument uses SCPI. If it does not, omit this file and implement communication directly.
- <manual filename> — use this as the sole source for all command strings.

**Your task:**
1. Implement all methods from the parent class using commands from the attached manual.
   Only use commands you can find in the manual — do not invent or guess command strings.
2. Fill out all class attributes (capabilities and limits) as described in the guide.
3. Set AUTODETECT_ID to the unique model substring returned by the instrument's *IDN? response.
   If the manual does not show an example *IDN? response, set it to None.
4. Do not write any # inline comments — use docstrings only.
5. Follow the method naming, signature, and default-parameter rules in the guide exactly.
```

---

### Verification pass (optional but recommended)

After receiving the initial driver, run a second session with the same attachments plus the generated driver and ask:

```
Review the attached driver against the instrument manual and the DRIVER_DEVELOPMENT_GUIDE.md rules.

Check for the following and list any discrepancies:
1. Are all class attribute names identical to the argument names used in the methods?
2. Do the class attribute values (ranges, lists) match the manual?
3. Are all command strings sent to the instrument valid according to the manual?
4. Are all methods from the parent class implemented? Have any extra methods been added that are not in the parent?

For each discrepancy, show: the original code, the corrected code, and the section of the manual or guide where you found the issue.
```

---

## Step 4: Register the driver

Once the driver file is in place:

1. **Add the import** to the `__init__.py` in the category folder so piec can discover it.
2. **Verify autodetection** — the `AUTODETECT_ID` string must be a unique substring of the instrument's identification response. You can test this by connecting to the instrument and calling `.idn()` on it.

---

## Step 5: Validate with the test notebook

Each driver category has a Jupyter test notebook in its folder (e.g. `drivers/awg/awg_test.ipynb`). Use this to verify your driver against the virtual instrument first, then against real hardware.

The notebook follows this structure:

- **Section 0** — connection and `.idn()` check
- **Sections 1–2** — base `Instrument` communication tests
- **Sections 3+** — driver-specific method tests (one cell per method)
- **Final section** — cleanup and disconnect

When adding a new driver, copy `src/piec/drivers/example/example_test.ipynb` as a starting template. Add a cell for each method your driver implements. Run each cell from top to bottom sequentially and confirm expected behavior before opening a pull request.

---

## Before contributing

If you are planning to submit this driver as a pull request, we strongly recommend the following before forking the repository and opening a PR:

* **Test against real hardware.** Run the test notebook (Step 5) end-to-end with a physical instrument connected. Every cell should pass without errors or unexpected responses.
* **Cross-check all command strings.** For each method, verify the command sent to the instrument against the manual one more time — AI-generated command strings can be subtly wrong.
* **Check the autodetect ID.** Connect to the instrument, call `.idn()`, and confirm that `AUTODETECT_ID` is a substring of the actual response string.
* **Run the automated test suite.** From the repository root: `pytest tests/ -v`. All tests must pass before submitting.

A driver that has only been verified against the virtual instrument is not ready for a pull request. Physical hardware verification is the minimum bar for contribution.

---

## Code Rules Reference

The following is the complete `DRIVER_DEVELOPMENT_GUIDE.md`. Every rule here is enforced during code review.

```{include} ../../../src/piec/drivers/example/DRIVER_DEVELOPMENT_GUIDE.md
```