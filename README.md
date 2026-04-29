# PIEC — Python Integrated Experimental Control

[![Documentation Status](https://readthedocs.org/projects/piec/badge/?version=latest)](https://piec.readthedocs.io/en/latest/?badge=latest)
[![PyPI version](https://badge.fury.io/py/piec.svg)](https://pypi.org/project/piec/)
[![PyPI license](https://img.shields.io/pypi/l/piec.svg)](https://pypi.org/project/piec/)

<!-- TODO: Replace with a real figure (e.g. a ferroelectric hysteresis loop collected and analyzed with piec) -->
<!-- [![Example Figure](imgs/placeholder.png)](https://piec.readthedocs.io) -->

A Python instrument control and measurement library for condensed matter physics experiments — featuring automatic driver detection, a standardized driver hierarchy, and built-in virtual instrument support for offline development.

- [Overview](#overview)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Supported Instruments](#supported-instruments)
- [Contributing](#contributing)
- [Support](#support)
- [Citation](#citation)

---

# Overview

Running experiments across multiple instruments — AWGs, oscilloscopes, source meters, lock-in amplifiers, DMMs — typically means writing bespoke control code for every hardware combination. When you swap an instrument, you rewrite code. When you hand off to a student, they learn everything from scratch.

**piec** solves this with a standardized 3-level driver hierarchy:

```
Level 1 — Instrument          Base connection management + parameter validation
Level 2 — Category Interface  e.g. Awg, Oscilloscope, Lockin, Sourcemeter, DMM
Level 3 — Specific Model      e.g. Keysight81150a, RigolDS1000Z, Keithley2400
```

Measurement code talks to the **Level 2 interface**, so instruments are interchangeable without any code changes. Swap a Keysight oscilloscope for a Rigol — the measurement script stays the same.

### Key Features

- **Autodetection** — connect any supported instrument and piec finds and loads the correct driver automatically via `autodetect()`. Subsequent connections are instant thanks to a local registry cache.
- **Virtual Mode** — every driver supports `address='VIRTUAL'` for offline development and testing. Write and debug measurement code without any physical hardware.
- **Parameter Validation** — optional `check_params=True` flag validates method arguments against the instrument's known ranges before sending any command, preventing invalid configurations from reaching hardware.
- **State Tracking** — the framework automatically records every successfully set parameter, enabling dependent validation (e.g. knowing the current waveform to validate the frequency range) without extra instrument queries.
- **Measurement Classes** — pre-built experiment workflows for common condensed matter measurements (ferroelectric hysteresis, PUND, IV sweeps, AMR) that handle instrument configuration, data acquisition, and analysis in a single `run_experiment()` call.

---

# Installation

Install piec from PyPI:

```bash
pip install piec
```

or upgrade to the latest version:

```bash
pip install -U piec
```

### Additional Requirements

Depending on your instruments, you may need one or more of the following:

| Requirement | When needed | Download |
|---|---|---|
| **NI-488.2** | GPIB instruments | [ni.com/downloads](https://www.ni.com/en/support/downloads/drivers/download.ni-488-2.html) |
| **NI-VISA** | USB-TMC, Ethernet, or GPIB instruments via NI-VISA | [ni.com/downloads](https://www.ni.com/en/support/downloads/drivers/download.ni-visa.html) |
| **MCC Universal Library + `mcculw`** | Digilent/MCC DAQ boards (e.g. USB-231) | [mccdaq.com/swdownload](http://www.mccdaq.com/swdownload) |

For installation issues, see the [Issue Tracker](https://github.com/TransluSci/piec/issues).

---

# Quick Start

No hardware? No problem. Every piec driver works in virtual mode out of the box:

```python
from piec.drivers.awg.virtual_awg import VirtualAwg

awg = VirtualAwg()
print(awg.idn())             # 'Piec_Virtual_Instrument,...'
awg.set_waveform(1, 'sin')
awg.set_frequency(1, 1000)
awg.set_amplitude(1, 1.0)
awg.output(1, on=True)
```

With real hardware, use `autodetect()` to find and connect to your instruments automatically:

```python
from piec.drivers.autodetect import autodetect

awg = autodetect('awg')       # Scans the bus and loads the correct driver
scope = autodetect('scope')

print(awg.idn())
print(scope.idn())
```

Or connect manually with a known VISA address:

```python
from piec.drivers.awg.k_81150a import Keysight81150a

awg = Keysight81150a('GPIB0::8::INSTR')
print(awg.idn())
```

For a complete walkthrough, see the [User Guide](https://piec.readthedocs.io/en/latest/user_guide/the_driver.html).

---

# Supported Instruments

| Category | Supported Models |
|---|---|
| Arbitrary Waveform Generator | Keysight 81150A, Agilent 33220A, Agilent 33500, Rigol DG1000, Rigol DG4000, Siglent SDG2000X |
| Oscilloscope | Keysight DSOX3024A, Agilent DSOX5000, Rigol DS1000Z, Tektronix TDS2000, Tektronix TDS6604, LeCroy SDA6020 |
| Source Meter | Keithley 2400 |
| Lock-in Amplifier | Stanford Research SR830 |
| Digital Multimeter | Agilent 34410A, Keithley 2000, Keithley 193A |
| Pulser | Berkeley Nucleonics BNC 765 |
| DAQ | MCC USB-231 |
| DC Calibrator | EDC 522 |
| Stepper Motor | Arduino Stepper (custom serial) |

Each category also provides a **virtual instrument** for hardware-free development and testing.

**[Full instrument list →](https://piec.readthedocs.io/en/latest/supported_instruments.html)**

---

# Contributing

We welcome contributions! New drivers can be added by following the structured workflow in the [Adding a Driver](https://piec.readthedocs.io/en/latest/contributing/adding_driver.html) guide. The process uses an AI coding assistant together with the instrument's programming manual and our standardized [Driver Development Guide](https://github.com/TransluSci/piec/blob/master/src/piec/drivers/example/DRIVER_DEVELOPMENT_GUIDE.md) to generate a driver skeleton, which is then validated against a hardware test notebook.

For general contribution guidelines, see the [Contributing Guide](https://piec.readthedocs.io/en/latest/contributing/index.html).

---

# Support

Code issues, bug reports, and feature requests can be created in the [Issue Tracker](https://github.com/TransluSci/piec/issues).

Maintainer: Geo Fratian — geo_fratian@brown.edu

---

# Citation

Please cite this software following the [CITATION.cff](https://github.com/TransluSci/piec/blob/master/CITATION.cff).

```
Fratian, G. (2026). PIEC: Python Integrated Experimental Control [Software].
https://github.com/TransluSci/piec
```

## Cited By

<!-- Add publications that use piec here -->
<!-- Example format: -->
<!-- 1. G. Fratian *et al.*, Title of Paper, *Journal* **Vol**, Page (Year). -->
