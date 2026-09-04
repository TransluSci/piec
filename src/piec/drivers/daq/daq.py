"""
This is an outline for what the daq.py file should be like.

A daq (Data Acqusition System) is defined as an instrument that has the typical features one expects a daq to have
"""
from ..instrument import Instrument, optional
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
