from ..digilent import Digilent
from .daq import Daq

try:
    from mcculw.enums import (
        AnalogInputMode,
        DigitalIODirection,
        DigitalPortType,
        FunctionType,
        ScanOptions,
        Status,
        ULRange,
    )
except ImportError:
    # Digilent raises a contextual ImportError when hardware is initialized.
    ULRange = None
    DigitalIODirection = None
    DigitalPortType = None
    AnalogInputMode = None
    FunctionType = None
    ScanOptions = None
    Status = None

class USB231(Digilent, Daq):
    """
    Driver for the MCC USB-231 DAQ device.
    
    Based on Manual:
    - [cite_start]8 Single-Ended Analog Inputs (16-bit, +/- 10V) [cite: 668]
    - [cite_start]2 Analog Outputs (16-bit, +/- 10V) [cite: 677]
    - [cite_start]8 Digital I/O (Bit configurable) [cite: 683]
    """

    # --- Class Attributes ---
    
    AUTODETECT_ID = "USB-231"

    # Default to the safer Differential mode (4 channels) per user request.
    # This will be updated dynamically by set_input_mode().
    ai_channel = [0, 1, 2, 3]

    # [cite_start]Analog Output Channels: 2 channels (indices 0-1) [cite: 677]
    ao_channel = [0, 1]

    # [cite_start]Digital I/O Channels: 8 channels (indices 0-7) [cite: 683]
    dio_channel = [0, 1, 2, 3, 4, 5, 6, 7]

    # Analog Input Range: fixed at +/-10 V.
    ai_range = [(-10.0, 10.0)]

    # Maximum aggregate hardware-paced analog input rate.
    ai_sample_rate = (1, 50_000)

    # Analog Output Range: fixed at +/-10 V.
    ao_range = [(-10.0, 10.0)]

    # Maximum simultaneous hardware-paced update rate per AO channel.
    ao_sample_rate = (1, 5_000)

    # [cite_start]Analog Input Modes: SE (Single-Ended) or DIFF (Differential) [cite: 668]
    ai_mode = ['SE', 'DIFF']

    # [cite_start]Digital Direction: Configurable as Input ('I') or Output ('O') [cite: 683]
    dio_direction = ['I', 'O']

    def __init__(self, address, **kwargs):
        """
        Initialize the USB-231. 
        Defaults to Differential Mode (Channels 0-3) to match ai_channel default.
        """
        # Initialize the parent Digilent class (handles connection)
        super().__init__(address, **kwargs)

        # Force hardware to match the class default (Differential) on startup
        self.set_input_mode('DIFF')

    def read_AI(self, channel):
        """
        Reads a float value (voltage) from the specified Analog Input channel.
        [cite_start]Manual Page 10: Software paced mode[cite: 124].
        
        args:
            channel (int): The channel to read from.
        returns:
            float: The measured value in Volts.
        """
        # Validation: Ensure the requested channel is valid for the CURRENT mode
        if channel not in self.ai_channel:
            raise ValueError(f"Channel {channel} is not valid in current Input Mode. Available: {self.ai_channel}")

        try:
            # v_in returns the voltage directly. 
            # [cite_start]Range is fixed at +/- 10V (BIP10VOLTS) [cite: 668]
            value = self.ul.v_in(self.board_num, channel, ULRange.BIP10VOLTS)
            return value
        except Exception as e:
            print(f"USB231 Error reading AI{channel}: {e}")
            raise

    def read_AI_scan(self, channel, points, rate):
        """
        Reads a stream of Analog input data (hardware paced).
        [cite_start]Manual Page 10: Hardware paced mode[cite: 124].
        
        args:
            channel (int): The channel to read from.
            points (int): Number of points to acquire.
            rate (float): Sample rate in Hz.
        returns:
            list: The acquired voltage data.
        """
        if channel not in self.ai_channel:
            raise ValueError(f"Channel {channel} is not valid in current Input Mode. Available: {self.ai_channel}")

        if not isinstance(points, int) or isinstance(points, bool) or points <= 0:
            raise ValueError("points must be a positive integer")
        if not 1 <= rate <= 50_000:
            raise ValueError("rate must be between 1 S/s and 50,000 S/s")

        # USB-231 supports SCALEDATA. Let Universal Library apply the board's
        # calibration coefficients and return engineering-unit voltages rather
        # than approximating volts from ideal 16-bit raw counts.
        memhandle = self.ul.scaled_win_buf_alloc(points)
        if not memhandle:
            raise MemoryError("Universal Library could not allocate the AI scan buffer")

        try:
            scan_options = ScanOptions.BACKGROUND | ScanOptions.SCALEDATA
            self._last_ai_scan_rate = self.ul.a_in_scan(
                self.board_num,
                channel,
                channel,
                points,
                int(rate),
                ULRange.BIP10VOLTS,
                memhandle,
                scan_options,
            )

            import time

            timeout = time.monotonic() + points / float(rate) + 5.0
            while True:
                status, _, _ = self.ul.get_status(
                    self.board_num, FunctionType.AIFUNCTION
                )
                if status == Status.IDLE:
                    break
                if time.monotonic() >= timeout:
                    raise TimeoutError("USB-231 analog-input scan timed out")
                time.sleep(0.01)

            from ctypes import c_double

            data_volts = (c_double * points)()
            self.ul.scaled_win_buf_to_array(memhandle, data_volts, 0, points)
            return list(data_volts)
        finally:
            try:
                self.ul.stop_background(self.board_num, FunctionType.AIFUNCTION)
            except Exception:
                pass
            self.ul.win_buf_free(memhandle)

    def write_AO(self, channel, data):
        """
        Writes data to the Analog Output channel.
        [cite_start]Manual Page 17: Software paced mode[cite: 489].
        
        args:
            channel (int): The channel to write to (0-1).
            data (float or list/ndarray): The voltage(s) to output (+/- 10V).
        """
        try:
            # Handle single value vs array
            if isinstance(data, (int, float)):
                data = [data]
            
            # Software paced loop
            for v in data:
                # [cite_start]Range is fixed at +/- 10V [cite: 677]
                self.ul.v_out(self.board_num, channel, ULRange.BIP10VOLTS, float(v))
                
        except Exception as e:
            print(f"USB231 Error writing AO{channel}: {e}")
            raise

    def set_input_mode(self, ai_mode):
        """
        Configures the Analog Input Mode and updates self.ai_channel list.
        [cite_start]Manual Page 22: "8 single-ended or 4 differential; software-selectable"[cite: 668].
        
        args:
            ai_mode (str): 'SE' (Single-Ended) or 'DIFF' (Differential).
        """
        mode_str = str(ai_mode).upper()

        try:
            if 'DIFF' in mode_str:
                # Differential Mode: Limits to 4 channels (0-3)
                # [cite_start]Pins 0-3 become High, Pins 4-7 become Low inputs [cite: 261]
                self.ul.a_input_mode(self.board_num, AnalogInputMode.DIFFERENTIAL)
                self.ai_channel = [0, 1, 2, 3]
                print(f"USB231: Set to DIFFERENTIAL mode. Available Channels: {self.ai_channel}")
                
            elif 'SE' in mode_str or 'SINGLE' in mode_str:
                # Single-Ended Mode: Enables 8 channels (0-7)
                # [cite_start]All inputs referenced to AGND [cite: 358]
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
        [cite_start]The USB-231 has a fixed input range of +/- 10V[cite: 668].
        
        args:
            ai_channel (int): The channel to configure.
            ai_range (tuple): The (min, max) range desired.
        """
        # Check if the requested range is the supported range (-10, 10)
        valid_range = (-10.0, 10.0)
        if ai_range != valid_range:
            print(f"Warning: USB-231 has a fixed AI range of +/- 10V. Requested {ai_range} ignored.")
        
        # No UL command needed; hardware is fixed.

    def set_ao_range(self, ao_channel, ao_range):
        """
        Configures the output range for an Analog Output channel.
        [cite_start]The USB-231 has a fixed output range of +/- 10V[cite: 677].
        
        args:
            ao_channel (int): The channel to configure.
            ao_range (tuple): The (min, max) range desired.
        """
        valid_range = (-10.0, 10.0)
        if ao_range != valid_range:
            print(f"Warning: USB-231 has a fixed AO range of +/- 10V. Requested {ao_range} ignored.")

    def read_DI(self, channel):
        """
        Reads the state of a single digital channel (DIO0 - DIO7).
        [cite_start]Manual Page 18: "All digital I/O updates and samples are software-paced."[cite: 508].
        
        args:
            channel (int): The channel to read.
        returns:
            int: 1 (High) or 0 (Low).
        """
        try:
            # Universal Library exposes the USB-231's eight-bit DIO block as AUXPORT.
            bit_value = self.ul.d_bit_in(self.board_num, DigitalPortType.AUXPORT, channel)
            return bit_value
        except Exception as e:
            print(f"USB231 Error reading DIO{channel}: {e}")
            raise

    def write_DO(self, channel, data):
        """
        Writes data to a digital output channel.
        
        args:
            channel (int): The channel to write to.
            data (int/bool or list): 1/True for High, 0/False for Low.
        """
        try:
            if isinstance(data, (int, bool)):
                data = [data]

            for state in data:
                bit_val = 1 if state else 0
                self.ul.d_bit_out(self.board_num, DigitalPortType.AUXPORT, channel, bit_val)
        except Exception as e:
            print(f"USB231 Error writing DIO{channel}: {e}")
            raise

    def set_dio_direction(self, dio_channel, dio_direction):
        """
        Configures the physics of the digital pin (Input vs Output).
        [cite_start]Manual Page 18: "Each digital I/O line is bit-configurable as input or output."[cite: 505].
        
        args:
            dio_channel (int): The channel to configure.
            dio_direction (str): 'IN' or 'OUT'.
        """
        direction_str = str(dio_direction).upper()
        
        # Map string to UL Enum
        if 'I' in direction_str and 'OUT' not in direction_str:
            ul_dir = DigitalIODirection.IN
        else:
            ul_dir = DigitalIODirection.OUT

        try:
            # d_config_bit configures individual bits
            self.ul.d_config_bit(self.board_num, DigitalPortType.AUXPORT, dio_channel, ul_dir)
        except Exception as e:
            print(f"USB231 Error configuring DIO{dio_channel}: {e}")
            raise
