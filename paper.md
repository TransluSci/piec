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
    orcid: 0009-0008-2687-671X
    affiliation: 1
  - name: Alexander Qualls
    orcid: 0000-0001-9070-026X
    affiliation: 1
  - name: Jesalina Phan
    orcid: 0009-0007-7216-8506
    affiliation: 1
  - name: Rohan Pankaj
    orcid: 0009-0005-0445-9323
    affiliation: 1
  - name: Lucas Caretta
    orcid: 0000-0001-7229-7980
    affiliation: 1

affiliations:
  - name: Brown University, Providence, Rhode Island, USA
    index: 1
date: 03 March 2026
bibliography: paper.bib
---

# Summary

Experimental laboratories depend on the precise, coordinated control of myriad instruments from complex waveform generators, oscilloscopes, or amplifiers, to simple motors or magnetic coils. Any automatable experimental procedure can be decomposed into communications with individual instruments, scripting that synchronizes instrument behavior, and data collection and processing. `PIEC` (Python Integrated Experimental Control) is an open-source Python library that provides the infrastructure for such experiment design and operation through a standardized, hierarchical, object-oriented framework with points of entry at multiple levels of technical depth. Originally developed at Brown University as a fork of the ferroelectric testing-focused ‘EKPY’ python suite [@Parsonnet_ekpy], `PIEC` is designed to be extended to any experimental domain that requires programmable instrument control. It is installable via `pip install piec` and its documentation is hosted at [https://piec.readthedocs.io](https://piec.readthedocs.io).

# Statement of Need

`PIEC` was designed to be used by anyone looking to automate laboratory instruments, from professional scientists and engineers to students learning to use these instruments for the first time. Currently, when setting up an experiment, users often must build automations from scratch or pay high prices for proprietary test kit solutions. `PIEC`'s API was designed to provide a class-based, user-friendly interface for common experimental operations such as waveform generation, data acquisition, and synchronized multi-instrument triggering. The package seeks to be a collaborative central repository where researchers can design and build experiments and share their work, collectively saving tedious ramp up time for new laboratory setups. `PIEC` relies on and interfaces naturally with the standard scientific Python stack, using NumPy, SciPy, Matplotlib, and pandas for data handling and visualization.

The ferroelectric measurement workflow illustrates the challenge that motivated `PIEC`: to measure a polarization–electric field hysteresis loop, a researcher must configure an arbitrary waveform generator (AWG) to output a specific triangular voltage waveform, trigger an oscilloscope to capture the resulting displacement current, and integrate the current to recover the polarization, all before a single data point is recorded. 

Inconsistencies in communication protocols and in the structure of other open-source instrument drivers mean that a researcher setting up such a measurement would typically build a system from the ground-up based on available hardware, navigating multiple repositories and repeating work done by many others before. Alternatively, the researcher could purchase a small number of ferroelectric testing solutions that exist on the market, though by virtue of the profit model, these packages severely lack in customization, transparency in circuit/software design, are significantly marked up over base hardware costs, and may contain functions which go unused for the researcher’s specific needs, only inflating cost and complexity.

`PIEC` was designed to allow code-savvy researchers to automate exactly this kind of procedure, or for time-constrained researchers to simply download the repository, source the hardware that meets their specific needs, and immediately program experiments and acquire data using a pre-built GUI or Jupyter Notebook. The combination of validated and standardized instrument drivers, reusable `Measurement` classes, and myriad convenience functionalities such as file system handling and virtual instruments for offline testing in `PIEC` allows the researcher to choose exactly where on the spectrum of customization they want to enter the experimental design process.

# State of the Field

The landscape of laboratory automation is dominated by commercial platforms such as LabVIEW [@LabVIEW], which are widely deployed across experimental physics and materials science laboratories. While powerful, these solutions rely on proprietary programming environments and require licenses, making them cost-restrictive, inflexible, and difficult to integrate with modern version-control and data-science workflows.

In the open-source ecosystem, several Python-based tools have emerged to address these limitations. General-purpose packages like PyMeasure [@rawlings2023pymeasure] and QCoDeS [@qcodes] provide extensive libraries of instrument wrappers, parameter validation, and sweep automation. Within specific subfields, targeted packages such as Hardware-Control [@hardware_control] and EKPY [@Parsonnet_ekpy] have been developed to handle automated testing and analysis for specific instrumentation, focusing on beamline and ferroelectric measurements respectively.

PIEC was developed to bridge the gap between generalized instrument wrappers and highly specialized, rigid test suites. It is a valuable alternative to the options listed above because of three major differences in design:

First and foremost, `PIEC` employs a "type-first" architecture. Existing solutions like PyMeasure [@rawlings2023pymeasure] typically build drivers around specific instrument models, which can make substituting hardware within an experimental setup cumbersome. In contrast, `PIEC` is designed around rigid driver class definitions built from abstract templates. These templates enforce a standard interface across any instrument of a given type (e.g., any arbitrary waveform generator or oscilloscope must possess the same core methods). While this type-first approach may require extra effort to expose unique features of a specific model, it allows a standardized, hardware-agnostic measurement stack to be built on top of the drivers.

Second, `PIEC` prioritizes minimizing overhead for researchers who want to get new experimental flows up and running quickly and simply. While other open-source repositories like QCoDeS [@qcodes] provide excellent frameworks to script experimental setups, and can act as robust control and data handling backbones to a laboratory setup, the depth of features can make initial setup and rapid prototyping cumbersome. The hierarchical structure of `PIEC` allows researchers to deploy complex experiments quickly, with little to no Python knowledge.

Third, as an open-source project `PIEC` aims to maintain a transparent and modular nature while providing the "plug-and-play" convenience often associated with commercial test kits like LabVIEW [@LabVIEW]. This enables researchers to invest their funding directly into hardware rather than software licenses, without sacrificing the ability to quickly deploy peer-tested characterization routines.

# Software Design

The main principle behind `PIEC`'s instrument control design is to provide a user-friendly API that researchers can use to ensure continuity between different instrument manufacturers and experimental setups. The instrument drivers are designed with a “type-first” philosophy, and can be understood as having three layers of abstraction>

Within `piec.drivers`, the base `Instrument` class (Level 1) is a parent class which defines the minimum requirements of any instrument driver in general, wrapping PyVISA [@pyvisa] for resource management. The `Scpi` child class optionally extends this with vetted implementations for Standard Commands for Programmable Instruments (SCPI)-compliant devices [@scpi1999spec]. Driver classes (Level 2) — such as `Oscilloscope`, `Awg`, `lockin`—define the required methods and parameter standards for the drivers to implement. Specific instrument models (Level 3) inherit from these classes and implement the hardware-specific logic. Each instrument category also provides a `VirtualInstrument` that returns simulated responses, enabling development and testing without physical hardware.

On top of this three-level standardized instrument control, within `piec.measurement` we provide `Measurement` classes that coordinate multiple drivers to implement complete experiment protocols. For example, `HysteresisLoop` configures an AWG to output a triangular voltage waveform, triggers an oscilloscope to capture applied voltage and displacement current, integrates the current to compute polarization, and saves the P-E loop to a structured file, all in a single method call. Each `Measurement` class initializes using instrument objects that match the required instrument types for the particular measurement. It then calls functions from the instrument objects to produce the correct calls to the hardware. Further analysis methods in the `Measurement` class process the data, save data files in a standard ‘.csv’ format along with added metadata.

Finally, in the top-level Measurement repository, GUIs are provided using a class in ‘piec.measurement.gui_utils.py’ which leverages tkinter and Matplotlib [@hunter2007matplotlib], as well as python notebooks where the measurement and driver classes can be run directly. Useful background on measurements is included in the notebooks as well as markdown files in the same directory.

The layered architecture means that a researcher can work at whatever level their experiment requires, whether that is coding driver methods for new setups, creating `Measurement` classes for running experiments, or using the pre-existing graphical interfaces for routine tasks without writing code. Throughout the workflow, standard Python packages such as NumPy [@harris2020array], and Pandas @[the_pandas_development_team_2026_19340003].

In the case that an instrument isn't supported or a new measurement class is needed, extending `PIEC` is also simple. Adding a new instrument requires implementing a driver subclass alongside its `VirtualInstrument`, and adding a new experiment type requires implementing a `Measurement` subclass, without modifying other existing code.

Effort has been put in to make contribution to the codebase using modern LLM-enabled workflows convenient and robust. The directory for each instrument type contains a template class which contains every method and attribute, as well as detailed docstrings, but no implementation. Entirely new instruments can be quickly and seamlessly integrated into the codebase by providing the existing `example` driver template and the corresponding `DRIVER_DEVOLPMENT_GUIDE` as context to an LLM, and then manually stepping through provided debugging notebooks.

# Research Impact Statement

`PIEC` has been developed and applied at Brown University, based on software developed at UC Berkeley to support experimental research on ferroelectric thin films and correlated oxide materials. The repository is currently deployed at Brown to perform charge and magneto-transport characterization of thin film complex oxides. It is also deployed at UC Berkeley to evaluate the performance of ferroelectric films grown with CMOS-compatible workflows. `PIEC` provides the first open-source, Python-native implementation of these protocols that implements an abstracted instrument-type-first design philosophy that enables unprecedented ease of use for diverse research objectives.

# AI Usage Disclosure

Portions of the source code and documentation were developed with assistance from generative AI tools including Google Gemini, GitHub Copilot, and Claude Code. All AI-generated content was manually reviewed, tested, and modified by the authors prior to inclusion in the repository.

# Acknowledgements

