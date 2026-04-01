# PIEC Example Driver Template

This folder serves as the reference and template for developing new instrument drivers in the PIEC library. It is intentionally excluded from the package distribution to prevent it from being mistaken as a valid instrument driver.

## The 3-Level Architecture

PIEC uses a strict 3-level hierarchy to ensure all drivers are consistent and interchangeable.

1. **Level 1: Foundation (Instrument)**
   The base class for all instruments. It handles VISA connections and core library behavior.

2. **Level 2: Template Interface (example.py)**
   This file (sharing the folder's name) is a pure template. It defines the required methods and parameter boundaries (voltage, current, mode) for an entire instrument category. It does not implement any communication logic.

3. **Level 3: Model Implementation (specific_example.py)**
   The actual driver for a specific instrument model. It implements the Level 2 interface using hardware-specific commands.

### Convenience Classes (e.g., Scpi)

Scpi is a convenience implementation, not a structural level. It provides ready-made functions (like reset, clear, idn) that most SCPI-compliant instruments share. Level 3 drivers can inherit from Scpi to save time, provided the hardware actually supports those standard commands.

---

## How to Start a New Driver

For a comprehensive overview and strict coding rules, please refer to the Driver Development Guide.

1. **Choose a Type**: Determine which category folder (e.g. oscilloscope, dmm) the driver belongs in.
2. **Define the Interface**: Create or update the Level 2 interface file named after the folder (e.g., oscilloscope.py). Use example.py as a reference.
3. **Implement the Driver**: Create your specific instrument driver file directly within that folder (e.g., dsox3024a.py). Do not create manufacturer subfolders. Use specific_example.py as a template.
4. **Create a Test Notebook**: Use example_test.ipynb as a template for your functional verification suite.

---

## Folder Overview

| File | Role | Description |
|---|---|---|
| **example.py** | Level 2 Interface | The requirements template for this category. |
| **specific_example.py** | Level 3 Implementation | A concrete example of a working driver (SpecificExample). |
| **example_test.ipynb** | Functional Test | A sequential test suite to verify the entire hierarchy once implemented. |
| **DRIVER_DEVELOPMENT_GUIDE.md** | The Rules | The authoritative guide for adhering to PIEC architectural standards. |
