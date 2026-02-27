"""
Virtual Instrument Base Module

This module provides the base class for virtual instruments used in simulation and testing.
It handles shared sample management and default material properties for ferroelectric simulations.
"""

from piec.simulation.fe_material import Ferroelectric
from piec.simulation.magnetic_material import MagneticSample
from piec.drivers.instrument import Instrument

class VirtualInstrument(Instrument):
    """
    Base class for all virtual instruments that share a common sample instance.
    
    This class manages a shared ferroelectric sample and a shared magnetic sample
    across all virtual instruments, ensuring consistent material properties 
    and state during simulations.
    
    Attributes:
        _shared_fe_sample (Ferroelectric): Class-level shared ferroelectric sample instance
        _shared_mag_sample (MagneticSample): Class-level shared magnetic sample instance
        sample (Ferroelectric): Instance-level reference to shared FE sample
        mag_sample (MagneticSample): Instance-level reference to shared magnetic sample
    """

    _shared_fe_sample = None
    _shared_mag_sample = None

    def __init__(self, *args, **kwargs):
        """
        Initialize virtual instrument with default ferroelectric sample if none exists.
        
        Creates a default Ferroelectric sample with PbTiO3-like properties on first instantiation.
        Subsequent instances will share the same sample object.

        Args:
            *args: Variable length argument list
            **kwargs: Arbitrary keyword arguments
        """
        if VirtualInstrument._shared_fe_sample is None:
            default_fe_material = {
                'ferroelectric': { #PZT
                    'a0': 824800,  # J m / (C^2 K)
                    'b': -838800000,  # J m^5 / C^4 (Negative for first-order transition)
                    'c': 7764000000,  # J m^9 / C^6
                    'T0': 388,    # Curie-Weiss Temp (K)
                    'Q12': -0.034,  # m^4 / C^2 (Electrostrictive coefficient)
                    's11': 12.7e-12,  # m^2 / N (Elastic compliance)
                    's12': -4.2e-12,  # m^2 / N (Elastic compliance)
                    'lattice_a': 0.402e-9,  # meters
                    "film_thickness": 5e-9,  # meters
                    'epsilon_r': 100,  # no unit
                    'leakage_resistance': 3e4,  # Ohms
                    'kinetic_damping': 1e-8, # V s m^2 / C
                },
                'substrate': {  # SrTiO3 substrate
                    'lattice_a': 0.3905e-9  # meters
                },
                'electrode': {  # Platinum electrodes
                    'screening_lambda': 0.05e-9,  # meters
                    'permittivity_e': 8.0,  # dimensionless
                    'area': 1.0e-10  # meters^2
                }
            }
            VirtualInstrument._shared_fe_sample = Ferroelectric(material_dict=default_fe_material)
            VirtualInstrument._shared_fe_sample.name = "virtual_fe_sample"
        
        if VirtualInstrument._shared_mag_sample is None:
            VirtualInstrument._shared_mag_sample = MagneticSample()
            
        self.sample = VirtualInstrument._shared_fe_sample
        self.mag_sample = VirtualInstrument._shared_mag_sample

    @classmethod
    def set_virtual_sample(cls, sample):
        """
        Set a new shared sample for all virtual instruments.

        Args:
            sample (Ferroelectric): New ferroelectric sample instance to share
        """
        cls._shared_sample = sample

    @property
    def virtual_sample(self):
        """
        Get the current shared sample instance.

        Returns:
            Ferroelectric: Current shared sample instance
        """
        return self._shared_sample

    @virtual_sample.setter
    def virtual_sample(self, sample):
        """
        Set a new shared sample for all instances of this class.

        Args:
            sample (Ferroelectric): New ferroelectric sample instance to share
        """
        self.__class__._shared_sample = sample
