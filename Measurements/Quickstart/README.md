# Your first PIEC experiment

- [Browser notebook](quick_start.ipynb): fully virtual, used by Binder.
- [Local notebook](quick_start_local.ipynb): run the imports, then choose the virtual
  or physical section. Work through sine, square, and ramp one cell at a time.
- **Local GUI**: the same experiment using PIEC's familiar settings, plot, run
  button, and message panel. No notebook needed.

From the repository root:

```bash
python -m pip install -e .
python Measurements/Quickstart/awg_scope_GUI.py
```

The GUI requires a local desktop with Tkinter (included with standard Windows
Python; some Linux installations need their distribution's Python Tk package).
Start in **Virtual** mode, click **Capture**, then choose Square and Ramp.
**Export CSV** saves the last successful scope capture. The amplitude control
uses Vpp in both modes; 2 Vpp corresponds to the notebook's 1 V virtual peak.

**Physical** mode uses a Keysight 81150A and DSOX3024A. Enter both VISA addresses
and connect AWG CH1 directly to scope CH1. Set the AWG to continuous output
(burst off), with Vpp units. The GUI configures 50 Ω source/load/input settings,
DC coupling, and a CH1 rising-edge trigger at zero volts. No external trigger
cable is needed. Hardware operation has not been bench-validated.

Each capture turns output off and closes the hardware sessions. Closing the GUI
during a capture waits for its cleanup. Compare a physical capture with the
virtual **applied waveform**; the virtual scope response includes a ferroelectric
sample, unlike the direct hardware connection.

The quick-start GUI deliberately covers only these two physical models and a
small parameter range. For broader experiments, see the AMR and ferroelectric
GUIs under `Measurements/`.
