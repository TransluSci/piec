from piec.drivers.stepper_motor.stepper_motor import Stepper
from piec.drivers.virtual_instrument import VirtualInstrument
import re

class VirtualStepper(VirtualInstrument, Stepper):
    """
    Virtual version of a Stepper that updates a shared magnetic sample.
    """
    def __init__(self, address="VIRTUAL", **kwargs):
        super().__init__(address=address, **kwargs)
        self.current_pos = 0
        self.steps_per_revolution = 200 # default

    def idn(self):
        return "Virtual Stepper"

    def step(self, steps, direction):
        # Update internal position
        if direction == 1: # CW
             self.current_pos += steps
        else:
             self.current_pos -= steps
        
        # Update shared sample orientation angle
        if self.sample is not None:
            delta_angle = steps * 360.0 / self.steps_per_revolution
            angle = self.sample.state.get('angle', 0.0)
            self.sample.state['angle'] = angle + (delta_angle if direction == 1 else -delta_angle)

        return self.current_pos

    def read_position(self):
        return self.current_pos

    def set_zero(self):
        self.current_pos = 0
        if self.sample is not None:
            self.sample.state['angle'] = 0.0
