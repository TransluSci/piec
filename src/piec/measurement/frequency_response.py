import inspect
import time

import numpy as np
import pandas as pd

from piec.analysis.utilities import metadata_and_data_to_csv, create_measurement_filename


class FrequencyResponse:
    """
    Frequency response (Bode plot) measurement using an AWG to drive a
    device under test and an oscilloscope to read its input and output
    simultaneously.

    Sweeps a sine wave in log-spaced frequency steps from f_start to f_stop.
    At each step, the AWG channel's own output is treated as the reference
    input, or -- when the DUT's input is separately wired into the
    oscilloscope's input_channel -- the actually-measured input is used as
    the reference instead. Either way, gain/phase are computed from
    input_channel vs. output_channel captured on the *same* oscilloscope
    trigger event, so results are immune to AWG output-level drift or
    source/load impedance mismatches.

    Works with any Oscilloscope driver that implements get_multi_channel_data()
    (checked at construction time -- see below); it isn't tied to any one
    scope model. Acquisition sizing (_configure_scope_for_frequency) reads
    each connected scope's own declared max_sample_rate and
    acquisition_points class attributes rather than assuming particular
    hardware numbers, so it adapts automatically whether osc is e.g. an
    AnalogDiscovery2Oscilloscope (100 MS/s, variable up-to-8192-point
    buffer) or a TektronixTBS1154 (1 GS/s, fixed 2500-point buffer) --
    see those two drivers for a concrete comparison of what each brings to
    this measurement:
      - Analog Discovery 2: 14-bit vertical resolution (vs. the TBS1154's
        8-bit) and near-zero per-call overhead (direct ctypes calls into the
        WaveForms SDK, not SCPI-over-VISA round trips), so it's
        substantially faster across the low/mid-frequency portion of a
        sweep where per-point communication overhead dominates.
      - Tektronix TBS1154: much higher analog bandwidth (~150 MHz vs. the
        AD2's ~30 MHz) and 10x the sample rate, so it stays accurate much
        closer to the top of a sweep that reaches into the tens of MHz,
        where the AD2's own front-end starts to become the limiting factor
        rather than the DUT.

    Attributes:
        :awg: AWG driver object (drives the DUT input)
        :osc: Oscilloscope driver object (reads DUT input and output)
        :awg_channel (int): AWG channel driving the DUT
        :input_channel (int): Oscilloscope channel on the DUT's input
        :output_channel (int): Oscilloscope channel on the DUT's output
        :f_start (float): Sweep start frequency in Hz
        :f_stop (float): Sweep stop frequency in Hz
        :points_per_decade (int): Log-spaced frequency points per decade
        :amplitude (float): AWG sine amplitude in Vpp
        :cycles_per_point (float): Target number of signal periods captured per point
        :min_capture_time (float): Floor on the capture window, seconds
        :max_capture_time (float): Ceiling on the capture window, seconds (bounds low-frequency sweep time)
        :settle_cycles (float): Periods to wait after retuning frequency before capturing
        :input_range (float): Oscilloscope input_channel full-scale range, volts.
            Starting value when autorange is True; otherwise fixed for the whole sweep.
        :output_range (float): Oscilloscope output_channel full-scale range, volts.
            Starting value when autorange is True; otherwise fixed for the whole sweep.
        :autorange (bool): If True (default), each channel's range is resized after
            every point based on the peak amplitude just measured, so a sweep spanning
            a huge dynamic range (e.g. a filter's passband down through its rolloff)
            doesn't have to live with one fixed range the whole way through.
        :range_headroom (float): Autorange target: the new range's peak-to-peak span
            is set to `range_headroom` times the last measured peak-to-peak amplitude.
        :min_range (float): Autorange floor, volts.
        :max_range (float): Autorange ceiling, volts.
        :save_dir (str): Directory path for data storage
        :data (pd.DataFrame): Frequency, magnitude (dB), phase (deg), and raw Vin/Vout amplitudes
        :metadata (pd.DataFrame): Measurement parameters and metadata
        :filename (str): Path of saved data file
    """

    mtype = "frequency_response"

    def __init__(self, awg, osc, awg_channel=1, input_channel=1, output_channel=2,
                 f_start=10.0, f_stop=1e6, points_per_decade=10,
                 amplitude=1.0, cycles_per_point=10.0, min_capture_time=2e-3,
                 max_capture_time=1.0, settle_cycles=3.0,
                 input_range=10.0, output_range=10.0,
                 autorange=True, range_headroom=4.0, min_range=0.02, max_range=100.0,
                 save_dir=r'\\scratch'):
        if inspect.getattr_static(osc, 'get_multi_channel_data', None) is None:
            raise TypeError(
                f"{osc.__class__.__name__} does not implement get_multi_channel_data(), "
                "which FrequencyResponse requires for phase-accurate simultaneous "
                "dual-channel capture. Use an oscilloscope driver that supports it "
                "(e.g. AnalogDiscovery2Oscilloscope)."
            )

        self.awg = awg
        self.osc = osc
        self.awg_channel = awg_channel
        self.input_channel = input_channel
        self.output_channel = output_channel
        self.f_start = f_start
        self.f_stop = f_stop
        self.points_per_decade = points_per_decade
        self.amplitude = amplitude
        self.cycles_per_point = cycles_per_point
        self.min_capture_time = min_capture_time
        self.max_capture_time = max_capture_time
        self.settle_cycles = settle_cycles
        self.input_range = input_range
        self.output_range = output_range
        self.autorange = autorange
        self.range_headroom = range_headroom
        self.min_range = min_range
        self.max_range = max_range
        self.save_dir = save_dir
        self.data = None
        self.filename = None
        self._update_metadata()

    def _update_metadata(self):
        """
        Update metadata with current measurement parameters.
        Captures instrument IDs, sweep parameters, and timestamp.
        """
        params = {key: value for key, value in self.__dict__.items()
                  if not key.startswith('_') and
                  not callable(value) and
                  key not in ['awg', 'osc', 'data', 'metadata']}

        self.metadata = pd.DataFrame(params, index=[0])
        self.metadata['awg'] = self.awg.idn()
        self.metadata['osc'] = self.osc.idn()
        self.metadata['mtype'] = self.mtype
        self.metadata['timestamp'] = time.time()
        self.metadata['processed'] = False

    def configure_scope(self):
        """
        Enables and configures the input/output oscilloscope channels and
        sets up a free-running (AUTO) acquisition -- exact trigger phase
        doesn't matter here since gain/phase are extracted from the two
        simultaneously-captured channels, not from a trigger reference.
        """
        for channel, channel_range in [(self.input_channel, self.input_range),
                                        (self.output_channel, self.output_range)]:
            self.osc.toggle_channel(channel, on=True)
            self.osc.set_input_coupling(channel, "DC")
            self.osc.set_probe_attenuation(channel, 1.0)
            self.osc.set_vertical_scale(channel, vdiv=None, y_range=channel_range)
            # Center both traces (0 = no vertical offset on every Oscilloscope
            # driver). Without this, a channel left off-center from prior use
            # only has half its configured range before clipping in one
            # direction -- autoranging sizes the range correctly, but that
            # doesn't help if the trace isn't centered within it.
            self.osc.set_vertical_position(channel, 0.0)
        self.osc.set_trigger_sweep("AUTO")

    def configure_awg(self):
        """
        Configures the AWG to output a sine wave at the sweep's starting
        frequency and enables the output.
        """
        self.awg.configure_waveform(self.awg_channel, "SIN",
                                     frequency=self.f_start, amplitude=self.amplitude, offset=0.0)
        self.awg.output(self.awg_channel, True)

    def _frequency_points(self):
        decades = np.log10(self.f_stop / self.f_start)
        n_points = max(2, int(round(decades * self.points_per_decade)) + 1)
        return np.logspace(np.log10(self.f_start), np.log10(self.f_stop), n_points)

    # Oversampling target: how many samples per signal period we'd *like* to
    # capture, before any particular scope's hardware limits get applied.
    # This class has no opinion on which oscilloscope is connected -- AD2,
    # a Tektronix TBS1000, or anything else -- so it never hardcodes a
    # sample-rate ceiling or point-count budget itself. Instead it reads
    # each connected scope's own declared limits (its `max_sample_rate` and
    # `acquisition_points` class attributes -- the same capability-
    # declaration convention every piec Oscilloscope driver already uses)
    # and sizes the acquisition around whatever hardware is actually there.
    _SAMPLES_PER_PERIOD = 50

    # Used only when a driver doesn't declare max_sample_rate (i.e. it's
    # still None on the base Oscilloscope class). Conservative fallback, not
    # a real hardware number -- if you hit this, the oscilloscope driver in
    # use should have max_sample_rate added to it.
    _DEFAULT_MAX_SAMPLE_RATE = 10e6

    # Same idea, for when acquisition_points isn't declared.
    _DEFAULT_ACQUISITION_POINTS = (8, 8192)

    def _configure_scope_for_frequency(self, frequency):
        """
        Sizes the acquisition so the sample rate always scales with the
        drive frequency (no aliasing at the sweep's high end) and the point
        budget is whatever the connected scope actually supports.

        Two hardware models exist among real oscilloscopes, and this method
        handles both from the same two scope-declared numbers:

        - Variable record length (e.g. Analog Discovery 2, acquisition_points
          spans a wide range): picks close to the ideal point count for the
          target duration, so low-frequency points don't over-allocate.
        - Fixed record length (e.g. Tektronix TBS1000 series,
          acquisition_points min == max): the scope always fills its whole
          fixed buffer regardless of what's requested, so the useful lever
          is the acquisition *duration* -- widened, if needed, to keep the
          resulting sample rate within the scope's max_sample_rate rather
          than silently exceeding it.

        In both cases, if hitting the sample-rate ceiling forces a longer
        acquisition than the nominal cycles_per_point target, that just
        means extra cycles get captured at the same sample density -- more
        averaging in the lock-in correlation, not a problem.
        """
        max_sample_rate = getattr(self.osc, 'max_sample_rate', None) or self._DEFAULT_MAX_SAMPLE_RATE
        points_bounds = getattr(self.osc, 'acquisition_points', None)
        if not points_bounds or points_bounds[0] is None or points_bounds[1] is None:
            points_min, points_max = self._DEFAULT_ACQUISITION_POINTS
        else:
            points_min, points_max = points_bounds

        target_duration = min(self.cycles_per_point / frequency, self.max_capture_time)
        desired_points = self.cycles_per_point * self._SAMPLES_PER_PERIOD
        points = round(max(points_min, min(desired_points, points_max)))

        # Sample rate needed to fit `points` samples into `target_duration`.
        # If the scope can't actually sample that fast, widen the
        # acquisition window instead of silently under-sampling -- this is
        # also just what happens physically on a fixed-record-length scope,
        # since its point count can't shrink to compensate.
        required_rate = points / target_duration
        if required_rate > max_sample_rate:
            sample_rate = max_sample_rate
            total_time = points / sample_rate
        else:
            total_time = target_duration

        self.osc.set_acquisition_points(points)
        self.osc.set_horizontal_scale(total_time / 10.0, total_time)
        return total_time

    @staticmethod
    def _trapz(y, x):
        """Trapezoidal integration without depending on numpy's trapz/trapezoid naming
        (renamed between numpy versions; piec supports numpy>=1.19.2)."""
        return float(np.sum((y[1:] + y[:-1]) * np.diff(x) / 2.0))

    @classmethod
    def _complex_component(cls, t, y, frequency):
        """
        Complex Fourier coefficient of y at `frequency`, i.e. a single-bin
        DFT (the "lock-in amplifier" technique): correlate the captured
        signal against sin/cos references at the drive frequency instead of
        reading an FFT bin or peak, so an arbitrary (non-integer-period)
        capture window and sample count are fine.
        """
        duration = t[-1] - t[0] if len(t) > 1 else 0.0
        if duration <= 0:
            return 0j
        in_phase = cls._trapz(y * np.cos(2 * np.pi * frequency * t), t)
        quadrature = cls._trapz(y * np.sin(2 * np.pi * frequency * t), t)
        return (2.0 / duration) * (in_phase - 1j * quadrature)

    def measure_point(self, frequency):
        """
        Drives `frequency` on the AWG and returns the complex, simultaneously
        -measured input and output components. If autorange is enabled,
        also resizes self.input_range/self.output_range for the next call
        based on the peak amplitude just measured.

        args:
            frequency (float): Drive frequency in Hz.
        returns:
            (complex, complex): (Vin, Vout) complex amplitudes.
        """
        self.awg.set_frequency(self.awg_channel, frequency)
        self._configure_scope_for_frequency(frequency)
        time.sleep(max(self.settle_cycles / frequency, 0.01))

        df = self.osc.get_multi_channel_data([self.input_channel, self.output_channel])
        t = df["Time"].to_numpy()
        vin = df[f"Channel {self.input_channel}"].to_numpy()
        vout = df[f"Channel {self.output_channel}"].to_numpy()

        vin_peak = float(np.max(np.abs(vin))) if len(vin) else 0.0
        vout_peak = float(np.max(np.abs(vout))) if len(vout) else 0.0
        self._warn_if_clipping("Vin", vin_peak, self.input_range, frequency)
        self._warn_if_clipping("Vout", vout_peak, self.output_range, frequency)

        vin_c = self._complex_component(t, vin, frequency)
        vout_c = self._complex_component(t, vout, frequency)

        # Resize each channel's range for the *next* point based on what was
        # just measured, so a sweep spanning a huge dynamic range isn't stuck
        # using one fixed range (and its resolution) the whole way through.
        if self.autorange:
            self.input_range = self._next_range(self.input_range, vin_peak)
            self.output_range = self._next_range(self.output_range, vout_peak)
            self.osc.set_vertical_scale(self.input_channel, vdiv=None, y_range=self.input_range)
            self.osc.set_vertical_scale(self.output_channel, vdiv=None, y_range=self.output_range)

        return vin_c, vout_c

    def _next_range(self, current_range, peak):
        """
        Feed-forward autorange: sizes the NEXT capture's range from the peak
        amplitude just measured, targeting `range_headroom`x that peak's
        peak-to-peak span as the new full-scale range. Feed-forward (using
        the previous point to size the next) rather than a measure-check-
        retry loop, since adjacent log-spaced sweep points have similar
        amplitude in a smooth response -- this avoids doubling every point's
        acquisition time for a re-capture that's rarely needed.
        """
        if peak <= 0:
            return current_range
        ideal = 2.0 * peak * self.range_headroom
        return float(np.clip(ideal, self.min_range, self.max_range))

    @staticmethod
    def _warn_if_clipping(label, peak, channel_range, frequency, threshold=0.9):
        """
        Warns when a captured channel's peak amplitude is close to (or past)
        its configured full-scale range -- a clipped/railed capture silently
        corrupts the gain/phase extraction, since it assumes a clean sine.
        """
        limit = channel_range / 2.0
        if peak >= limit:
            print(f"  [WARN] {label} clipped at {frequency:.5g} Hz: peak={peak:.3g}V "
                  f"exceeds the configured range's +/-{limit:.3g}V limit.")
        elif peak >= threshold * limit:
            print(f"  [WARN] {label} near full-scale at {frequency:.5g} Hz: peak={peak:.3g}V "
                  f"is within {int((1 - threshold) * 100)}% of the +/-{limit:.3g}V range limit.")

    def sweep(self):
        """
        Runs the full log-spaced frequency sweep, measuring gain and phase
        at each point. Results are stored in self.data as a pandas DataFrame.
        """
        frequencies = self._frequency_points()
        rows = []

        print(f"Starting frequency response sweep: {self.f_start:.4g} Hz to {self.f_stop:.4g} Hz, "
              f"{len(frequencies)} points...")

        for i, frequency in enumerate(frequencies):
            vin_c, vout_c = self.measure_point(frequency)
            vin_mag = abs(vin_c)
            vout_mag = abs(vout_c)

            if vin_mag == 0:
                print(f"  [WARN] No input signal detected at {frequency:.5g} Hz; skipping point.")
                continue

            gain_c = vout_c / vin_c
            magnitude_db = 20.0 * np.log10(abs(gain_c))
            phase_deg = np.degrees(np.angle(gain_c))
            rows.append((frequency, magnitude_db, phase_deg, vin_mag, vout_mag))

            if (i + 1) % max(1, len(frequencies) // 10) == 0 or i == len(frequencies) - 1:
                print(f"  {i + 1}/{len(frequencies)}: f={frequency:.5g} Hz  "
                      f"gain={magnitude_db:.2f} dB  phase={phase_deg:.1f} deg")

        self.data = pd.DataFrame(rows, columns=[
            "Frequency (Hz)", "Magnitude (dB)", "Phase (deg)", "Vin (V)", "Vout (V)"
        ])
        if not self.data.empty:
            self.data["Phase (deg)"] = np.degrees(np.unwrap(np.radians(self.data["Phase (deg)"])))
        print("Sweep complete.")

    def save_data(self):
        """
        Save captured frequency response data to CSV file.
        """
        self._update_metadata()

        if self.data is not None:
            notes = f"{self.f_start:.4g}Hz_to_{self.f_stop:.4g}Hz".replace('.', 'p')
            self.filename = create_measurement_filename(self.save_dir, self.mtype, notes)
            metadata_and_data_to_csv(self.metadata, self.data, self.filename)
            print(f"Frequency response data saved to {self.filename}")
        else:
            print("No data to save. Run the sweep first.")

    def run_experiment(self):
        """
        Execute complete frequency response (Bode plot) workflow.
        """
        print("Running frequency response (Bode) sweep...")
        self.configure_scope()
        self.configure_awg()
        print("Instruments configured.")
        try:
            self.sweep()
        finally:
            self.awg.output(self.awg_channel, False)
            print("Output off.")
        self.save_data()
        print("Experiment complete.")
