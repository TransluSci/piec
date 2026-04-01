"""
This is an outline for how the arduino_stepper.py file should be like
"""
import time
import re
from ..utilities import PiecManager
from .stepper_motor import Stepper

class Geos_Stepper(Stepper):
    """
    This is the base level - instrument specific of the Arduino_Stepper used in our lab
    """
    num_steps = (0, 600) #typical step sizes (arduino code as limit of -300 to 300)
    direction = [0,1] #0 is CW 1 is CCW

    def __init__(self, address, **kwargs):
        """
        Connects to the instrument by opening a ResourceManager and talking to it (use PiecManager)
        Sets the instrument timeout and the steps_per_revolution to ensure (hardcode this value based on hardware specs)
        """
        # Ensure we use the correct baud rate for Arduino Serial
        kwargs.setdefault('baud_rate', 115200)
        super().__init__(address, **kwargs)
        
        # Configure the real instrument if not in virtual mode
        if not self.virtual:
            self.instrument.timeout = 20000 # 20s
            
        self.steps_per_revolution = 200 # default value, only change IFF change in hardware is also managed

    def idn(self):
        """
        Overwrites idn functionality to work with arduino
        """
        line = self.instrument.query('0,0') #calls in builtin method to check if serial communication works
        if "Complete" in line:
            return "Custom Arduino_Stepper Object at {}".format(self.instrument.resource_name)
                
        else:
            print("Timeout error occurred while waiting for the Arduino.")
            return "Not connected"

    def step(self, num_steps, direction):
        """
        Steps the stepper motor by sending a write string (via query) where the format is "{steps},{direction}"
        where direction = 0 is for CW and 1 is for CCW
        returns the current position after the stepper stops moving
        args:
            self (pyvisa.resources.asrl.not sure): Arduino
            num_steps (str/int): Desired step size, must be an integer value
            direction (str/int): [0,1] are the ONLY allowed values, 0 for CW 1 for CCW (not could be backwards)
        returns:
            current_position (int) The current position as read from the arduino
        """
        answer = self.instrument.query("{},{}".format(num_steps, direction)) #specially formatted string for arduino code to work. See arduino code under src\piec\drivers\Arduino\motor_control_serial_piec\motor_control_serial_piec.ino for more information
        number = int(re.search(r'-?\d+', answer).group())
                
        if "Complete" in answer:
            return number
        if "ERROR" in answer:
            print(answer)
        else: 
            print("Did not complete task")


    def set_zero(self):
        """
        Hardcoded command that sets the arduinos position tracker to zero. Sends a direction = 9 to set the zero
        """
        time.sleep(2) #ensure that arduino has time to recieve the data
        self.step(0,9)

    def read_position(self):
        """
        Reads the current position without stepping the stepper by sending in zero steps
        since the arduino already returns position with each step
        """
        time.sleep(2) #ensure that arduino has time to recieve the data
        position = self.step(0,0) #steps 0 steps, so doesnt change position
        if position is not None:
            return position
        else:
            print("Position unknown")