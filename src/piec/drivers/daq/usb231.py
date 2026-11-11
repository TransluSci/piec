from ..digilent import Digilent
from .daq import Daq

try:
    from mcculw.enums import (
        AnalogInputMode,
        DigitalIODirection,
        DigitalPortType,
        ULRange,
    )
except ImportError:
    # Digilent raises a contextual ImportError when hardware is initialized.
    ULRange = None
    DigitalIODirection = None
    DigitalPortType = None
    AnalogInputMode = None

class USB231(Digilent, Daq):
    """
    Driver for the MCC USB-231 DAQ device.
    
    Based on Manual:
    - 8 Single-Ended Analog Inputs (16-bit, +/- 10V)
    - 2 Analog Outputs (16-bit, +/- 10V)
    - 8 Digital I/O (Bit configurable)
    """

    # --- Class Attributes ---
    
    AUTODETECT_ID = "USB-231"
    AI_STATUS = "assisted"
    HARDWARE_TESTED = True  # Tested on physical hardware

    # Default to the safer Differential mode (4 channels) per user request.
    # This will be updated dynamically by set_input_mode().
    ai_channel = [0, 1, 2, 3]

    # Analog Output Channels: 2 channels (indices 0-1)
    ao_channel = [0, 1]

    # Digital I/O Channels: 8 channels (indices 0-7)
    dio_channel = [0, 1, 2, 3, 4, 5, 6, 7]

    # Analog Input Range: fixed at +/-10 V.
    ai_range = [(-10.0, 10.0)]

    # Maximum aggregate hardware-paced analog input rate.
    ai_sample_rate = (1, 50_000)

    # Analog Output Range: fixed at +/-10 V.
    ao_range = [(-10.0, 10.0)]

    # Maximum simultaneous hardware-paced update rate per AO channel.
    ao_sample_rate = (1, 5_000)

    # Analog Input Modes: SE (Single-Ended) or DIFF (Differential)
    ai_mode = ['SE', 'DIFF']

    # Digital Direction: Configurable as Input ('I') or Output ('O')
    dio_direction = ['I', 'O']

    def __init__(self, address, **kwargs):
        """
        Initialize the USB-231. 
        Defaults to Differential Mode (Channels 0-3) to match ai_channel default.
        """
        # Initialize the parent Digilent class (handles connection)
        super().__init__(address, **kwargs)

        self._ai_sample_rates = {}
        self._ao_sample_rates = {}
        self._selected_ai_channel = 0
        self._selected_ao_channel = 0
        self._selected_dio_channel = 0

        # Force hardware to match the class default (Differential) on startup
        self.set_input_mode('DIFF')

    def read_AI(self, ai_channel):
        """
        Reads a float value (voltage) from the specified Analog Input channel.
        Manual Page 10: Software paced mode.
        
        args:
            ai_channel (int): The channel to read from.
        returns:
            float: The measured value in Volts.
        """
        # Validation: Ensure the requested channel is valid for the CURRENT mode
        if ai_channel not in self.ai_channel:
            raise ValueError(f"Channel {ai_channel} is not valid in current Input Mode. Available: {self.ai_channel}")

        try:
            # v_in returns the voltage directly. 
            # Range is fixed at +/- 10V (BIP10VOLTS)
            value = self.ul.v_in(self.board_num, ai_channel, ULRange.BIP10VOLTS)
            return value
        except Exception as e:
            print(f"USB231 Error reading AI{ai_channel}: {e}")
            raise

    def _ai_ul_range(self, ai_channel):
        return ULRange.BIP10VOLTS

    def write_AO(self, ao_channel, data):
        """
        Writes data to the Analog Output channel.
        Manual Page 17: Software paced mode.
        
        args:
            ao_channel (int): The channel to write to (0-1).
            data (float or list/ndarray): The voltage(s) to output (+/- 10V).
        """
        if ao_channel not in self.ao_channel:
            raise ValueError(f"AO channel {ao_channel} is invalid; valid channels are {self.ao_channel}")
        try:
            # Handle single value vs array
            if isinstance(data, (int, float)):
                data = [data]
            
            # Software paced loop
            for v in data:
                # Range is fixed at +/- 10V
                voltage = float(v)
                if not -10.0 <= voltage <= 10.0:
                    raise ValueError("analog-output values must be within +/-10 V")
                self.ul.v_out(self.board_num, ao_channel, ULRange.BIP10VOLTS, voltage)
                
        except Exception as e:
            print(f"USB231 Error writing AO{ao_channel}: {e}")
            raise

    def set_input_mode(self, ai_mode):
        """
        Configures the Analog Input Mode and updates self.ai_channel list.
        Manual Page 22: "8 single-ended or 4 differential; software-selectable".
        
        args:
            ai_mode (str): 'SE' (Single-Ended) or 'DIFF' (Differential).
        """
        mode_str = str(ai_mode).upper()

        try:
            if 'DIFF' in mode_str:
                # Differential Mode: Limits to 4 channels (0-3)
                # Pins 0-3 become High, Pins 4-7 become Low inputs
                self.ul.a_input_mode(self.board_num, AnalogInputMode.DIFFERENTIAL)
                self.ai_channel = [0, 1, 2, 3]
                print(f"USB231: Set to DIFFERENTIAL mode. Available Channels: {self.ai_channel}")
                
            elif 'SE' in mode_str or 'SINGLE' in mode_str:
                # Single-Ended Mode: Enables 8 channels (0-7)
                # All inputs referenced to AGND
                self.ul.a_input_mode(self.board_num, AnalogInputMode.SINGLE_ENDED)
                self.ai_channel = [0, 1, 2, 3, 4, 5, 6, 7]
                print(f"USB231: Set to SINGLE-ENDED mode. Available Channels: {self.ai_channel}")
                
            else:
                raise ValueError(f"Invalid mode '{ai_mode}'. Use 'SE' or 'DIFF'.")
                
        except Exception as e:
            print(f"USB231 Error setting input mode: {e}")
            raise

    def set_ai_range(self, ai_channel, ai_range):
        """
        Configures the gain/range for an Analog Input channel.
        The USB-231 has a fixed input range of +/- 10V.
        
        args:
            ai_channel (int): The channel to configure.
            ai_range (tuple): The (min, max) range desired.
        """
        if ai_channel not in self.ai_channel:
            raise ValueError(f"AI channel {ai_channel} is invalid; valid channels are {self.ai_channel}")
        valid_range = (-10.0, 10.0)
        if self._normalize_range(ai_range) != valid_range:
            raise ValueError("USB-231 analog inputs have a fixed +/-10 V range")
        
        # No UL command needed; hardware is fixed.

    def set_ao_range(self, ao_channel, ao_range):
        """
        Configures the output range for an Analog Output channel.
        The USB-231 has a fixed output range of +/- 10V.
        
        args:
            ao_channel (int): The channel to configure.
            ao_range (tuple): The (min, max) range desired.
        """
        if ao_channel not in self.ao_channel:
            raise ValueError(f"AO channel {ao_channel} is invalid; valid channels are {self.ao_channel}")
        valid_range = (-10.0, 10.0)
        if self._normalize_range(ao_range) != valid_range:
            raise ValueError("USB-231 analog outputs have a fixed +/-10 V range")

    @staticmethod
    def _normalize_range(voltage_range):
        """Return the common DAQ ``(minimum, maximum)`` range representation."""
        try:
            low, high = voltage_range
        except (TypeError, ValueError) as error:
            raise ValueError(
                "range must be a two-value (minimum, maximum) pair"
            ) from error
        return float(low), float(high)

    def read_DI(self, dio_channel):
        """
        Reads the state of a single digital channel (DIO0 - DIO7).
        Manual Page 18: "All digital I/O updates and samples are software-paced.".
        
        args:
            dio_channel (int): The channel to read.
        returns:
            int: 1 (High) or 0 (Low).
        """
        if dio_channel not in self.dio_channel:
            raise ValueError(f"DIO channel {dio_channel} is invalid; valid channels are {self.dio_channel}")
        try:
            # Universal Library exposes the USB-231's eight-bit DIO block as AUXPORT.
            bit_value = self.ul.d_bit_in(self.board_num, DigitalPortType.AUXPORT, dio_channel)
            return bit_value
        except Exception as e:
            print(f"USB231 Error reading DIO{dio_channel}: {e}")
            raise

    def write_DO(self, dio_channel, data):
        """
        Writes data to a digital output channel.
        
        args:
            dio_channel (int): The channel to write to.
            data (int/bool or list): 1/True for High, 0/False for Low.
        """
        if dio_channel not in self.dio_channel:
            raise ValueError(f"DIO channel {dio_channel} is invalid; valid channels are {self.dio_channel}")
        try:
            if isinstance(data, (int, bool)):
                data = [data]

            for state in data:
                if state not in (0, 1, False, True):
                    raise ValueError("digital-output values must be 0/1 or False/True")
                bit_val = 1 if state else 0
                self.ul.d_bit_out(self.board_num, DigitalPortType.AUXPORT, dio_channel, bit_val)
        except Exception as e:
            print(f"USB231 Error writing DIO{dio_channel}: {e}")
            raise

    def set_dio_direction(self, dio_channel, dio_direction):
        """
        Configures the physics of the digital pin (Input vs Output).
        Manual Page 18: "Each digital I/O line is bit-configurable as input or output.".
        
        args:
            dio_channel (int): The channel to configure.
            dio_direction (str): 'IN' or 'OUT'.
        """
        if dio_channel not in self.dio_channel:
            raise ValueError(f"DIO channel {dio_channel} is invalid; valid channels are {self.dio_channel}")
        direction_str = str(dio_direction).upper()
        
        # Map string to UL Enum
        if direction_str in {"I", "IN", "INPUT"}:
            ul_dir = DigitalIODirection.IN
        elif direction_str in {"O", "OUT", "OUTPUT"}:
            ul_dir = DigitalIODirection.OUT
        else:
            raise ValueError("dio_direction must be 'I' or 'O'")

        try:
            # d_config_bit configures individual bits
            self.ul.d_config_bit(self.board_num, DigitalPortType.AUXPORT, dio_channel, ul_dir)
        except Exception as e:
            print(f"USB231 Error configuring DIO{dio_channel}: {e}")
            raise

    # Daq interface adapters. Universal Library receives channel/range/rate
    # values when an operation starts, so selection methods retain the settings.
    def set_AI_channel(self, ai_channel):
        if ai_channel not in self.ai_channel:
            raise ValueError(f"AI channel {ai_channel} is invalid; valid channels are {self.ai_channel}")
        self._selected_ai_channel = ai_channel

    def set_AI_range(self, ai_channel, range):
        self.set_ai_range(ai_channel, range)

    def set_AI_sample_rate(self, ai_channel, sample_rate):
        self.set_AI_channel(ai_channel)
        if not 1 <= sample_rate <= 50_000:
            raise ValueError("sample_rate must be between 1 and 50,000 S/s")
        self._ai_sample_rates[ai_channel] = sample_rate

    def configure_AI_channel(self, ai_channel, range=None, sample_rate=None):
        self.set_AI_channel(ai_channel)
        if range is not None:
            self.set_AI_range(ai_channel, range)
        if sample_rate is not None:
            self.set_AI_sample_rate(ai_channel, sample_rate)

    def set_AO_channel(self, ao_channel):
        if ao_channel not in self.ao_channel:
            raise ValueError(f"AO channel {ao_channel} is invalid; valid channels are {self.ao_channel}")
        self._selected_ao_channel = ao_channel

    def set_AO_range(self, ao_channel, range):
        self.set_ao_range(ao_channel, range)

    def set_AO_sample_rate(self, ao_channel, sample_rate):
        self.set_AO_channel(ao_channel)
        if not 1 <= sample_rate <= 5_000:
            raise ValueError("sample_rate must be between 1 and 5,000 S/s")
        self._ao_sample_rates[ao_channel] = sample_rate

    def configure_AO_channel(self, ao_channel, range=None, sample_rate=None):
        self.set_AO_channel(ao_channel)
        if range is not None:
            self.set_AO_range(ao_channel, range)
        if sample_rate is not None:
            self.set_AO_sample_rate(ao_channel, sample_rate)

    def set_DIO_channel(self, dio_channel):
        if dio_channel not in self.dio_channel:
            raise ValueError(f"DIO channel {dio_channel} is invalid; valid channels are {self.dio_channel}")
        self._selected_dio_channel = dio_channel

    def set_DIO_mode(self, dio_channel, mode):
        self.set_dio_direction(dio_channel, mode)

    def configure_DIO_channel(self, dio_channel, mode, sample_rate=None):
        self.set_DIO_channel(dio_channel)
        self.set_DIO_mode(dio_channel, mode)
        if sample_rate is not None:
            self.set_DIO_sample_rate(dio_channel, sample_rate)

    def set_DI_channel(self, dio_channel):
        self.set_DIO_channel(dio_channel)

    def configure_DI_channel(self, dio_channel, sample_rate=None):
        self.set_DI_channel(dio_channel)
        self.set_DIO_mode(dio_channel, "I")
        if sample_rate is not None:
            self.set_DI_sample_rate(dio_channel, sample_rate)

    def set_DO_channel(self, dio_channel):
        self.set_DIO_channel(dio_channel)

    def configure_DO_channel(self, dio_channel, sample_rate=None):
        self.set_DO_channel(dio_channel)
        self.set_DIO_mode(dio_channel, "O")
        if sample_rate is not None:
            self.set_DO_sample_rate(dio_channel, sample_rate)

    def read_data(self, ai_channel):
        return self.read_AI(ai_channel)
