import numpy as np
import time
import pandas as pd
from piec.analysis.utilities import metadata_and_data_to_csv, create_measurement_filename
from piec.measurement.experiment import Experiment


class IVSweep(Experiment):
    """
    IV sweep measurement using a sourcemeter.
    Attributes:
        :sourcemeter: Sourcemeter driver object
        :v_start (float): Starting voltage in Volts
        :v_stop (float): Ending voltage in Volts
        :num_steps (int): Number of voltage steps in the sweep
        :current_compliance (float): Current compliance limit in Amps
        :dwell_time (float): Time to wait at each voltage step before measuring (seconds)
        :sense_mode (str): Sensing mode, '2W' or '4W'
        :save_dir (str): Directory path for data storage
        :data (pd.DataFrame): Captured IV data
        :metadata (pd.DataFrame): Measurement parameters and metadata
        :filename (str): Path of saved data file
    """

    mtype = "iv_sweep"
    _metadata_instruments = ('sourcemeter',)

    def __init__(self, sourcemeter, v_start=0.0, v_stop=1.0, num_steps=50,
                 current_compliance=0.1, dwell_time=0.1, sense_mode='2W',
                 save_dir=r'\\scratch'):
        """
        Initialize IV sweep measurement parameters.
        """
        self.sourcemeter = sourcemeter
        self.v_start = v_start
        self.v_stop = v_stop
        self.num_steps = num_steps
        self.current_compliance = current_compliance
        self.dwell_time = dwell_time
        self.sense_mode = sense_mode
        self.data = None
        self.filename = None
        super().__init__(save_dir=save_dir)

    def configure_sourcemeter(self):
        """
        Sets up voltage source mode at v_start with current compliance
        and configures the sensing mode.
        """
        self.sourcemeter.configure_voltage_source(
            voltage=self.v_start,
            current_compliance=self.current_compliance
        )
        self.sourcemeter.set_sense_mode(sense_mode=self.sense_mode)

    def sweep(self):
        """
        Ramps voltage from v_start to v_stop in num_steps steps.
        At each step, waits dwell_time seconds, then reads voltage and current.
        Results are stored in self.data as a pandas DataFrame.
        """
        voltages = np.linspace(self.v_start, self.v_stop, self.num_steps)
        measured_voltages = []
        measured_currents = []

        print(f"Starting IV sweep: {self.v_start}V to {self.v_stop}V in {self.num_steps} steps...")
        self.sourcemeter.output(on=True)

        for i, v in enumerate(voltages):
            self.sourcemeter.set_source_voltage(voltage=v)
            time.sleep(self.dwell_time)
            measured_v = self.sourcemeter.get_voltage()
            measured_i = self.sourcemeter.get_current()
            measured_voltages.append(measured_v)
            measured_currents.append(measured_i)

            if (i + 1) % max(1, self.num_steps // 10) == 0:
                print(f"  Step {i + 1}/{self.num_steps}: V={measured_v:.4f} V, I={measured_i:.6e} A")

        self.data = pd.DataFrame({
            "voltage (V)": measured_voltages,
            "current (A)": measured_currents
        })
        print("Sweep complete.")

    def save_data(self):
        """
        Save captured IV sweep data to CSV file.
        """
        self._update_metadata()

        if self.data is not None:
            notes = f"{str(self.v_start).replace('.', 'p')}V_to_{str(self.v_stop).replace('.', 'p')}V"
            self.filename = create_measurement_filename(self.save_dir, self.mtype, notes)
            metadata_and_data_to_csv(self.metadata, self.data, self.filename)
            print(f"IV sweep data saved to {self.filename}")
        else:
            print("No data to save. Run the sweep first.")

    def run_experiment(self):
        """
        Execute complete IV sweep workflow.
        """
        print("Running IV sweep experiment...")
        self.configure_sourcemeter()
        print("Sourcemeter configured.")
        self.sweep()
        self.sourcemeter.output(on=False)
        print("Output off.")
        self.save_data()
        self._update_history()
        print("Experiment complete.")
