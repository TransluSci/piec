# Your first PIEC experiment

- [Browser notebook](quick_start.ipynb): fully virtual, used by Binder.
- [Local notebook](quick_start_local.ipynb): run the imports, then choose the virtual
  or physical section. Work through sine, square, and ramp one cell at a time.
- **Local GUI**: the same experiment using PIEC's familiar settings, plot, run
  button, and message panel. No notebook needed.

From the repository root:

```bash
python -m pip install -e .
python Measurements/Quickstart/quick_start_local_GUI.py
```

The GUI requires a local desktop with Tkinter (included with standard Windows Python; some Linux installations need their distribution's Python Tk package).

- **Instrument Selection**: Dropdowns allow choosing `VIRTUAL` or connected VISA instruments. Click **Refresh** to rescan VISA ports, or **Autodetect** to automatically discover connected AWG and Oscilloscope hardware.
- **Signal Configuration**: Select **Sine**, **Square**, or **Ramp** waveform, and set frequency and amplitude.
- **Capture**: Click **Capture Waveform** (or press `Ctrl+Enter`) to run the acquisition.
- **Export**: Check **Save CSV on capture?** to automatically save data to your chosen directory.
