"""
This is an outline for what the daq.py file should be like.

A daq (Data Acqusition System) is defined as an instrument that has the typical features one expects a daq to have
"""
from ..instrument import Instrument, optional
import math
import threading
import time
from numbers import Integral, Real
class Daq(Instrument):
    # Initializer / Instance attributes
    """
    All daqs must be able to either acquire or output signals.
    """

    # --- Class Attributes (Capabilities & Limits) ---
    # Child drivers MUST override these with their specific hardware values.
    # See DRIVER_DEVELOPMENT_GUIDE.md Section 4 for formatting rules.

    # Analog Input
    # List of valid analog input channels. For example, four channels would be
    # represented as [0, 1, 2, 3]. Use [] when analog input is not supported.
    ai_channel = []
    ai_range = [(None, None)]           # List of supported (min_V, max_V) tuples
    ai_mode = ["SE", "DIFF"]           # Standard input-mode names when selectable
    ai_sample_rate = (None, None)       # (min_Hz, max_Hz) for analog input acquisition

    # Analog Output
    # List of valid analog output channels. For example, four channels would be
    # represented as [0, 1, 2, 3]. Use [] when analog output is not supported.
    ao_channel = []
    ao_range = [(None, None)]           # List of supported (min_V, max_V) tuples
    ao_sample_rate = (None, None)       # (min_Hz, max_Hz) for analog output generation

    # Digital I/O
    # List of valid digital input/output channels. For example, four channels
    # would be represented as [0, 1, 2, 3]. Use [] when DIO is not supported.
    dio_channel = []
    dio_direction = ["I", "O"]         # Supported directions: Input, Output
    # Instrument management methods are supplied by the protocol base (for
    # example Digilent or Scpi) or by the concrete driver.
    def idn(self):
        """Return a device-identification string."""

    def reset(self):
        """Reset the device to its default state."""

    def clear(self):
        """Clear the device error/status state."""

    def error(self):
        """Return the most recent device error/status."""

    def wait(self):
        """Wait for pending operations to complete."""

    def self_test(self):
        """Run the device self-test, when supplied by the protocol."""

    def operation_complete(self):
        """Report whether the current operation is complete."""

    def close(self):
        """Release the device and associated resources."""

    def initialize(self):
        """Initialize the DAQ into a known state using reset and clear."""
        self.reset()
        self.clear()

    # --- DAQ-Specific Methods ---

    # Analog Input
    @optional
    def set_input_mode(self, ai_mode):
        """Set the analog-input wiring mode when it is configurable."""

    def set_AI_channel(self, channel):
        """Select an analog-input channel."""

    def set_AI_range(self, channel, range):
        """Set or validate an analog-input voltage range."""

    def set_AI_sample_rate(self, channel, sample_rate):
        """Store/configure the hardware-paced input sample rate."""

    def configure_AI_channel(self, channel, range=None, sample_rate=None):
        """Configure an analog-input channel using supplied settings."""

    def read_AI(self, channel):
        """Read one analog-input value in volts."""

    def read_AI_scan(self, channel, points, rate):
        """Acquire a finite analog-input scan.

        Drivers with hardware-paced acquisition should use the device clock.
        Drivers without hardware scanning must implement a software-paced
        fallback using repeated analog-input reads. A software fallback must
        document that its requested sample rate is not timing-guaranteed.
        """

    def quick_read(self):
        """Read the currently selected/default analog-input channel."""

    def read_data(self, channel):
        """Read data from a channel using the driver's documented default."""

    # Analog Output
    def set_AO_channel(self, channel):
        """Select an analog-output channel."""

    def set_AO_range(self, channel, range):
        """Set or validate an analog-output voltage range."""

    def set_AO_sample_rate(self, channel, sample_rate):
        """Store/configure the hardware-paced output sample rate."""

    def configure_AO_channel(self, channel, range=None, sample_rate=None):
        """Configure an analog-output channel using supplied settings."""

    def write_AO(self, channel, data):
        """Write one or more voltage values to an analog-output channel."""

    @optional
    def output(self, channel, on=True):
        """Explicitly enable/disable an output when hardware supports it.

        Many DAQs have no separate output switch: a write immediately changes
        the pin and the value remains latched. Such drivers intentionally do
        not override this method; callers must write a safe value explicitly.
        """

    # Digital Input/Output
    def set_DIO_channel(self, channel):
        """Select a digital I/O line."""

    def set_DIO_mode(self, channel, mode):
        """Configure a digital I/O line as input or output."""

    @optional
    def set_DIO_sample_rate(self, channel, sample_rate):
        """Configure a hardware-paced digital I/O sample rate."""

    def configure_DIO_channel(self, channel, mode, sample_rate=None):
        """Configure a digital I/O line using supplied settings."""

    def set_DI_channel(self, channel):
        """Select a digital line for input."""

    @optional
    def set_DI_sample_rate(self, channel, sample_rate):
        """Configure a hardware-paced digital-input sample rate."""

    def configure_DI_channel(self, channel, sample_rate=None):
        """Configure a digital line as input."""

    def read_DI(self, channel):
        """Read one digital line as 0 or 1."""

    def set_DO_channel(self, channel):
        """Select a digital line for output."""

    @optional
    def set_DO_sample_rate(self, channel, sample_rate):
        """Configure a hardware-paced digital-output sample rate."""

    def configure_DO_channel(self, channel, sample_rate=None):
        """Configure a digital line as output."""

    def write_DO(self, channel, data):
        """Write one or more Boolean states to a digital-output line."""

    def get_trigger_pulse_capabilities(self):
        """Return pulse-output resources, channels, timing and width bounds (seconds).

        Advertise only real implementations. Digital channel 0 and timer channel 0
        name different physical terminals; callers must explicitly choose a resource.
        """
        if (self.dio_channel and type(self).write_DO is not Daq.write_DO
                and type(self).set_DIO_mode is not Daq.set_DIO_mode):
            return {'digital': {'channels': list(self.dio_channel), 'timing': 'software',
                                'min_width': 0.0, 'max_width': 60.0}}
        return {}

    def validate_trigger_pulse(self, channel, pulse_width, active_high=True, *,
                               resource='digital', require_hardware_timing=False):
        """Validate a pulse request without touching outputs; return its capabilities."""
        if not isinstance(resource, str):
            raise ValueError('resource must be a string naming a pulse output')
        capabilities = self.get_trigger_pulse_capabilities()
        if resource not in capabilities:
            raise NotImplementedError(f'{type(self).__name__} has no {resource!r} trigger-pulse resource')
        selected = capabilities[resource]
        if isinstance(channel, bool) or not isinstance(channel, Integral) or channel not in selected['channels']:
            raise ValueError(f'{resource} channel must be one of {selected["channels"]}')
        if (isinstance(pulse_width, bool) or not isinstance(pulse_width, Real)
                or not math.isfinite(pulse_width) or pulse_width <= 0
                or not selected['min_width'] <= pulse_width <= selected['max_width']):
            raise ValueError(f'pulse_width must be positive, finite and within '
                             f'{selected["min_width"]} to {selected["max_width"]} seconds')
        if not isinstance(active_high, bool) or not isinstance(require_hardware_timing, bool):
            raise ValueError('active_high and require_hardware_timing must be Boolean')
        if require_hardware_timing and selected['timing'] != 'hardware':
            raise NotImplementedError('The selected output does not provide hardware-timed pulses')
        return selected

    @staticmethod
    def _wait_trigger_pulse(duration, cancel_event):
        if cancel_event is None:
            time.sleep(duration)
        elif cancel_event.wait(duration):
            raise InterruptedError('Trigger pulse cancelled')

    def send_trigger_pulse(self, channel, pulse_width, active_high=True, *,
                           resource='digital', require_hardware_timing=False, cancel_event=None):
        """Emit one physical pulse, then restore idle; block until done or cancelled.

        Driver authors: override this method to use a hardware timer/pulse engine
        when supported, and override get_trigger_pulse_capabilities accordingly.
        If hardware pulse generation is unsupported, inherit this software fallback
        or override with an equivalent SOFTWARE-TIMED implementation using the
        driver's digital-output commands. Label it 'software', propagate I/O errors,
        and restore idle in finally. Do not silently substitute another physical pin
        or fall back to software after a hardware start error (a pulse may have fired).

        This default uses set_DIO_mode and write_DO. It requests idle -> active ->
        idle, with USB/OS-dependent latency and pulse width; it guarantees no precise
        synchronization with analog output. The software width limit is 60 seconds.
        Callers must reserve the output, match voltage/load requirements, and avoid
        concurrent operations on it. Mode changes can produce device-specific edges.
        Cancellation attempts idle restoration; cleanup failures propagate too.

        resource='digital' means a DIO line, not a timer terminal. Drivers without
        implemented DIO reject the request. require_hardware_timing rejects software
        and simulation before I/O. Return metadata describes timing and programmed
        width; no physical edge timestamp or measured pulse width is claimed.
        """
        capability = self.validate_trigger_pulse(channel, pulse_width, active_high,
            resource=resource, require_hardware_timing=require_hardware_timing)
        if resource != 'digital':
            raise NotImplementedError('This resource needs a driver-specific pulse implementation')
        lock = self.__dict__.setdefault('_trigger_pulse_lock', threading.Lock())
        with lock:
            self._wait_trigger_pulse(0, cancel_event)
            idle = int(not active_high)
            try:
                self.set_DIO_mode(channel, 'O')
                self.write_DO(channel, idle)
                self.write_DO(channel, int(active_high))
                self._wait_trigger_pulse(float(pulse_width), cancel_event)
            finally:
                self.write_DO(channel, idle)
        return {'resource': resource, 'channel': int(channel), 'timing': capability['timing'],
                'requested_pulse_width': float(pulse_width), 'programmed_pulse_width': None,
                'active_high': active_high}
