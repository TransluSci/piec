'''
This is for the EDC Model 522 DC Voltage/Current Calibrator.
Does NOT use SCPI commands.
Integrated from z_old/edc522/core.py.
'''
import re
from .dc_callibrator import DCCalibrator

class EDC522(DCCalibrator):
    """
    Specific Class for EDC Model 522. Supporting voltage and current sourcing.
    Inherits from the general DCCalibrator base class.
    """
    AUTODETECT_ID = ["522", "KROHN-HITE", "NOT PROGRAMMED", "NOTHING WRONG"]
    
    voltage_range = (-100, 100) # volts (without opt)
    current_range = (-0.1, 0.1) # amps

    # Capabilities defined for autodetection/high-level API consistency
    channel = [1]
    source_func = ['VOLT', 'CURR']
    voltage = (-111.1110, 111.1110) # Max physical limits including over-range
    current = (-0.111111, 0.111111)

    def idn(self):
        """
        Queries the instrument for its identification string.
        Hardcoded to ensure reliability since the physical instrument
        often returns echoes or status codes ('000') instead of the ID string.
        """
        ans = self.error()
        
        # "NOT PROGRAMMED" is a valid idle state, not a failure.
        valid_states = ['NOTHING WRONG', 'NOT PROGRAMMED']

        # We treat both "NOTHING WRONG" and "NOT PROGRAMMED" as success
        # because they confirm the instrument is connected and talking.
        if any(state in ans for state in valid_states):
            return "KROHN-HITE, 522, VER GEO"
        else:
            # If it returns "DATA ERROR" or "OVERLOAD", we pass that through
            return ans

    def error(self):
        """
        Queries the instrument for the current error status.
        """
        self.instrument.write("?")
        return self.instrument.read()

    def set_output(self, value, mode="voltage", **kwargs):
        """
        Formats and sends a command to set the instrument's output voltage or current.
        Automatically determines the appropriate range.
        Uses 'J00000' for digits if the value is exactly the maximum of a nominal range.

        Args:
            value (float or int): The desired output value.
            mode (str): "voltage", "current", or "crowbar".
            **kwargs: Additional parameters. Supports 'opt=True' to enable 1000V range.

        Returns:
            str: The 8-character command string sent to the instrument.
        """
        opt = kwargs.get('opt', False)
        # --- Define NOMINAL Ranges and Limits ---
        voltage_ranges_all = [
            (0.1, '0'), (10.0, '1'), (100.0, '2'), (1000.0, '3')
        ]
        current_ranges_all = [
            (0.01, '4'), (0.1, '5')
        ]

        # Filter ranges based on 'opt'
        if opt:
            voltage_ranges = voltage_ranges_all
            voltage_range_limits = (-1000.0, 1000.0)
        else:
            voltage_ranges = [r for r in voltage_ranges_all if r[1] in ('0', '1', '2')]
            voltage_range_limits = (-100.0, 100.0)

        current_ranges = current_ranges_all
        current_range_limits = (-0.1, 0.1)

        # Sort ranges by max value (ascending)
        voltage_ranges.sort(key=lambda x: x[0])
        current_ranges.sort(key=lambda x: x[0])

        # --- Input Validation / Crowbar / Mode Validation / Zero Handling ---
        if not isinstance(value, (int, float)):
            raise TypeError(f"Input value must be numeric (int or float), got {type(value)}")

        if mode == "crowbar":
            command = "00000000"
            self.instrument.write(command)
            return command

        if mode.lower() not in ("voltage", "current", "volt", "curr"):
            raise ValueError(f"Invalid mode: '{mode}'. Must be 'voltage', 'current', or 'crowbar'.")
        
        # Normalize mode
        if mode.lower() in ("voltage", "volt"):
            mode = "voltage"
        else:
            mode = "current"

        if abs(value) < 1e-12: # Use tolerance for floating point zero
            polarity = "+"
            zero_range_char = voltage_ranges[0][1] if mode == "voltage" else current_ranges[0][1]
            command = f"{polarity}000000{zero_range_char}"
            self.instrument.write(command)
            return command

        # --- Polarity / Abs Value ---
        polarity = "+" if value > 0 else "-"
        abs_value = abs(float(value))

        # --- Select Appropriate Ranges List ---
        if mode == "voltage":
            ranges_to_check = voltage_ranges
            min_limit, max_limit = voltage_range_limits
            unit = "Voltage"
        else: # mode == "current"
            ranges_to_check = current_ranges
            min_limit, max_limit = current_range_limits
            unit = "Current"

        # --- Check Overall Limits (Nominal) ---
        if not (min_limit <= value <= max_limit + 1e-9):
             raise ValueError(f"{unit} value {value} is out of the instrument's range ({min_limit} to {max_limit} with opt={opt})")

        # --- Find Range and Handle 'J' Code ---
        selected_range_max = None
        selected_range_char = None
        digits_str = None 
        processed = False
        epsilon = 1e-9 

        for i, (r_max, r_char) in enumerate(ranges_to_check):
            # Check if value is exactly the maximum for this range
            is_exact_max = abs(abs_value - r_max) < epsilon

            if is_exact_max:
                # Use 'J' code and THIS range's character
                selected_range_char = r_char
                digits_str = "J00000"
                processed = True
                break 

            # If not exact max, check if value fits strictly within this range
            elif abs_value < r_max - epsilon:
                selected_range_max = r_max
                selected_range_char = r_char
                processed = True
                break 

        if not processed:
             range_index = len(ranges_to_check) - 1
             selected_range_max = ranges_to_check[range_index][0]
             selected_range_char = ranges_to_check[range_index][1]
             processed = True 

        if not processed or selected_range_char is None:
             raise RuntimeError(f"Internal Error: Could not determine range or digits for {abs_value}.")

        # --- Calculate Digits IF NOT using 'J' code ---
        if digits_str is None: 
            if selected_range_max == 0:
                scaled_for_digits = 0.0
            else:
                scaled_for_digits = (abs_value / selected_range_max) * 1000000.0

            digits_int = int(round(scaled_for_digits))

            if digits_int >= 1000000:
                digits_int = 999999
            elif digits_int < 0: 
                digits_int = 0

            digits_str = "{:06d}".format(digits_int) 

        # --- Construct Command ---
        command = f"{polarity}{digits_str}{selected_range_char}"

        self.instrument.write(command)
        return command

    def set_voltage(self, voltage):
        """
        Convenience method to specifically set the output voltage.
        args:
            voltage (float): The desired output voltage in Volts.
        """
        return self.set_output(voltage, mode="voltage")

    def set_current(self, current):
        """
        Convenience method to specifically set the output current.
        args:
            current (float): The desired output current in Amps.
        """
        return self.set_output(current, mode="current")

    def output(self, on=True):
        """
        Turns the main output of the calibrator on or off.
        Usually, 'off' engages a 'crowbar' or short circuit at the output.
        args:
            on (bool): True to enable the output, False to disable it.
        """
        if not on:
            return self.set_output(0, mode="crowbar")
        # To turn back 'on' without changing value, we'd need to store state.
        # For now, following the simple crowbar logic.
        pass

    def reset(self):
        """
        Resets the instrument to a safe, known state (e.g., crowbar output).
        """
        return self.output(False)

def extract_number(input_string):
    """Helper for response parsing."""
    match = re.search(r'[+-]?\d+\.\d+E[+-]?\d+', input_string)
    if match:
        return match.group(0)
    else:
        return None
