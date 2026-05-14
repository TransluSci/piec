"""
This is the parent class for MCC (formerly Digilent) DAQ devices
that use the Measurement Computing Universal Library (UL).

It inherits from Instrument and provides a common connection,
identification, and utility framework for all UL-based devices.

This driver requires the 'mcculw' library to be installed.
"""



# --- Import the actual MCC Universal Library ---
# We try to import the library. If it fails, we set the
# library objects to None and the driver will raise an
# error on initialization.
try:
    from mcculw import ul
    from mcculw.enums import BoardInfo, ErrorCode
    from mcculw.ul import ULError
    from mcculw.device_info import DaqDeviceInfo
    mcc_ul_imported = True
except:
    print("Warning: 'mcculw' library not found.")
    print("The Digilent/MCC driver cannot be used without this library.")
    ul = None
    BoardInfo = None
    ErrorCode = None
    ULError = None
    DaqDeviceInfo = None
    mcc_ul_imported = False


class Digilent():
    """
    Parent class for Digilent/MCC instruments using the Universal Library.
    
    This class handles the connection and board identification,
    replacing the VISA/PiecManager logic from the Scpi class.
    
    The 'address' for this class is the MCC Board Number (e.g., "0").
    """
    
    def __init__(self, address, verbose=False, **kwargs):
        """
        Connects to the MCC DAQ device using its Board Number.
        
        Args:
            address (str or int): The MCC Board Number (e.g., "0" or 0)
                                or "VIRTUAL".
            verbose (bool): If True, prints status messages.
            **kwargs: Additional arguments for the base Instrument class.
        """
        # --- Check if the required library was imported ---
        if not mcc_ul_imported or ul is None:
            print("Warning: 'mcculw' library not found. Falling back to VIRTUAL mode for Digilent driver.")
            # Force virtual mode to prevent crashes
            self.is_virtual_mode = True
        else:
            # --- FIX: Store the user's intended mode ---
            # We check the 'address' passed by the user, not the 'self.virtual'
            # flag from the parent, which is always True.
            self.is_virtual_mode = (str(address).upper() == 'VIRTUAL')
        self.verbose = verbose

        try:
            # The 'address' is the board number, not a VISA string
            self.board_num = int(address)
        except (ValueError, TypeError):
            if self.is_virtual_mode:
                # This is a VIRTUAL connection
                self.board_num = 0 
            else:
                # This is an invalid address
                raise ValueError(f"Invalid address '{address}'. "
                                 "Must be a MCC Board Number (e.g., '0') or 'VIRTUAL'.")
        
        # We call super().__init__ with "VIRTUAL" to bypass PiecManager
        # but still get the auto-check framework. This is internal.
        super().__init__(address="VIRTUAL", verbose=verbose, **kwargs)
        
        # Restore the correct virtual status based on user input, 
        # since we forced "VIRTUAL" to Instrument to bypass VISA logic.
        self.virtual = self.is_virtual_mode
        
        
        # Store the (real) UL object and enums
        self.board = ul
        self.ul = ul  # Alias for child classes (e.g. USB231)
        self.ul_error = ULError
        self.error_codes = ErrorCode
        
        # Default capabilities
        self.ao_info = None
        self.max_rate = 5000 # Default safe rate for USB-231 (5kS/s)
        
        # --- FIX: Check our stored 'is_virtual_mode' flag ---
        if self.is_virtual_mode:
            print(f"Digilent: VIRTUAL mode for board {self.board_num} (Digilent does not support VISA).")
            self.dev_name = "VIRTUAL_DEVICE"
        else:
            # This is a real connection attempt
            if self.verbose:
                print(f"Digilent: Connecting to board {self.board_num}...")
            try:
                # Check if board exists and get its name (this acts as a connection check)
                self.dev_name = self.board.get_board_name(self.board_num)
                print(f"Digilent: Connected to {self.dev_name} on board {self.board_num}.")
                
                # Fetch Device Info
                if DaqDeviceInfo:
                    try:
                        dev_info = DaqDeviceInfo(self.board_num)
                        if dev_info.supports_analog_output:
                            self.ao_info = dev_info.get_ao_info()
                    except Exception as e:
                        if self.verbose:
                            print(f"Digilent: Could not fetch AO info: {e}")

            except ULError as e:
                raise ConnectionError(f"Failed to connect to MCC board {self.board_num}. Error: {e}")

    def idn(self):
        """
        Returns an identification string from the Universal Library.

        This is the UL-equivalent of the SCPI ``*IDN?`` command.

        Returns:
            str: Identification string in ``Manufacturer,Model,Serial,Version`` format.
        """
        if self.is_virtual_mode:
            return f"Measurement_Computing,VIRTUAL_DEVICE,s/n_virtual,ver_UL"
        
        try:
            # Re-fetch the name in case it changed (unlikely, but good practice)
            dev_name = self.board.get_board_name(self.board_num)
            # Serial number retrieval is not a standard UL call, so
            # we provide a placeholder.
            serial = "s/n_unknown"
            return f"Measurement_Computing,{dev_name},{serial},ver_UL"
        except self.ul_error as e:
            print(f"Digilent: Could not get IDN. Error: {e}")
            return "Measurement_Computing,Unknown_Device,s/n_unknown,ver_UL_error"

    # --- Base Universal Library Commands ---
    # These mirror the SCPI command set for a consistent interface
    # across all instrument types.

    def reset(self):
        """
        Resets the DAQ device to a known idle state.

        This is the UL-equivalent of the SCPI ``*RST`` command.
        Stops any active background scans and re-initialises the
        internal state tracker.
        """
        if self.is_virtual_mode:
            if self.verbose:
                print(f"Digilent: (Virtual) Resetting board {self.board_num}...")
            self._initialize_state()
            return

        # Stop any running background operations
        try:
            from mcculw.enums import FunctionType
            self.board.stop_background(self.board_num, FunctionType.AIFUNCTION)
        except Exception:
            pass
        try:
            from mcculw.enums import FunctionType
            self.board.stop_background(self.board_num, FunctionType.AOFUNCTION)
        except Exception:
            pass

        self._initialize_state()
        if self.verbose:
            print(f"Digilent: Reset board {self.board_num}.")

    def clear(self):
        """
        Clears the device's error / status state.

        This is the UL-equivalent of the SCPI ``*CLS`` command.
        The MCC Universal Library does not maintain a persistent status
        register, so this is effectively a no-op.
        """
        if self.verbose:
            print(f"Digilent: Clear (no-op for UL — no status register).")

    def error(self):
        """
        Queries the device's most recent error status or message.

        This is the UL-equivalent of the SCPI ``*ESR?`` / ``SYST:ERR?`` query.
        
        Returns:
            str: The error message.
        """
        if self.is_virtual_mode:
            return "No errors."
            
        try:
            # --- FIX: Corrected function name from get_error_message to get_err_msg ---
            message = self.board.get_err_msg(self.error_codes.NOERRORS)
            return message
        except self.ul_error as e:
            return f"Failed to get error message. Error: {e}"
        except AttributeError:
            # This handles the case where the ul object itself is missing the function
            return "Error: ul.get_err_msg function not found. Is 'mcculw' installed correctly?"

    def wait(self):
        """
        Blocks until all pending background operations have completed.

        This is the UL-equivalent of the SCPI ``*WAI`` command.
        Polls the AI and AO background scan status until both are idle.
        """
        if self.is_virtual_mode:
            return

        import time
        try:
            from mcculw.enums import FunctionType, Status
        except ImportError:
            return

        timeout = time.time() + 30.0  # 30 second safety timeout
        while time.time() < timeout:
            try:
                ai_status, _, _ = self.board.get_status(self.board_num, FunctionType.AIFUNCTION)
                ao_status, _, _ = self.board.get_status(self.board_num, FunctionType.AOFUNCTION)
                if ai_status == Status.IDLE and ao_status == Status.IDLE:
                    return
            except Exception:
                return  # If status query fails, assume idle
            time.sleep(0.01)

        print("Digilent: wait() timed out after 30 seconds.")

    def self_test(self):
        """
        Runs a basic connectivity self-test.

        This is the UL-equivalent of the SCPI ``*TST?`` command.
        The MCC Universal Library does not have a formal self-test routine,
        so this verifies communication by querying the board name.

        Returns:
            str: ``'0'`` for pass, ``'1'`` for fail.
        """
        if self.is_virtual_mode:
            return "0"

        try:
            self.board.get_board_name(self.board_num)
            return "0"  # Pass
        except Exception as e:
            print(f"Digilent: Self-test failed. Error: {e}")
            return "1"  # Fail

    def operation_complete(self):
        """
        Queries whether all background operations have finished.

        This is the UL-equivalent of the SCPI ``*OPC?`` command.

        Returns:
            str: ``'1'`` when all operations are complete, ``'0'`` otherwise.
        """
        if self.is_virtual_mode:
            return "1"

        try:
            from mcculw.enums import FunctionType, Status
            ai_status, _, _ = self.board.get_status(self.board_num, FunctionType.AIFUNCTION)
            ao_status, _, _ = self.board.get_status(self.board_num, FunctionType.AOFUNCTION)
            if ai_status == Status.IDLE and ao_status == Status.IDLE:
                return "1"
            return "0"
        except Exception:
            return "1"  # If status query fails, assume complete

    def close(self):
        """
        Releases the DAQ device from the Universal Library.

        This has no direct SCPI equivalent — it is specific to DAQ hardware
        that must be explicitly released.
        """
        if self.is_virtual_mode:
            if self.verbose:
                print(f"Digilent: (Virtual) Releasing board {self.board_num}...")
            return

        try:
            if self.verbose:
                print(f"Digilent: Releasing board {self.board_num}...")
            self.board.release_daq_device(self.board_num)
        except self.ul_error as e:
            print(f"Digilent: Error releasing device. Error: {e}")

    def initialize(self):
        """
        Convenience method that resets and clears the device to bring it
        to a known good starting state.

        Calls :meth:`reset` followed by :meth:`clear`.
        """
        self.reset()
        self.clear()

    # --- UL-Specific Utilities ---

    def flash_led(self):
        """
        Flashes the LED on the device to physically identify it.
        (Note: Not supported by all boards, e.g., USB-231)
        """
        if self.is_virtual_mode:
            if self.verbose:
                print(f"Digilent: (Virtual) Flashing LED on board {self.board_num}...")
            return
            
        try:
            if self.verbose:
                print(f"Digilent: Flashing LED on board {self.board_num}...")
            self.board.flash_led(self.board_num)
        except self.ul_error as e:
            # We will just print the error, as this is a non-critical function
            print(f"Digilent: Could not flash LED. Error: {e}")

    # --- Hardware Background Scan (New) ---

    def write_waveform_scan(self, channel, data, sample_rate):
        """
        Calculates and outputs a waveform using hardware background scan.
        Requires 'mcculw' and a supported board.
        
        args:
            channel (int): Output channel.
            data (list/array): Waveform points.
            sample_rate (int): Output rate in Hz.
        """
        if self.is_virtual_mode:
            print(f"Digilent [Virt]: Started background scan on Ch {channel} at {sample_rate} Hz")
            return

        try:
            from ctypes import cast, POINTER, c_double
            from mcculw.enums import ScanOptions, FunctionType, ULRange
        except ImportError:
            print("Digilent: Cannot perform scan. ctypes or enums missing.")
            return

        # Stop previous scan
        self.stop_output()

        num_points = len(data)
        
        # Allocate Windows memory buffer (requires mcculw.ul)
        memhandle = self.board.scaled_win_buf_alloc(num_points)
        self._active_memhandle = memhandle # Keep reference
        
        # Copy data to buffer
        data_array = cast(memhandle, POINTER(c_double))
        for i in range(num_points):
            data_array[i] = float(data[i])

        # Configure Options
        options = ScanOptions.BACKGROUND | ScanOptions.CONTINUOUS | ScanOptions.SCALEDATA
        
        # Determine Range
        current_range = ULRange.BIP10VOLTS # Default fallback
        if self.ao_info and self.ao_info.supported_ranges:
            current_range = self.ao_info.supported_ranges[0]
            
        # Debug Clipping
        if len(data) > 0:
            max_val = max(abs(x) for x in data)
            # Only print info if verbose, but ALWAYS print warning if clipping
            if self.verbose:
                print(f"Digilent: Scan Range={current_range}, Max Voltage={max_val:.3f}")
            
            if max_val > 10.0:
                print(f"WARNING: Waveform Amplitude {max_val:.2f}V exceeds +/- 10V! Clipping will occur.")

        try:
            # Start Scan
            # Note: channel argument is start_chan, end_chan
            self.board.a_out_scan(self.board_num, channel, channel, 
                                  num_points, sample_rate, current_range, 
                                  memhandle, options)
            print(f"Digilent: Started background scan on Ch {channel}")
        except Exception as e:
            print(f"Digilent: Error starting scan: {e}")
            # Clean up memory if failed
            self.stop_output()
            raise

    def stop_output(self):
        """
        Stops any active background scan and frees memory.
        """
        if self.is_virtual_mode:
            return

        try:
            from mcculw.enums import FunctionType
            self.board.stop_background(self.board_num, FunctionType.AOFUNCTION)
        except Exception:
            pass # Ignore if no scan running

        # Free memory
        if hasattr(self, '_active_memhandle') and self._active_memhandle:
            try:
                self.board.win_buf_free(self._active_memhandle)
            except Exception:
                pass
            self._active_memhandle = None