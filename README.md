<p align="center">
  <img src="https://raw.githubusercontent.com/TransluSci/piec/master/docs/source/_static/logo.png" alt="PIEC logo" width="80"/>
</p>

<h1 align="center">PIEC — Python Integrated Experimental Control</h1>

<p align="center">
  <a href="https://piec.readthedocs.io/en/latest/?badge=latest"><img src="https://readthedocs.org/projects/piec/badge/?version=latest" alt="Documentation Status"/></a>
  <a href="https://pypi.org/project/piec/"><img src="https://badge.fury.io/py/piec.svg" alt="PyPI version"/></a>
  <a href="https://pypi.org/project/piec/"><img src="https://img.shields.io/pypi/l/piec.svg" alt="PyPI license"/></a>
  <a href="https://mybinder.org/v2/gh/TransluSci/piec/master?urlpath=lab/tree/Measurements/Quickstart/quick_start.ipynb"><img src="https://mybinder.org/badge_logo.svg" alt="Launch Binder"/></a>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/TransluSci/piec/master/docs/source/_static/example_data.png" alt="Example ferroelectric PUND current traces and polarization hysteresis loop collected and analyzed with piec" width="700"/>
</p>

`PIEC` is an open-source Python library that provides infrastructure for laboratory experiment design and operation through a standardized, hierarchical, object-oriented framework. Originally developed at Brown University as a fork of the ferroelectric testing-focused [EKPY](https://github.com/ElPsyKurisu/ekpmeasure) Python suite, `PIEC` is designed to be extended to any experimental domain that requires programmable instrument control.

---

## Installation

`PIEC` requires Python 3.9 or higher:

```bash
pip install piec
```

---

## Quickstart GUI (No Coding Required)

Run the desktop quickstart app to generate and capture waveforms with an interactive graphical interface:

```bash
python Measurements/Quickstart/quick_start_local_GUI.py
```

* Works out of the box in **Virtual** simulation mode (no hardware required).
* Connect physical instruments with dropdown selection or **Autodetect**.
* Configure sine, square, or ramp waveforms and view live scope captures.
* Optionally save captured traces directly to CSV.

Prefer running in your browser? Launch the [interactive notebook on Binder](https://mybinder.org/v2/gh/TransluSci/piec/master?urlpath=lab/tree/Measurements/Quickstart/quick_start.ipynb).

---

## Quickstart in Python

Run a complete ferroelectric hysteresis measurement using virtual instruments:

```python
from piec.drivers.awg.k_81150a import Keysight81150a
from piec.drivers.oscilloscope.k_dsox3024a import KeysightDSOX3024a
from piec.measurement.discrete_waveform import HysteresisLoop

# Connect in virtual simulation mode
awg = Keysight81150a("VIRTUAL")
osc = KeysightDSOX3024a("VIRTUAL")

# Configure, capture, analyze, and display plots
experiment = HysteresisLoop(awg, osc, save_dir=".", show_plots=True)
experiment.run_experiment()
```

To run on hardware, pass your instrument's VISA address instead of `"VIRTUAL"`, or use autodetection:

```python
from piec.drivers.autodetect import autodetect

awg   = autodetect('awg')
scope = autodetect('scope')
```

For complete driver documentation and advanced measurement workflows, see the **[User Guide](https://piec.readthedocs.io/en/latest/user_guide/the_driver.html)**.

---

## Supported Instruments

| Category | Models |
|---|---|
| Arbitrary Waveform Generator | Keysight 81150A, Agilent 33220A, Agilent 33500, Siglent SDG2000X |
| Oscilloscope | Keysight DSOX3024A, Agilent DSOX5000, Rigol DS1000Z, Tektronix TDS2000, Tektronix TDS6604, LeCroy SDA6020 |
| Source Meter | Keithley 2400 |
| Lock-in Amplifier | Stanford Research SR830 |
| Digital Multimeter | Agilent 34410A, Keithley 2000, Keithley 193A |
| Pulser | Berkeley Nucleonics BNC 765 |
| DAQ | MCC USB-231, MCC USB-1208HS |
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
PIEC: A Python library for Integrated Experimental Control [Software].
https://github.com/TransluSci/piec
```
