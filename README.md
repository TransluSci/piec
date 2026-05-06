<p align="center">
  <img src="https://raw.githubusercontent.com/ElPsyKurisu/piec/master/docs/source/_static/logo.png" alt="PIEC logo" width="80"/>
</p>

<h1 align="center">PIEC — Python Integrated Experimental Control</h1>

<p align="center">
  <a href="https://piec.readthedocs.io/en/latest/?badge=latest"><img src="https://readthedocs.org/projects/piec/badge/?version=latest" alt="Documentation Status"/></a>
  <a href="https://pypi.org/project/piec/"><img src="https://badge.fury.io/py/piec.svg" alt="PyPI version"/></a>
  <a href="https://pypi.org/project/piec/"><img src="https://img.shields.io/pypi/l/piec.svg" alt="PyPI license"/></a>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/ElPsyKurisu/piec/master/docs/source/_static/example_data.png" alt="Example ferroelectric PUND current traces and polarization hysteresis loop collected and analyzed with piec" width="700"/>
</p>

`PIEC` is an open-source Python library that provides infrastructure for laboratory experiment design and operation through a standardized, hierarchical, object-oriented framework. Originally developed at Brown University as a fork of the ferroelectric testing-focused [EKPY](https://github.com/ElPsyKurisu/ekpmeasure) Python suite, `PIEC` is designed to be extended to any experimental domain that requires programmable instrument control.

---

## Installation

`PIEC` requires python 3.9 or higher. To install `PIEC`, run the following command in the terminal:

```bash
pip install piec
```

After this, decide whether you would like to run a specific measurment with a GUI or notebook (in which case you'll need to download the appropriate files from the `Measurements` folder). Otherwise, see below for information on how to start scripting. Depending on your instruments, you may also need:

| Requirement | When needed | Download |
|---|---|---|
| **NI-488.2** | GPIB instruments | [ni.com](https://www.ni.com/en/support/downloads/drivers/download.ni-488-2.html) |
| **NI-VISA** | USB-TMC / Ethernet / GPIB via NI-VISA | [ni.com](https://www.ni.com/en/support/downloads/drivers/download.ni-visa.html) |
| **MCC Universal Library + `mcculw`** | Digilent/MCC DAQ boards | [mccdaq.com](http://www.mccdaq.com/swdownload) |

---

## Overview

Instrument drivers in `PIEC` follow a **type-first** architecture with three layers of abstraction:

| Layer | Role | Examples |
|---|---|---|
| **Level 1 — Instrument** | Base connection management and parameter validation (wraps PyVISA) | `Instrument`, `Scpi` |
| **Level 2 — Category** | Defines required methods and parameter standards for each instrument type | `Awg`, `Oscilloscope`, `Lockin`, `Sourcemeter` |
| **Level 3 — Model** | Implements hardware-specific logic for a particular instrument | `Keysight81150a`, `RigolDS1000Z`, `Keithley2400` |

Measurement code targets the **Level 2 interface**, so instruments are interchangeable without code changes. Each category also provides a **Virtual Instrument** that returns simulated responses, enabling development and testing without physical hardware.

On top of this driver layer, **Measurement classes** coordinate multiple instruments to execute complete experiment protocols — configuring waveforms, triggering acquisition, processing data, and saving results — in a single method call. Pre-built **GUIs** and **Jupyter notebooks** are also provided for routine tasks.

---

## Quick Start

**Virtual mode** — no hardware required:

```python
from piec.drivers.awg.virtual_awg import VirtualAwg

awg = VirtualAwg()
awg.set_waveform(1, 'sin')
awg.set_frequency(1, 1000)
awg.set_amplitude(1, 1.0)
awg.output(1, on=True)
```

**Autodetection** — connect and go:

```python
from piec.drivers.autodetect import autodetect

awg   = autodetect('awg')
scope = autodetect('scope')
```

For a complete walkthrough, see the [User Guide](https://piec.readthedocs.io/en/latest/user_guide/the_driver.html).

---

## Supported Instruments

| Category | Models |
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

**[Full instrument list →](https://piec.readthedocs.io/en/latest/supported_instruments.html)**

---

## Contributing

New drivers can be added by implementing a driver subclass alongside its Virtual Instrument, following the [Driver Development Guide](https://github.com/TransluSci/piec/blob/master/src/piec/drivers/example/DRIVER_DEVELOPMENT_GUIDE.md). New experiment types require implementing a Measurement subclass without modifying existing code.

For general guidelines, see the [Contributing Guide](https://piec.readthedocs.io/en/latest/contributing/index.html).

---

## Support

Issues, bug reports, and feature requests: [Issue Tracker](https://github.com/TransluSci/piec/issues)

Maintainer: Geo Fratian — geo_fratian@brown.edu

---

## Citation

Please cite this software following the [CITATION.cff](https://github.com/TransluSci/piec/blob/master/CITATION.cff).

```
Fratian, G., Qualls, A., Phan, J., Pankaj, R., & Caretta, L. (2026).
PIEC: A Python Library for Integrated Experimental Control [Software].
https://github.com/TransluSci/piec
```
