from piec.drivers.stepper_motor.stepper_motor import Stepper
from piec.drivers.virtual_instrument import VirtualInstrument
import re

class VirtualStepper(VirtualInstrument, Stepper):
    """
    Virtual version of a Stepper that updates a shared magnetic sample.
    """
    def __init__(self, address="VIRTUAL", **kwargs):
        VirtualInstrument.__init__(self, address=address)
        Stepper.__init__(self, address=address, **kwargs)
        self.current_pos = 0
        self.steps_per_revolution = 200 # default

    def idn(self):
        return "Virtual Stepper"

    def step(self, num_steps, direction):
        # Update internal position
        if direction == 1: # CW
             self.current_pos += num_steps
        else:
             self.current_pos -= num_steps
        
        # Update shared magnetic sample angle
        if hasattr(self, 'mag_sample') and self.mag_sample:
            # Convert steps to degrees (assuming 200 steps/rev)
            delta_angle = (num_steps * 360.0 / self.steps_per_revolution)
            if direction == 1: # CW
                self.mag_sample.current_angle += delta_angle
            else: # CCW
                self.mag_sample.current_angle -= delta_angle

        return self.current_pos

    def read_position(self):
        return self.current_pos

    def set_zero(self):
        self.current_pos = 0
        if hasattr(self, 'mag_sample') and self.mag_sample:
            self.mag_sample.current_angle = 0
