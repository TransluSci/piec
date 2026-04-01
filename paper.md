---
title: 'PIEC: A Python Library for Integrated Experimental Control'
tags:
  - Python
  - laboratory automation
  - instrument control
  - ferroelectrics
  - materials characterization
  - measurement automation
authors:
  - name: Geo Fratian
    orcid: 0000-XXXX-XXXX-XXXX  #replace with actual ORCID
    affiliation: 1
  - name: Alexander Qualls
    orcid: 0000-XXXX-XXXX-XXXX  #replace with actual ORCID
    affiliation: 1
affiliations:
  - name: Brown University, Providence, Rhode Island, USA
    index: 1
    ror: 05gq02987
date: 03 March 2026
bibliography: paper.bib
---

# Summary

Experimental physics and materials science depend on the precise, coordinated control of instruments such as waveform generators, oscilloscopes, amplifiers, and source
meters. These vital experiments rely on reliable instrument communication, synchronizing multi-device, and structured data collection. `PIEC` (Python Integrated Experimental Control) is an open-source Python library that provides this infrastructure all in one place through a hierarchical driver framework and high-level `Measurement` classes for designing automated multi-instrument experiments. Originally developed to support ferroelectric characterization at Brown University, `PIEC` is designed to be extended to any experimental domain that requires programmable instrument control. It is installable via
`pip install piec` and its documentation is hosted at
[https://piec.readthedocs.io](https://piec.readthedocs.io).

# Statement of Need

`PIEC` was designed to be used by anyone looking to automate laboratory instruments, from experimental physicists and materials scientists to students learning to use these instruments for the first time. With no current centralized way to easily create these automated experiments, `PIEC`'s API was designed to provide a class-based, user-friendly interface for common experimental operations such as waveform generation, data acquisition, and synchronized multi-instrument triggering. `PIEC` also relies on and interfaces naturally with the
scientific Python stack, using NumPy, SciPy, Matplotlib, and pandas for data handling and visualization.

The ferroelectric measurement workflow illustrates the challenge that motivated `PIEC`: to measure a polarization–electric field hysteresis loop, a researcher must configure an arbitrary waveform generator (AWG) to output a specific triangular voltage waveform, trigger an oscilloscope to capture the applied voltage and resulting displacement current simultaneously, acquire multiple waveform traces, and integrate the current to recover the polarization, all before a single data point is recorded. 

Repeating this procedure across dozens of samples and temperatures by hand introduces transcription errors and makes the measurements difficult to reproduce. `PIEC` was
designed to allow researchers and students to automate exactly this kind of procedure,
inspect results interactively in a Jupyter notebook, and share the measurement object
alongside the data. The combination of a validated driver hierarchy, reusable `Measurement` classes, and virtual instruments for offline testing in `PIEC` will allow for more streamlined and efficient experimental workflows.

# State of the Field

Several tools exist for Python-based laboratory automation. `PyMeasure` [@rawlings2023pymeasure] is a package providing instrument wrappers with parameter validation and simple sweep automation. `Bluesky` [@allan2019bluesky] offers a run engine and document model for large-scale synchrotron facilities. `QCoDeS` [@qcodes] is a Python-based data acquisition framework developed for quantum-computing measurement setups. Commercial platforms such as LabVIEW [@LabVIEW] are widely deployed in experimental physics laboratories.

`PIEC` was built rather than contributing to these existing projects for several reasons. First, `PIEC` was designed to execute multi-instrument coordination. `PyMeasure` does well with single-instrument abstraction and parameter
sweeps but does not allow for the synchronized configuration and triggering of multiple devices which is often necessary in experiments. Second, `PIEC` was designed to have minimal infrastructure overhead for small laboratory groups. `Bluesky`'s architecture is better for multi-user facilities but has a barrier for smaller research groups
automating measurements with less resources. `QCoDeS` is also optimized for quantum-device stacks that exceed the needs of most materials-science laboratories. Third, commercial platforms such as LabVIEW require expensive licenses and proprietary programming environments that also are integrated with the modern Python tech stack. `PIEC` fills that gap between simple scripts and heavy infrastructure frameworks.

# Software Design

The main principle behind `PIEC`'s design is to provide a user-friendly, layered API that scientists can use at whatever level of abstraction suits their experiment. Along with this, it can support offline development and testing through virtual instrument implementations that mirror the interface of the hardware.

Within `piec.drivers`, the base `Instrument` class wraps PyVISA for resource
communication and uses a custom metaclass (`AutoCheckMeta`) to preventing out-of-range values from reaching hardware. `SCPI_Instrument` extends this with helpers for Standard Commands for Programmable Instruments (SCPI)-compliant devices. Driver classes for oscilloscopes, AWGs, digital multimeters (DMMs), lock-in amplifiers, source meters, and more, all inherit from these base classes. Each instrument category also provides a `VirtualInstrument` that returns simulated responses, enabling development and testing without physical hardware.

Within `piec.measurement`, we provide `Measurement` classes that coordinate multiple drivers to implement complete experiment protocols. For example, `HysteresisLoop` configures an AWG to output a triangular voltage waveform, triggers an oscilloscope to capture applied voltage and displacement current, integrates the current to compute polarization, and saves the P-E loop to a structured file, all in a single method call. Each `Measurement` class calls functions from driver objects to produce the correct calls to the hardware and format the data.

The layered architecture means that a researcher can work at whatever level their experiment requires, whether that is coding driver methods for new setups, creating `Measurement` classes for running experiments, or using the pre-existing graphical interfaces ()`piec.guis`) for routine tasks without writing code. 

In the case that an instrument isn't supported or a new measurement class is needed, extending `PIEC` is also simple. Adding a new instrument requires implementing a driver subclass alongside its `VirtualInstrument`, and adding a new experiment type requires implementing a `Measurement` subclass, without modifying other existing code.

Care has been taken to make contibution to the codebase as seamless as possible using modern LLM-enabled workflows. The directory for each instrument type contains a template class which contains every method and attribute, as well as detailed doctrings, but no implementation. Entirely new instuments can be quickly and seamlessly integrated into the codebase by providing this template and a coding manual as context to an LLM, and then stepping through provided debugging notebooks.

# Research Impact Statement

`PIEC` has been developed and applied at Brown University to support experimental research on ferroelectric thin films and correlated oxide materials. The measurement protocols it implements (P-E hysteresis and PUND) are standard techniques in the ferroelectrics community. `PIEC` provides the first open-source, Python-native implementation of these protocols that can be shared directly alongside experimental datasets and manuscripts. 

# AI Usage Disclosure

Portions of the source code and documentation were developed with assistance from generative AI tools including Google Gemini, GitHub Copilot, and Claude Code. All AI-generated content was reviewed, tested, and modified by the authors prior to inclusion in the repository.

# Acknowledgements
