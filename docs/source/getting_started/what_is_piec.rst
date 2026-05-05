What is PIEC?
=============

**PIEC (Python Integrated Experimental Control)** is a Python library for streamlining control of laboratory instruments and rapid development of new experimental procedures. 
It enables scientists to quickly test and build new experimental setups without
getting bogged down in low-level instrument communication.

PIEC provides:

* **Instrument drivers** — a unified interface for communicating with real hardware (AWGs,
  oscilloscopes, DMMs, lock-in amplifiers, and more) over GPIB, USB, and other connections.
* **Measurement classes** — ready-to-use experiment types (hysteresis loops, PUND, AMR, IV
  sweeps) that handle instrument configuration, data acquisition, and saving automatically.
* **GUIs and notebooks** — graphical interfaces and Jupyter notebook examples for interactive
  use without writing code from scratch.

.. image:: ../_static/PIEC_diagram.png
   :alt: piec logo
   :align: center
   :width: 450px
   :class: no-invert

Who is PIEC for?
----------------
PIEC is aimed at experimental scientists and engineers who:

* Work with programmable lab instruments.
* Want to automate measurements and reduce manual data collection.
* Need a flexible starting point they can extend for custom experiments.

How PIEC fits into your workflow
---------------------------------
A typical PIEC workflow looks like this:

1. Connect to your instruments using a driver from ``piec.drivers``.
2. Create a measurement object with your experimental parameters.
3. Call ``run_experiment()`` — piec handles instrument configuration, waveform output, data
   capture, and saving.
4. Inspect and analyze the output data.

For a hands-on introduction, see :doc:`quickstart`.