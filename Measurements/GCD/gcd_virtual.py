"""Run GCD with a simulated battery; this entry point only opens VIRTUAL."""

import argparse

from piec.drivers.sourcemeter.keithley2400 import Keithley2400
from piec.drivers.virtual_instrument import VirtualInstrument
from piec.measurement.gcd import GCD
from piec.simulation.battery import Battery


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--current', type=float, default=0.01, help='Current magnitude (A)')
    parser.add_argument('--voltage-lower', type=float, default=3.1, help='Discharge cutoff (V)')
    parser.add_argument('--voltage-upper', type=float, default=4.1, help='Charge cutoff (V)')
    parser.add_argument('--cycles', type=int, default=3)
    parser.add_argument('--sample-interval', type=float, default=1.0, help='Simulated seconds')
    parser.add_argument('--max-half-cycle-time', type=float, default=1000.0, help='Simulated seconds')
    parser.add_argument('--voltage-compliance', type=float, default=5.0, help='SMU voltage limit (V)')
    parser.add_argument('--capacity-ah', type=float, default=0.001)
    parser.add_argument('--initial-soc', type=float, default=0.2)
    parser.add_argument('--save-dir', default='scratch/gcd')
    parser.add_argument('--show-plots', action='store_true')
    args = parser.parse_args()

    smu = Keithley2400('VIRTUAL')
    original_sample = smu.sample
    experiment = None
    try:
        smu.sample = Battery(capacity_ah=args.capacity_ah, initial_soc=args.initial_soc)
        experiment = GCD(
            smu, current=args.current, voltage_lower=args.voltage_lower,
            voltage_upper=args.voltage_upper, n_cycles=args.cycles,
            sample_interval=args.sample_interval,
            max_half_cycle_time=args.max_half_cycle_time,
            voltage_compliance=args.voltage_compliance, virtual_time=True,
            save_dir=args.save_dir, show_plots=args.show_plots, save_plots=True)
        experiment.run_experiment()
        print(f'Completed {experiment.completed_cycles} cycles in '
              f'{experiment.data["time (s)"].iloc[-1]:.1f} simulated seconds.')
        print(f'Data: {experiment.filename}')
        print(f'Plot: {experiment.plot_filename}')
    finally:
        try:
            if experiment is not None:
                experiment.safe_close()
        finally:
            VirtualInstrument.set_virtual_sample(original_sample)


if __name__ == '__main__':
    main()
