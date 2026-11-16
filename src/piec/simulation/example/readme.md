# PIEC Example Simulation Template

Reference template for adding new simulated sample categories and models, mirroring `piec/drivers/example/`.

## The 3-Level Architecture

1. **Level 1 (`sample.py` / `Sample`)**: Holds `name`, `parameter_dict`, and default physical stimuli/observables (`set_voltage`, `set_current`, `set_field`, `set_angle`, `apply_waveform` $\to$ `get_voltage`, `get_current`, `get_resistance`, `get_field`, `get_angle`, `get_waveform`).
2. **Level 2 (`<category>/<category>.py`, e.g. `example.py`)**: Declares the required public contract methods for that category with `raise NotImplementedError` stubs and no physics implementation.
3. **Level 3 (`<category>/<model>.py`, e.g. `specific_example.py`)**: Implements those Level 2 public methods directly using scalar constructor defaults and/or `parameter_dict`.

## How to Start a New Simulation Model

1. **Choose or Create a Category**: Pick an existing folder (`resistor`, `fe_material`, `magnetic/moke`, `magnetic/amr`) or create a new `<category>/` directory with an empty `__init__.py`.
2. **Define the Level 2 Contract**: In `<category>/<category>.py`, subclass `Sample` and override the relevant physical I/O methods with `raise NotImplementedError`.
3. **Implement the Level 3 Model**: In `<category>/<model>.py`, subclass the Level 2 contract and implement those methods directly.
4. **Verify**: Run `pytest tests/test_sample.py` — discovery and signature checks are automatic.