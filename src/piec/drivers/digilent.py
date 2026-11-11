"""
This is the parent class for MCC (formerly Digilent) DAQ devices
that use the Measurement Computing Universal Library (UL).

It inherits from Instrument and provides a common connection,
identification, and utility framework for all UL-based devices.

This driver requires the 'mcculw' library to be installed.
"""

from ctypes import c_double
import time

import numpy as np

from .instrument import Instrument


# --- Import the actual MCC Universal Library ---
# We try to import the library. If it fails, we set the
# library objects to None and the driver will raise an
# error on initialization.
try:
    from mcculw import ul
    from mcculw.enums import BoardInfo, ErrorCode, FunctionType, ScanOptions, Status
    from mcculw.ul import ULError
    from mcculw.device_info import DaqDeviceInfo
    mcc_ul_imported = True
except:
    print("Warning: 'mcculw' library not found.")
    print("The Digilent/MCC driver cannot be used without this library.")
    ul = None
    BoardInfo = None
    ErrorCode = None
    FunctionType = None
    ScanOptions = None
    Status = None
    ULError = None
    DaqDeviceInfo = None
    mcc_ul_imported = False


class Digilent(Instrument):
    """
    Parent class for Digilent/MCC instruments using the Universal Library.
    
    This class handles the connection and board identification,
    replacing the VISA/PiecManager logic from the Scpi class.
    
    The 'address' for this class is the MCC Board Number (e.g., "0").
    """
    
    def __init__(self, address, check_params=False, verbose=False, **kwargs):
        """
        Connects to the MCC DAQ device using its Board Number.
        
        Args:
            address (str or int): The MCC Board Number (e.g., "0" or 0).
            check_params (bool): Enable automatic parameter validation.
            verbose (bool): If True, prints status messages.
            **kwargs: Reserved for device-specific connection options.
        """
        if not mcc_ul_imported or ul is None:
            raise ImportError(
                "Cannot connect to an MCC/Digilent device because the "
                "'mcculw' library is not installed."
            )

        self._initialize_common_state(
            check_params=check_params,
            verbose=verbose,
        )

        try:
            # The 'address' is the board number, not a VISA string
            self.board_num = int(address)
        except (ValueError, TypeError):
            raise ValueError(
                f"Invalid address '{address}'. Must be an MCC Board Number "
                "(e.g., '0')."
            )
        
        # Store the (real) UL object and enums
        self.board = ul
        self.ul = ul  # Alias for child classes (e.g. USB231)
        self.ul_error = ULError
        self.error_codes = ErrorCode
        
        # Default capabilities
        self.ao_info = None
        self.max_rate = 5000 # Default safe rate for USB-231 (5kS/s)
        
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
            raise ConnectionError(
                f"Failed to connect to MCC board {self.board_num}. Error: {e}"
            ) from e

    def idn(self):
        """
        Returns an identification string from the Universal Library.

        This is the UL-equivalent of the SCPI ``*IDN?`` command.

        Returns:
            str: Identification string in ``Manufacturer,Model,Serial,Version`` format.
        """
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
        try:
            if self.verbose:
                print(f"Digilent: Flashing LED on board {self.board_num}...")
            self.board.flash_led(self.board_num)
        except self.ul_error as e:
            # We will just print the error, as this is a non-critical function
            print(f"Digilent: Could not flash LED. Error: {e}")

    # --- Hardware Background Scan (New) ---

    def read_AI_scan(self, ai_channel, points, rate):
        """
        Acquire a finite scan of one or more analog inputs.
        Use the device clock where available. A software fallback must
        document its timing and keep channel readings in the same scan.
        args:
            ai_channel (int or list[int]): One channel or a nonempty list of
                unique channels from the model's `ai_channel` capability.
            points (int): Number of samples to acquire per channel.
            rate (float): Requested sample rate in Hz per channel.
        Returns:
            data (pandas.DataFrame): 'Time' in seconds from scan start,
                followed by voltage columns in volts. One channel, including
                a one-element list, returns 'Time', 'Voltage'. Multiple
                channels return 'Time' followed by 'AI<n>' columns in
                selection order, where n is the DAQ channel number.
                data.attrs['sample_rate'] holds the actual per-channel rate in Hz.
        """
        scan = self._scan_analog_inputs(ai_channel, points, rate)
        return self._scan_dataframe(ai_channel, scan['time'], scan['values'], scan['rate'])

    def _scan_analog_inputs(self, ai_channel, points, rate, cancel_event=None, on_chunk=None):
        """Scan a contiguous MCC input span and select columns in request order."""
        channels = self._scan_channels(ai_channel)
        low, high = min(channels), max(channels)
        width = high - low + 1
        if isinstance(points, bool) or not isinstance(points, int) or points < 1:
            raise ValueError('points must be a positive integer')
        minimum_rate, aggregate_rate = self.ai_sample_rate
        if not minimum_rate <= rate <= aggregate_rate / width:
            raise ValueError('Requested rate exceeds the input scan limits')
        ranges = [self._ai_ul_range(ch) for ch in range(low, high + 1)]
        if any(value != ranges[0] for value in ranges):
            raise ValueError('All inputs in the scan span must use the same range')
        total = points * width
        if total > 20_000_000:
            raise ValueError('Scan exceeds 20 million buffered samples; reduce points')

        if cancel_event is not None and cancel_event.is_set():
            return {'values': np.empty((0, len(channels))), 'time': np.empty(0), 'rate': rate}
        values = np.empty((points, len(channels)))
        handle = self.ul.scaled_win_buf_alloc(total)
        if not handle:
            raise MemoryError('Could not allocate analog input scan buffer')
        columns = np.asarray(channels) - low
        options = ScanOptions.BACKGROUND | ScanOptions.SCALEDATA
        transferred = 0
        idle = False
        try:
            actual_rate = self.ul.a_in_scan(
                self.board_num, low, high, total, int(rate), ranges[0], handle, options)
            deadline = time.monotonic() + points / actual_rate + 5.0
            while True:
                status, count, _ = self.ul.get_status(self.board_num, FunctionType.AIFUNCTION)
                idle = status == Status.IDLE
                cancelled = cancel_event is not None and cancel_event.is_set()
                if idle or cancelled or on_chunk is not None:
                    available = min(total, count) // width
                    if available > transferred:
                        length = (available - transferred) * width
                        buffer = (c_double * length)()
                        self.ul.scaled_win_buf_to_array(handle, buffer, transferred * width, length)
                        block = values[transferred:available]
                        block[:] = np.asarray(buffer).reshape(-1, width)[:, columns]
                        if on_chunk is not None:
                            times = np.arange(transferred, available) / actual_rate
                            on_chunk({'values': block, 'time': times, 'rate': actual_rate})
                        transferred = available
                if idle or cancelled:
                    break
                if time.monotonic() >= deadline:
                    raise TimeoutError('Analog input scan timed out')
                time.sleep(0.01)
            return {'values': values[:transferred], 'time': np.arange(transferred) / actual_rate,
                    'rate': actual_rate}
        finally:
            try:
                self.ul.stop_background(self.board_num, FunctionType.AIFUNCTION)
            except Exception:
                if not idle:
                    raise
            self.ul.win_buf_free(handle)

    def write_waveform_scan(self, ao_channel, data, sample_rate):
        """
        Calculates and outputs a waveform using hardware background scan.
        Requires 'mcculw' and a supported board.
        
        args:
            ao_channel (int): Output channel.
            data (list/array): Waveform points.
            sample_rate (int): Output rate in Hz.
        """
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
            self.board.a_out_scan(self.board_num, ao_channel, ao_channel,
                                  num_points, sample_rate, current_range, 
                                  memhandle, options)
            print(f"Digilent: Started background scan on Ch {ao_channel}")
        except Exception as e:
            print(f"Digilent: Error starting scan: {e}")
            # Clean up memory if failed
            self.stop_output()
            raise

    def stop_output(self):
        """
        Stops any active background scan and frees memory.
        """
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
