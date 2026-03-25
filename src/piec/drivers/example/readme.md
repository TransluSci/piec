# 📘 PIEC Example Driver Template

This folder serves as the **gold-standard reference** and **template** for developing new instrument drivers in the PIEC library. It is intentionally excluded from the package (no `__init__.py`) to prevent it from being mistaken as a valid instrument driver.

## 🏛️ The 3-Level Architecture

PIEC uses a strict 3-level hierarchy to ensure all drivers are consistent and interchangeable.

1. **Level 1: Foundation (`Instrument`)**
   The base class for ALL instruments. It handles VISA connections and core library behavior.
2. **Level 2: Template Interface (`example.py`)**
   This file (sharing the folder's name) is a **pure template**. It defines the required methods and parameter boundaries (`voltage`, `current`, `mode`) for an entire instrument category. It does **not** implement any communication logic.
3. **Level 3: Model Implementation (`specific_example.py`)**
   The actual driver for a specific instrument model. It implements the Level 2 interface using hardware-specific commands.

### 💡 Convenience Classes (e.g., `Scpi`)
`Scpi` is a **convenience implementation**, not a structural level. It provides ready-made functions (like `reset`, `clear`, `idn`) that most SCPI-compliant instruments share. Level 3 drivers can inherit from `Scpi` to save time, provided the hardware actually supports those standard commands.

---

## 🚀 How to Start a New Driver

For a comprehensive overview and strict coding rules, please refer to the **[Driver Development Guide](DRIVER_DEVELOPMENT_GUIDE.md)**.

### 🤖 Instructions for AI Assistants
If you are using an AI to help generate a driver, provide it with the following context:

* **If creating a NEW Instrument Type (Level 2):**
  - Point the AI to `example.py` as the structural template.
  - Explain that it should define only the "vocabulary" (methods and class attributes) with no implementation logic.
* **If creating a SPECIFIC Instrument Model (Level 3):**
  - Point the AI to the matching Category Template (e.g., `oscilloscope.py`) to see the required interface.
  - Point the AI to `specific_example.py` to see the recommended implementation pattern (constructor queries, command mapping, and protocol inheritance).

---

## 📂 Folder Overview

| File | Role | Description |
|---|---|---|
| **`example.py`** | **Level 2 Interface** | The requirements template for this category. |
| **`specific_example.py`** | **Level 3 Implementation** | A concrete example of a working driver (`AnnotatedGenericDriver`). |
| **`example_test.ipynb`** | **Functional Test** | A sequential test suite to verify the entire hierarchy once implemented. |
| **`DRIVER_DEVELOPMENT_GUIDE.md`** | **The Rules** | The authoritative guide for adhering to PIEC architectural standards. |
