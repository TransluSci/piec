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
3. Add or update tests for any changed functionality (see :ref:`test-functions`).
4. Open a pull request against ``master`` with a clear description of what changed and why.

.. _test-functions:

Test functions
--------------

**Where tests live**

All tests are in the ``tests/`` directory at the repository root:

* ``test_imports.py`` — tests that every public module and subpackage imports
  without error.
* ``test_instrument_core.py`` — unit tests for the
  :class:`~piec.drivers.instrument.Instrument` base class and its helper functions.
* ``test_measurement_pipeline.py`` — integration tests for measurement classes. Each
  measurement goes through its complete pipeline.

**Running tests locally**

Install the package in editable mode with its development dependencies, then run
pytest from the repository root::

   pip install -e ".[dev]"
   pytest tests/ -v

Run a single file or test class::

   pytest tests/test_measurement_pipeline.py -v
   pytest tests/test_measurement_pipeline.py::TestHysteresisFullPipeline -v

**Testing without physical hardware**

Every driver class has a ``Virtual`` counterpart (e.g. ``VirtualAwg``,
``VirtualScope``) that emulates the hardware API entirely in memory. Tests import
these virtual drivers and never require an instrument to be connected. The CI
workflow runs the same ``pytest`` command, so all tests must pass using virtual
drivers only.

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

When adding a new driver, copy ``src/piec/drivers/example/example_test.ipynb`` as
your starting template and add a cell for each method your driver implements. Run
each cell sequentially from top to bottom and confirm the expected behaviour before
submitting a pull request.


AI use guidelines
-----------------

piec development has made use of AI coding assistants (Google Gemini, GitHub Copilot,
DeepSeek R1). When using AI tools in contributions:

* Review all AI-generated code carefully before submitting — AI tools can produce plausible
  but incorrect instrument command strings.
* Do not submit AI-generated docstrings or comments verbatim without verifying accuracy
  against the instrument manual or source code.
* Disclose significant AI assistance in your pull request description.

.. todo::
   Add recommended prompts for common contribution tasks (e.g., scaffolding a new driver,
   writing a virtual mode response).