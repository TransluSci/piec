Jupyter Notebook Examples
=========================

PIEC ships with a collection of Jupyter notebooks that demonstrate how to set up instruments,
configure measurements, run experiments, and analyze data. Notebooks offer more flexibility
than the GUIs and are a good starting point for custom experiment workflows.

Accessing the notebooks
-----------------------

Notebooks are located in the ``notebooks/`` directory of the repository. To open them:

1. Install Jupyter Lab if you haven't already:

   .. code-block:: console

      pip install jupyterlab

2. Navigate to the notebook directory and launch Jupyter Lab:

   .. code-block:: console

      jupyter lab

3. Open the desired ``.ipynb`` file from the Jupyter interface.

.. note::
  You may also be able to run your Jupyter notebook directly in your code editor.

Available notebooks
-------------------

* **FE_testing.ipynb** — Demonstrates hysteresis loop and PUND measurements on a ferroelectric
  device. 

* **amr.ipynb** — Sets up and runs an Anisotropic Magnetoresistance (AMR) sweep, showing how
  to control a stepper motor and lock-in amplifier together.

* **Arduino_Stepper_Example.ipynb** — Shows how to interface with an Arduino for stepper motor
  control.

.. todo::
   Add remaining notebooks with brief descriptions as they are created. Link to rendered
   versions (e.g., on GitHub or nbviewer) where possible.

How to use the notebooks
-------------------------

Each notebook is self-contained and includes comments explaining each step. The general
pattern is:

1. Import the relevant drivers and instantiate your instruments (or use virtual mode).
2. Create a measurement object with your parameters.
3. Call ``run_experiment()`` and inspect the saved output.

For more detail on how measurements work under the hood, see
:doc:`running_measurements`.