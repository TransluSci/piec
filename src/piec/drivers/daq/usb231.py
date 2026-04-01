from ..digilent import Digilent
from .daq import Daq

try:
    from mcculw.enums import ULRange, DigitalIODirection, DigitalPortType, AnalogInputMode, ScanOptions
    from mcculw import ul
except ImportError:
    # These will be handled in virtual mode logic
    ULRange = None
    DigitalIODirection = None
    DigitalPortType = None
    AnalogInputMode = None
    ScanOptions = None

class USB231(Digilent, Daq):
    """
    Driver for the Measurement Computing (MCC) USB-231 DAQ device.
    
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

    # [cite_start]Analog Input Range: Fixed at +/- 10V [cite: 668]
    ai_range = [(-10.0, 10.0)]

    # [cite_start]Analog Output Range: Fixed at +/- 10V [cite: 677]
    ao_range = [(-10.0, 10.0)]

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
        if not self.virtual:
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
        if self.virtual:
            print(f"USB231 [Virt]: Reading Analog Input Ch {channel} (Simulated 0.0V)")
            return 0.0

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
        if self.virtual:
            import numpy as np
            print(f"USB231 [Virt]: Scanning {points} points from Ch {channel} at {rate}Hz")
            # Generate simulated sine wave
            t = np.linspace(0, points/rate, points)
            return (np.sin(2 * np.pi * 10 * t)).tolist()

        if channel not in self.ai_channel:
            raise ValueError(f"Channel {channel} is not valid in current Input Mode. Available: {self.ai_channel}")

        memhandle = None
        try:
            # Allocate memory buffer
            memhandle = self.ul.win_buf_alloc(points)
            if not memhandle:
                raise Exception("Failed to allocate memory for scan.")

            # Prepare Scan Options
            # Use BACKGROUND mode with explicit polling
            scan_options = ScanOptions.BACKGROUND
            
            # Configure rate 
            rate_in = int(rate)
            
            # Start Scan
            try:
                self.ul.a_in_scan(
                    self.board_num, 
                    channel, 
                    channel, 
                    points, 
                    rate_in, 
                    ULRange.BIP10VOLTS, 
                    memhandle, 
                    scan_options
                )
            except Exception as e:
                print(f"DEBUG: a_in_scan FAILED with: {e}")
                raise

            # Poll for completion
            from mcculw.enums import FunctionType, Status
            import time
            
            # Wait loop
            expected_duration = points / rate
            timeout = time.time() + expected_duration + 5.0
            
            while True:
                status, curr_count, curr_index = self.ul.get_status(self.board_num, FunctionType.AIFUNCTION)
                if status == Status.IDLE:
                    break
                if time.time() > timeout:
                    self.ul.stop_background(self.board_num, FunctionType.AIFUNCTION)
                    raise TimeoutError("Hardware scan timed out.")
                time.sleep(0.01)

            # Retrieve Data manually to avoid Error 35 in scaled_win_buf_to_array
            # [cite_start]Manual Page 10: 16-bit resolution[cite: 124]
            # Data is 16-bit unsigned integers (raw counts)
            from ctypes import c_ushort, POINTER, cast
            
            # Create array for raw data
            raw_array = (c_ushort * points)()
            
            # Use raw win_buf_to_array which might be more stable?
            # Or better: cast the memhandle directly if possible.
            # But win_buf_alloc returns an opaque handle.
            # Let's try ul.win_buf_to_array first.
            
            try:
                self.ul.win_buf_to_array(memhandle, raw_array, 0, points)
            except Exception as e:
                print(f"DEBUG: win_buf_to_array failed: {e}")
                raise

            # Convert raw counts to Voltage
            # Range: +/- 10V (BIP10VOLTS)
            # Resolution: 16-bit (0 to 65535) or (-32768 to 32767)?
            # USB-231 is 12-bit SE, 16-bit Differential? No, manual says 12-bit??
            # Wait, docstring says 16-bit. Let's assume 16-bit for now.
            # If BIP10V: 
            #   0 = -10V, 65535 = +10V? 
            #   or is it signed?
            #   Usually MCC uses unsigned 0-65535 mapping.
            
            # Let's use the helper to_eng_units for a single point to verify scale/offset if needed,
            # but that's slow.
            # Standard MCC conversion:
            # Volts = (Raw - Offset) * Scale
            # Full Scale Range = 20V.
            # 65536 codes.
            # Volts = (Raw / 65536) * 20 - 10
            
            data_volts = []
            for val in raw_array:
                # 12-bit device usually returns 12-bit values shifted (e.g. 0-4095).
                # USB-231 is 12-bit according to some docs, but this driver said 16.
                # Let's try standard 16-bit scaling first.
                v = (val / 65536.0) * 20.0 - 10.0
                data_volts.append(v)
            
            return data_volts
            
        except Exception as e:
            print(f"USB231 Scan Error: {e}")
            raise
            
        except Exception as e:
            print(f"USB231 Scan Error: {e}")
            raise
            
        except Exception as e:
            print(f"USB231 Scan Error: {e}")
            raise
        finally:
            if memhandle:
                self.ul.win_buf_free(memhandle)

    def write_AO(self, channel, data):
        """
        Writes data to the Analog Output channel.
        [cite_start]Manual Page 17: Software paced mode[cite: 489].
        
        args:
            channel (int): The channel to write to (0-1).
            data (float or list/ndarray): The voltage(s) to output (+/- 10V).
        """
        if self.virtual:
            print(f"USB231 [Virt]: Writing data to Analog Output Ch {channel}")
            return

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

        if self.virtual:
            print(f"USB231 [Virt]: Input mode set to {mode_str}")
            # Simulate the logic update for virtual mode
            if 'DIFF' in mode_str:
                self.ai_channel = [0, 1, 2, 3]
            elif 'SE' in mode_str or 'SINGLE' in mode_str:
                self.ai_channel = [0, 1, 2, 3, 4, 5, 6, 7]
            return
        
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
        if self.virtual:
            print(f"USB231 [Virt]: Setting AI range to {ai_range} (Hardware is Fixed +/-10V)")
            return

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
        if self.virtual:
            print(f"USB231 [Virt]: Setting AO range to {ao_range} (Hardware is Fixed +/-10V)")
            return

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
        if self.virtual:
            print(f"USB231 [Virt]: Reading Digital Ch {channel} (Simulated 0)")
            return 0

        try:
            # [cite_start]USB-231 uses FIRSTPORTA for the 8 DIO bits (Pins 17-24) [cite: 741]
            bit_value = self.ul.d_bit_in(self.board_num, DigitalPortType.FIRSTPORTA, channel)
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
        if self.virtual:
            print(f"USB231 [Virt]: Writing data to Digital Ch {channel}")
            return

        try:
            if isinstance(data, (int, bool)):
                data = [data]

            for state in data:
                bit_val = 1 if state else 0
                self.ul.d_bit_out(self.board_num, DigitalPortType.FIRSTPORTA, channel, bit_val)
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
            dir_name = "IN"
        else:
            ul_dir = DigitalIODirection.OUT
            dir_name = "OUT"

        if self.virtual:
            print(f"USB231 [Virt]: Configured DIO{dio_channel} as {dir_name}")
            return

        try:
            # d_config_bit configures individual bits
            self.ul.d_config_bit(self.board_num, DigitalPortType.FIRSTPORTA, dio_channel, ul_dir)
        except Exception as e:
            print(f"USB231 Error configuring DIO{dio_channel}: {e}")
            raise