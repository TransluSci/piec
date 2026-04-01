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

.. todo::
   Document the test structure: where tests live, how to run them locally, and what a good
   test for a driver or measurement looks like. Include instructions for running tests against
   virtual instruments so contributors don't need physical hardware.

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