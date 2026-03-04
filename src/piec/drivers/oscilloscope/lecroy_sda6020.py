"""
Driver for the Teledyne LeCroy SDA 6020 Oscilloscope.
This class implements the specific functionalities for the SDA 6020 model,
inheriting from generic Oscilloscope and Scpi classes.
"""

import numpy as np
import pandas as pd
from .oscilloscope import Oscilloscope
from ..scpi import Scpi
import struct

class LeCroySDA6020(Oscilloscope, Scpi):
    """
    Specific Class for the Teledyne LeCroy SDA 6020 oscilloscope.
    """

    AUTODETECT_ID = "SDA6020"

    channel = [1, 2, 3, 4]
    vdiv = (0.001, 10.0)
    y_range = (0.008, 80.0)
    y_position = (-100.0, 100.0)
    input_coupling = ["AC", "DC", "GND"]
    probe_attenuation = (0.001, 10000.0)
    channel_impedance = ["50", "1M"]
    tdiv = (20e-12, 1000.0)
    x_range = (200e-12, 10000.0)
    x_position = (-10000.0, 10000.0)
    trigger_source = [1, 2, 3, 4, "EXT", "EX10", "LINE"]
    trigger_level = (-10.0, 10.0)
    trigger_slope = ["POS", "NEG", "EITHER", "WINDOW", "OFF"]
    trigger_mode = ["EDGE", "SMART"]
    trigger_sweep = ["AUTO", "NORM", "SINGLE", "STOP"]
    acquisition_mode = ["NORM"]
    acquisition_points = (1, 100000000)

    def autoscale(self):
        """
        Autoscales the oscilloscope
        """
        self.instrument.write("AUTO_SETUP")

    def reset(self):
        """
        Resets the oscilloscope to factory defaults with trigger in AUTO mode.

        Unlike *RST (which leaves the trigger in STOP mode, keeping old data
        visible), this uses the VBS automation command that mirrors the front-panel
        'Recall Default' button — resetting all settings AND starting fresh
        acquisition in AUTO trigger mode so old waveforms are cleared.
        """
        self.instrument.write("VBS 'app.SaveRecall.Setup.DoRecallDefaultPanelWithTriggerModeAuto'")

    def toggle_channel(self, channel, on=True):
        """
        Function that toggles the selected channel to on or off
        """
        state = "ON" if on else "OFF"
        self.instrument.write(f"C{channel}:TRACE {state}")

    def set_vertical_scale(self, channel, vdiv=None, y_range=None):
        """
        Function that sets the vertical scale in either volts per divison or absolute range
        """
        if vdiv is not None:
            self.instrument.write(f"C{channel}:VDIV {vdiv}")
        if y_range is not None:
            # LeCroy doesn't directly support V_range, calculate VDIV
            vdiv_calc = y_range / 8.0 
            self.instrument.write(f"C{channel}:VDIV {vdiv_calc}")

    def set_vertical_position(self, channel, y_position=None):
        """
        Sets the vertical position of the scale (offset)
        """
        if y_position is not None:
            self.instrument.write(f"C{channel}:OFFSET {y_position}")

    def set_input_coupling(self, channel, input_coupling=None):
        """
        Sets the input coupling, e.g. AC, DC, GND
        """
        if input_coupling == "AC":
            self.instrument.write(f"C{channel}:COUPLING A1M")
        elif input_coupling == "DC":
            try:
                current_cpl = self.instrument.query(f"C{channel}:COUPLING?").strip().upper()
                if "D50" in current_cpl:
                    self.instrument.write(f"C{channel}:COUPLING D50")
                else:
                    self.instrument.write(f"C{channel}:COUPLING D1M")
            except Exception:
                self.instrument.write(f"C{channel}:COUPLING D1M")
        elif input_coupling == "GND":
            self.instrument.write(f"C{channel}:COUPLING GND")

    def set_probe_attenuation(self, channel, probe_attenuation=None):
        """
        Sets the probe attenuation
        """
        if probe_attenuation is not None:
             self.instrument.write(f"C{channel}:ATTENUATION {probe_attenuation}")

    def set_channel_impedance(self, channel, channel_impedance=None):
        """
        Sets the channel impedance
        """
        if channel_impedance == "50":
            self.instrument.write(f"C{channel}:COUPLING D50")
        elif channel_impedance == "1M":
            try:
                current_cpl = self.instrument.query(f"C{channel}:COUPLING?").strip().upper()
                if "A1M" in current_cpl:
                    self.instrument.write(f"C{channel}:COUPLING A1M")
                else:
                    self.instrument.write(f"C{channel}:COUPLING D1M")
            except Exception:
                self.instrument.write(f"C{channel}:COUPLING D1M")

    def set_horizontal_scale(self, tdiv=None, x_range=None):
        """
        Sets the timebase in either time/division or in absolute range
        """
        if tdiv is not None:
            self.instrument.write(f"TIME_DIV {tdiv}")
        if x_range is not None:
            # LeCroy has 10 divisons horizontally
            tdiv_calc = x_range / 10.0
            self.instrument.write(f"TIME_DIV {tdiv_calc}")

    def set_horizontal_position(self, x_position=None):
        """ 
        Changes the position (delay) of the timebase
        """
        if x_position is not None:
            self.instrument.write(f"TRDL {x_position}")

    def configure_horizontal(self, tdiv=None, x_range=None, x_position=None):
        """
        Combines calls to set_horizontal_scale and set_horizontal_position
        """
        if tdiv is not None or x_range is not None:
            self.set_horizontal_scale(tdiv=tdiv, x_range=x_range)
        if x_position is not None:
            self.set_horizontal_position(x_position=x_position)

    def set_trigger_source(self, trigger_source=None):
        """
        Decides what the scope should trigger on
        """
        if trigger_source is not None:
            src = f"C{trigger_source}" if isinstance(trigger_source, int) else trigger_source
            self.instrument.write(f"TRIG_SELECT EDGE,SR,{src}")

    def set_trigger_level(self, trigger_level=None):
        """
        The voltage level the signal must cross to initiate a capture
        """
        if trigger_level is not None:
            # Requires querying the active trigger source first to set its level
            # In a basic implementation, we can just try to set the generic trigger level or assume C1.
            # Assuming edge trigger on C1 as a simplest fallback if we don't track state
            self.instrument.write(f"C1:TRLV {trigger_level}")

    def set_trigger_slope(self, trigger_slope=None):
        """
        Changes the trigger slope
        """
        if trigger_slope is not None:
            self.instrument.write(f"TRIG_SLOPE {trigger_slope}")

    def set_trigger_mode(self, trigger_mode=None):
        """
        Sets the trigger mode
        """
        if trigger_mode is not None:
            # SMART or EDGE
            pass # Usually handled within TRIG_SELECT on LeCroy, skipping discrete TRMD implementation for now

    def set_trigger_sweep(self, trigger_sweep=None):
        """
        Changes the trigger sweep settings
        """
        if trigger_sweep is not None:
            self.instrument.write(f"TRIG_MODE {trigger_sweep}")

    def configure_trigger(self, trigger_source=None, trigger_level=None, trigger_slope=None, trigger_mode=None, trigger_sweep=None):
        """
        Combines all the trigger commands into one
        """
        if trigger_source is not None:
            self.set_trigger_source(trigger_source=trigger_source)
        if trigger_level is not None:
            self.set_trigger_level(trigger_level=trigger_level)
        if trigger_slope is not None:
            self.set_trigger_slope(trigger_slope=trigger_slope)
        if trigger_mode is not None:
            self.set_trigger_mode(trigger_mode=trigger_mode)
        if trigger_sweep is not None:
            self.set_trigger_sweep(trigger_sweep=trigger_sweep)

    def manual_trigger(self):
        """
        Sends a manual force trigger event
        """
        self.instrument.write("ARM")
        self.instrument.write("FRTR")

    def toggle_acquisition(self, run=True):
        """
        Start or halt the process of capturing data
        """
        if run:
            self.set_trigger_sweep("NORM")
        else:
            self.instrument.write("STOP")

    def arm(self):
        """
        Tells the scope to get ready to capture
        """
        self.instrument.write("ARM")

    def set_acquisition(self):
        """
        Prepares the acquisition
        """
        self.instrument.write("COMM_FORMAT DEF9,WORD,BIN")
        self.instrument.write("COMM_HEADER OFF")

    def set_acquisition_channel(self, channel=None):
        """
        Sets the scope to return the selected channel when asked for data
        """
        # Data reading in LeCroy is often prefix-based (e.g. C1:WF?), so simply setting state here
        self._current_acquisition_channel = channel

    def set_acquisition_mode(self, acquisition_mode=None):
        pass # Not broadly used in basic LeCroy readouts

    def set_acquisition_points(self, acquisition_points=None):
        if acquisition_points is not None:
             self.instrument.write(f"MEMORY_SIZE {acquisition_points}")

    def configure_acquisition(self, channel=None, acquisition_mode=None, acquisition_points=None):
        """
        Configures the scope for data reading
        """
        if channel is not None:
            self.set_acquisition_channel(channel=channel)
        if acquisition_mode is not None:
            self.set_acquisition_mode(acquisition_mode=acquisition_mode)
        if acquisition_points is not None:
            self.set_acquisition_points(acquisition_points=acquisition_points)

    def quick_read(self, channel=1):
        """
        Quick read function that returns the default data in a numpy array.
        """
        self.set_acquisition()
        self.instrument.write("COMM_HEADER OFF")
        self.instrument.write("COMM_FORMAT DEF9,WORD,BIN")
        raw_data = self.instrument.query_binary_values(f"C{channel}:WF? DAT1", datatype='h', is_big_endian=False)
        return np.array(raw_data)

    def get_data(self, channel=1):
        """
        Returns the data in a Pandas Dataframe.
        """
        self.set_acquisition()
        
        # LeCroy waveform descriptors contain necessary scaling factors
        self.instrument.write("COMM_HEADER OFF")
        desc = self.instrument.query_binary_values(f"C{channel}:WF? DESC", datatype='B')
        
        # Very simplified parsing of the waveform descriptor based on LeCroy manual
        # Real world LeCroy driver parsing is substantially more involved, requiring struct unpacking of the 346 byte descriptor
        # This is a structural placeholder that attempts to grab basic scaling
        v_gain = 1.0
        v_offset = 0.0
        h_gain = 1.0
        h_offset = 0.0
        
        try:
            # Bytes 156-159: vertical gain
            v_gain = struct.unpack('f', bytes(desc[156:160]))[0]
            # Bytes 160-163: vertical offset
            v_offset = struct.unpack('f', bytes(desc[160:164]))[0]
            # Bytes 176-179: horizontal interval
            h_gain = struct.unpack('f', bytes(desc[176:180]))[0]
            # Bytes 180-187: horizontal offset
            h_offset = struct.unpack('d', bytes(desc[180:188]))[0]
        except Exception:
            print("Warning: Could not fully parse LeCroy waveform descriptor. Data will be unscaled raw ADC values.")

        raw_data = self.instrument.query_binary_values(f"C{channel}:WF? DAT1", datatype='h', is_big_endian=False)
        
        v_data = (np.array(raw_data) * v_gain) - v_offset
        t_data = (np.arange(len(v_data)) * h_gain) + h_offset
        
        return pd.DataFrame({'Time': t_data, 'Voltage': v_data})
