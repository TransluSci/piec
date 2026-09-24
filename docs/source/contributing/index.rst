Contributing to PIEC
====================

Thank you for your interest in contributing! PIEC is an open-source project and welcomes
contributions of all kinds.

.. toctree::
   :maxdepth: 1

   adding_driver
   adding_measurement

Bug reports
-----------

If you encounter unexpected behavior, please open an issue on the GitHub repository. Include:

* A minimal reproducible example (what code to run, what instruments are involved).
* The full error message and traceback.
* Your operating system, Python version, and PIEC version (``pip show piec``).

Pull request workflow
---------------------

1. Fork the repository on GitHub and create a feature branch from ``master``.
2. Make your changes, following the code style of the surrounding code.
3. For driver contributions, **do not add or modify tests**: run the existing
   dynamic suites as described in :doc:`adding_driver`. For other functionality,
   add or update tests as appropriate (see :ref:`test-functions`).
4. Open a pull request against ``master`` with a clear description of what changed and why.

.. _test-functions:

Test functions
--------------

**Where tests live**

All tests are in the ``tests/`` directory at the repository root:

* ``test_imports.py`` — tests that every public module and subpackage imports
  without error.
* ``driver/test_instrument_core.py`` — unit tests for the
  :class:`~piec.drivers.instrument.Instrument` base class and its helper functions.
* ``test_measurement_pipeline.py`` — integration tests for measurement classes. Each
  measurement goes through its complete pipeline.
* ``driver/test_driver_physical.py`` and ``driver/test_driver_virtual.py`` — dynamic
  checks that discover model drivers, category interfaces, and virtual drivers.
  New drivers and categories are checked without adding tests or registrations.

**Running tests locally**

Install the package in editable mode and install pytest, then run
pytest from the repository root::

   pip install -e . pytest
   pytest tests/ -v

Run a single file or test class::

   pytest tests/test_measurement_pipeline.py -v
   pytest tests/test_measurement_pipeline.py::TestHysteresisFullPipeline -v

**Testing without physical hardware**

Every driver category has a ``Virtual`` implementation (e.g. ``VirtualAwg``,
``VirtualScope``) that emulates the category API entirely in memory. Constructing
a concrete model with the exact address ``"VIRTUAL"`` uses that category
implementation with the model's capability attributes. Tests never require an
instrument to be connected. The CI workflow runs the same ``pytest`` command, so
all tests must pass using virtual drivers only.

See :doc:`adding_measurement` for the recommended three-class test structure and a
minimal working example for measurement tests.

**Hardware notebook tests**

Each driver category also has a Jupyter notebook for virtual instrument and hardware verification. These notebooks live alongside the driver source:

.. code-block:: text

   src/piec/drivers/
   ├── awg/awg_test.ipynb
   ├── oscilloscope/oscilloscope_test.ipynb
   ├── sourcemeter/sourcemeter_test.ipynb
   ├── dmm/dmm_test.ipynb
   ├── lockin/lockin_test.ipynb
   └── ...

These are **not** part of the automated pytest suite. They are intended to be run
interactively by a technician with an instrument physically connected, to verify that
a new driver (or a change to an existing one) works against real hardware.

Each notebook follows the same structure:

* **Section 0 — Setup & Connection**
* **Sections 1–2 — Instrument & SCPI tests:** 
* **Sections 3+ — Driver-specific tests:** 
* **Final section — Cleanup:** 

Use an existing notebook interactively where applicable, but **do not add tests
or create or modify test notebooks for driver contributions**. Run the existing
dynamic suites and verify the driver on physical hardware, recording the results
in your pull request. See :doc:`adding_driver` for both existing and new categories.


AI use guidelines
-----------------

piec development has made use of AI coding assistants (Google Gemini, GitHub Copilot,
DeepSeek R1). When using AI tools in contributions:

* Review all AI-generated code carefully before submitting — AI tools can produce plausible
  but incorrect instrument command strings.
* Do not submit AI-generated docstrings or comments verbatim without verifying accuracy
  against the instrument manual or source code.
* Disclose significant AI assistance in your pull request description.

See :doc:`adding_driver` for manual development, AI chat attachments, and repository
agent prompts with explicit file boundaries. Review the actual changed-file list
to ensure an agent has not modified shared framework code or existing files.
