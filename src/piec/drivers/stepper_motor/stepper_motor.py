"""
This is an outline for what the stepper_motor.py file should be like.

A stepper_motor is defined as an instrument that can control a stepper_motor (tbh naming should be changed to like stepper_driver but wtv)
"""
from ..instrument import Instrument
class Stepper(Instrument):
    # Initializer / Instance attributes
    """
    All steppers must be able to step!
    """

    def step(self, steps, direction):
        """
        Sends a command to the stepper to step in a certain direction
        """
