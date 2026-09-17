"""
Amplifier frequency response (Bode plot) using the DG812 (source) and the
Analog Discovery 2 (dual-channel scope), driven through piec's
FrequencyResponse measurement class.

Wiring:
    DG812 CH<AWG_CHANNEL>  --> amplifier input
    AD2 scope CH1           -- probes the amplifier INPUT (same node the DG812 drives)
    AD2 scope CH2           -- probes the amplifier OUTPUT

Gain/phase are computed directly from the two simultaneously-sampled scope
channels each frequency step, so the result is immune to DG812 output-level
drift or source/load impedance mismatch -- see
piec.measurement.frequency_response.FrequencyResponse for details.

Usage:
    python hardware_validation/run_amplifier_bode_plot.py \
        [--awg-address VISA_ADDR] [--ad2-index N] \
        [--f-start 10] [--f-stop 25e6] [--points-per-decade 10] \
        [--amplitude 0.5] [--save-dir DIR]

Note: the DG812 tops out at 25 MHz sine and the AD2 scope inputs are rated
to ~30 MHz analog bandwidth, so a sweep can't usefully go past ~25 MHz even
if your simulation/target curve extends further (e.g. to 100 MHz).
"""
import argparse
import sys

from piec.drivers.autodetect import autodetect, _safe_close
from piec.drivers.awg.rigol_dg812 import RigolDG812
from piec.drivers.analog_discovery import AnalogDiscovery
from piec.drivers.oscilloscope.analog_discovery_2 import AnalogDiscovery2Oscilloscope
from piec.measurement.frequency_response import FrequencyResponse
from piec.analysis.frequency_response import plot_bode


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--awg-address", default=None,
                         help="VISA resource string for the DG812 (default: autodetect)")
    parser.add_argument("--ad2-index", default=-1, type=int,
                         help="WaveForms device index for the Analog Discovery 2 (default: -1, first device)")
    parser.add_argument("--awg-channel", default=1, type=int, help="DG812 channel driving the amplifier input")
    parser.add_argument("--input-scope-channel", default=1, type=int, help="AD2 channel probing the amplifier input")
    parser.add_argument("--output-scope-channel", default=2, type=int, help="AD2 channel probing the amplifier output")
    parser.add_argument("--f-start", default=10.0, type=float, help="Sweep start frequency, Hz")
    parser.add_argument("--f-stop", default=25e6, type=float, help="Sweep stop frequency, Hz (DG812 max ~25 MHz)")
    parser.add_argument("--points-per-decade", default=10, type=int)
    parser.add_argument("--amplitude", default=0.5, type=float, help="Drive amplitude, Vpp")
    parser.add_argument("--input-range", default=2.0, type=float, help="AD2 input-channel full-scale range, V")
    parser.add_argument("--output-range", default=10.0, type=float, help="AD2 output-channel full-scale range, V")
    parser.add_argument("--save-dir", default=r".\\bode_data", help="Directory to save CSV/plot into")
    args = parser.parse_args()

    print("=" * 70)
    print("Amplifier Bode plot: DG812 + Analog Discovery 2")
    print(f"  DG812 CH{args.awg_channel} -> amplifier input")
    print(f"  AD2 scope CH{args.input_scope_channel} -> amplifier input (reference)")
    print(f"  AD2 scope CH{args.output_scope_channel} -> amplifier output")
    print("=" * 70)

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

    fr = FrequencyResponse(
        awg=awg, osc=scope,
        awg_channel=args.awg_channel,
        input_channel=args.input_scope_channel,
        output_channel=args.output_scope_channel,
        f_start=args.f_start, f_stop=args.f_stop,
        points_per_decade=args.points_per_decade,
        amplitude=args.amplitude,
        input_range=args.input_range, output_range=args.output_range,
        save_dir=args.save_dir,
    )

    try:
        fr.run_experiment()
    finally:
        _safe_close(awg)
        device.close()

    if fr.data is not None and not fr.data.empty:
        plot_bode(fr.data, title="Amplifier Frequency Response",
                  path=fr.filename, show_plots=True, save_plots=True)
    else:
        print("No data captured; skipping plot.")


if __name__ == "__main__":
    main()
