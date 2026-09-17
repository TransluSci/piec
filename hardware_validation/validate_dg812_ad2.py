"""
Hardware validation for RigolDG812 (AWG) + AnalogDiscovery2Oscilloscope (scope).

This is NOT a pytest unit test -- it drives real, physically connected
instruments and is meant to be run manually:

    python hardware_validation/validate_dg812_ad2.py

Wiring assumed:
    DG812 output CH<AWG_CHANNEL> --BNC/coax--> Analog Discovery 2 scope CH<SCOPE_CHANNEL>

If your wiring differs, change AWG_CHANNEL / SCOPE_CHANNEL below.

What it does:
    1. Connects to the DG812 (VISA, autodetected via AUTODETECT_ID="DG812")
       and to the Analog Discovery 2 (WaveForms SDK, first device).
    2. Outputs a DC level on the DG812 and measures it on the scope to derive
       a calibration `scale` factor (measured/commanded). This absorbs any
       source/load impedance mismatch between the DG812's output stage and
       the AD2's fixed 1 MOhm scope input (e.g. if the DG812's front-panel
       "output load" is set to 50 ohm while actually driving a high-Z scope
       input, `scale` will land near 2.0 -- that's expected, not a bug).
    3. Runs the DG812 through SIN / SQU / RAMP / PULS waveforms at a couple
       of frequencies, reads each back on the scope, and checks the
       commanded vs. measured frequency, amplitude, and shape (duty cycle /
       symmetry) against tolerances.
    4. Confirms output(on=False) actually silences the channel.
    5. Prints a PASS/FAIL table and exits with status 0 only if everything
       passed.

Exit code: 0 if all checks passed, 1 otherwise.
"""
import sys
import time
import argparse

import numpy as np

from piec.drivers.autodetect import autodetect, _safe_close
from piec.drivers.awg.rigol_dg812 import RigolDG812
from piec.drivers.analog_discovery import AnalogDiscovery
from piec.drivers.oscilloscope.analog_discovery_2 import AnalogDiscovery2Oscilloscope


# --- Wiring configuration ---
AWG_CHANNEL = 1
SCOPE_CHANNEL = 1

RESULTS = []


def check(label, expected, measured, rel_tol=0.1, abs_tol=0.0):
    tol = max(abs_tol, rel_tol * abs(expected))
    ok = abs(measured - expected) <= tol
    status = "PASS" if ok else "FAIL"
    print(f"  [{status}] {label}: expected={expected:.6g}  measured={measured:.6g}  "
          f"(tol=+/-{tol:.4g})")
    RESULTS.append((label, ok))
    return ok


def note(label, value):
    print(f"  [INFO] {label}: {value}")


# --- Waveform measurement helpers ---

def estimate_frequency(t, y):
    """
    Mid-level rising-edge crossing period estimate, with linear
    interpolation between samples for sub-sample-accurate crossing times.

    More robust than an FFT-peak estimate for narrow-duty-cycle pulse
    trains: a non-integer number of captured periods causes spectral
    leakage that can make a harmonic outrank the true fundamental in the
    FFT magnitude spectrum, while edge-crossing timing is unaffected by
    capture-window/period alignment.
    """
    y = np.asarray(y, dtype=float)
    thresh = (np.max(y) + np.min(y)) / 2.0
    above = y > thresh
    crossing_idx = np.where(np.diff(above.astype(int)) == 1)[0]
    if len(crossing_idx) < 2:
        return 0.0

    cross_times = []
    for idx in crossing_idx:
        y0, y1 = y[idx], y[idx + 1]
        t0, t1 = t[idx], t[idx + 1]
        frac = (thresh - y0) / (y1 - y0) if y1 != y0 else 0.0
        cross_times.append(t0 + frac * (t1 - t0))

    periods = np.diff(cross_times)
    return 1.0 / float(np.mean(periods))


def vpp(y):
    return float(np.max(y) - np.min(y))


def mean_v(y):
    return float(np.mean(y))


def duty_cycle_percent(y):
    """Fraction of samples above the mid-level threshold, as a percentage."""
    thresh = (np.max(y) + np.min(y)) / 2.0
    return float(np.mean(np.asarray(y) > thresh) * 100.0)


def ramp_rising_fraction_percent(y):
    """Fraction of sample-to-sample steps that are rising, as a percentage.

    Approximates ramp "symmetry" (piec convention: 100% = rising sawtooth,
    0% = falling sawtooth, 50% = triangle).
    """
    dy = np.diff(np.asarray(y, dtype=float))
    return float(np.mean(dy > 0) * 100.0)


def configure_scope_for_frequency(scope, channel, freq, points=8192,
                                   samples_per_period=100, max_sample_rate=20e6):
    sample_rate = min(freq * samples_per_period, max_sample_rate)
    total_time = points / sample_rate
    tdiv = total_time / 10.0
    scope.configure_acquisition(channel=channel, acquisition_mode="NORM", acquisition_points=points)
    scope.set_horizontal_scale(tdiv, total_time)
    return total_time


def acquire(scope, channel, settle=0.2):
    time.sleep(settle)  # let the AWG output settle / scope re-arm
    df = scope.get_data()
    t = df["Time"].to_numpy()
    y = df[f"Channel {channel}"].to_numpy()
    return t, y


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--awg-address", default=None,
                         help="VISA resource string for the DG812 (default: autodetect)")
    parser.add_argument("--ad2-index", default=-1, type=int,
                         help="WaveForms device index for the Analog Discovery 2 (default: -1, first device)")
    args = parser.parse_args()

    print("=" * 70)
    print("DG812 + Analog Discovery 2 hardware validation")
    print(f"Wiring: DG812 CH{AWG_CHANNEL}  -->  AD2 scope CH{SCOPE_CHANNEL}")
    print("=" * 70)

    # --- Connect ---
    print("\n--- Connecting ---")
    if args.awg_address:
        awg = RigolDG812(address=args.awg_address, verbose=True)
    else:
        awg = autodetect(RigolDG812, verbose=True)
        if awg is None:
            print("ERROR: Could not find a DG812 over VISA. Pass --awg-address explicitly, "
                  "or check the instrument's USB connection (Windows Device Manager).")
            sys.exit(2)
    print("DG812 IDN:", awg.idn())

    device = AnalogDiscovery(address=args.ad2_index, verbose=True)
    scope = AnalogDiscovery2Oscilloscope(device, verbose=True)
    print("AD2 IDN:", scope.idn())

    scope.toggle_channel(SCOPE_CHANNEL, on=True)
    scope.set_input_coupling(SCOPE_CHANNEL, "DC")
    scope.set_probe_attenuation(SCOPE_CHANNEL, 1.0)
    scope.set_trigger_source(SCOPE_CHANNEL)
    scope.set_trigger_slope("POS")
    scope.set_trigger_mode("EDGE")
    scope.set_trigger_sweep("AUTO")

    scale = 1.0

    try:
        # --- Test 1: DC level + amplitude calibration ---
        print("\n--- Test 1: DC level / amplitude calibration ---")
        awg.set_waveform(AWG_CHANNEL, "DC")
        awg.set_offset(AWG_CHANNEL, 1.0)
        awg.output(AWG_CHANNEL, True)

        scope.set_vertical_scale(SCOPE_CHANNEL, vdiv=None, y_range=20.0)
        scope.set_vertical_position(SCOPE_CHANNEL, 0.0)
        scope.set_trigger_level(0.5)
        configure_scope_for_frequency(scope, SCOPE_CHANNEL, freq=1000)

        t, y = acquire(scope, SCOPE_CHANNEL)
        measured_dc = mean_v(y)
        note("Measured DC level for 1.0V commanded", measured_dc)

        if abs(measured_dc) > 1e-6:
            scale = measured_dc / 1.0
        note("Derived amplitude calibration scale (measured/commanded)", scale)
        if not (0.4 <= scale <= 2.6):
            print("  [WARN] Calibration scale is far from 1x or 2x -- check wiring/grounding "
                  "before trusting amplitude checks below.")

        awg.set_offset(AWG_CHANNEL, 0.0)

        # --- Test 2: Sine wave, 1 kHz ---
        print("\n--- Test 2: Sine wave @ 1 kHz, 2 Vpp ---")
        awg.configure_waveform(AWG_CHANNEL, "SIN", frequency=1000.0, amplitude=2.0, offset=0.0)
        awg.output(AWG_CHANNEL, True)
        configure_scope_for_frequency(scope, SCOPE_CHANNEL, freq=1000.0)
        t, y = acquire(scope, SCOPE_CHANNEL)
        check("Sine frequency (Hz)", 1000.0, estimate_frequency(t, y), rel_tol=0.02)
        check("Sine Vpp (V)", 2.0 * scale, vpp(y), rel_tol=0.15)
        check("Sine mean/offset (V)", 0.0 * scale, mean_v(y), rel_tol=0.15, abs_tol=0.2)

        # --- Test 3: Sine wave, 50 kHz (frequency-setting sanity check) ---
        print("\n--- Test 3: Sine wave @ 50 kHz, 1 Vpp ---")
        awg.configure_waveform(AWG_CHANNEL, "SIN", frequency=50_000.0, amplitude=1.0, offset=0.0)
        configure_scope_for_frequency(scope, SCOPE_CHANNEL, freq=50_000.0)
        t, y = acquire(scope, SCOPE_CHANNEL)
        check("Sine frequency (Hz)", 50_000.0, estimate_frequency(t, y), rel_tol=0.02)
        check("Sine Vpp (V)", 1.0 * scale, vpp(y), rel_tol=0.15)

        # --- Test 4: Square wave, duty cycle ---
        print("\n--- Test 4: Square wave @ 2 kHz, 30% duty cycle ---")
        awg.configure_waveform(AWG_CHANNEL, "SQU", frequency=2000.0, amplitude=2.0, offset=0.0)
        awg.set_square_duty_cycle(AWG_CHANNEL, 30.0)
        configure_scope_for_frequency(scope, SCOPE_CHANNEL, freq=2000.0)
        t, y = acquire(scope, SCOPE_CHANNEL)
        check("Square frequency (Hz)", 2000.0, estimate_frequency(t, y), rel_tol=0.02)
        check("Square Vpp (V)", 2.0 * scale, vpp(y), rel_tol=0.15)
        check("Square duty cycle (%)", 30.0, duty_cycle_percent(y), rel_tol=0, abs_tol=8.0)

        # --- Test 5: Ramp / triangle symmetry ---
        print("\n--- Test 5: Ramp @ 1 kHz, 50% symmetry (triangle) ---")
        awg.configure_waveform(AWG_CHANNEL, "RAMP", frequency=1000.0, amplitude=2.0, offset=0.0)
        awg.set_ramp_symmetry(AWG_CHANNEL, 50.0)
        configure_scope_for_frequency(scope, SCOPE_CHANNEL, freq=1000.0)
        t, y = acquire(scope, SCOPE_CHANNEL)
        check("Ramp frequency (Hz)", 1000.0, estimate_frequency(t, y), rel_tol=0.02)
        check("Ramp Vpp (V)", 2.0 * scale, vpp(y), rel_tol=0.15)
        check("Ramp rising fraction (%)", 50.0, ramp_rising_fraction_percent(y), rel_tol=0, abs_tol=10.0)

        print("\n--- Test 6: Ramp @ 1 kHz, 90% symmetry (near-sawtooth) ---")
        awg.set_ramp_symmetry(AWG_CHANNEL, 90.0)
        t, y = acquire(scope, SCOPE_CHANNEL)
        check("Ramp rising fraction (%)", 90.0, ramp_rising_fraction_percent(y), rel_tol=0, abs_tol=10.0)

        # --- Test 7: Pulse width ---
        print("\n--- Test 7: Pulse @ 1 kHz, 100us width (10% duty), 1us edges ---")
        # configure_pulse() switches the DG812 into PULS mode internally,
        # which resets its timing base -- set_frequency must come AFTER, not before.
        awg.configure_pulse(AWG_CHANNEL, pulse_width=100e-6, pulse_delay=0.0,
                             rise_time=1e-6, fall_time=1e-6)
        awg.set_frequency(AWG_CHANNEL, 1000.0)
        awg.set_amplitude(AWG_CHANNEL, 2.0)
        awg.set_offset(AWG_CHANNEL, 1.0)  # 0V-2V pulse for a clean mid threshold
        configure_scope_for_frequency(scope, SCOPE_CHANNEL, freq=1000.0, samples_per_period=500)
        t, y = acquire(scope, SCOPE_CHANNEL)
        check("Pulse frequency (Hz)", 1000.0, estimate_frequency(t, y), rel_tol=0.05)
        expected_duty = 100e-6 * 1000.0 * 100.0  # width * freq * 100%
        check("Pulse duty cycle (%)", expected_duty, duty_cycle_percent(y), rel_tol=0, abs_tol=5.0)

        # --- Test 8: Output off actually silences the channel ---
        print("\n--- Test 8: output(on=False) silences the channel ---")
        awg.configure_waveform(AWG_CHANNEL, "SIN", frequency=1000.0, amplitude=2.0, offset=0.0)
        awg.output(AWG_CHANNEL, True)
        configure_scope_for_frequency(scope, SCOPE_CHANNEL, freq=1000.0)
        t, y = acquire(scope, SCOPE_CHANNEL)
        note("Vpp with output ON", vpp(y))

        awg.output(AWG_CHANNEL, False)
        t, y = acquire(scope, SCOPE_CHANNEL)
        off_vpp = vpp(y)
        note("Vpp with output OFF", off_vpp)
        ok = off_vpp < 0.5
        RESULTS.append(("Output OFF silences channel", ok))
        print(f"  [{'PASS' if ok else 'FAIL'}] Output OFF silences channel "
              f"(measured Vpp={off_vpp:.4g} V, threshold=0.5V)")

    finally:
        try:
            awg.output(AWG_CHANNEL, False)
        except Exception:
            pass
        # RigolDG812/Scpi don't implement close() themselves (a pre-existing
        # gap in the base Scpi class); fall back to closing the underlying
        # PyVISA resource directly, same as autodetect.py's own cleanup path.
        _safe_close(awg)
        device.close()

    # --- Summary ---
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    n_pass = sum(1 for _, ok in RESULTS if ok)
    n_total = len(RESULTS)
    for label, ok in RESULTS:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    print(f"\n{n_pass}/{n_total} checks passed.")

    if n_pass == n_total:
        print("ALL CHECKS PASSED")
        sys.exit(0)
    else:
        print("SOME CHECKS FAILED")
        sys.exit(1)


if __name__ == "__main__":
    main()
