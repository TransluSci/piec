"""
Virtual Instrument Base Module

This module provides the base class for virtual instruments used in simulation and testing.
It handles shared sample management and default material properties for ferroelectric simulations.
"""

from piec.simulation.fe_material import Ferroelectric
from piec.simulation.magnetic_material import MagneticSample


class VirtualInstrument():
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
                # SRO / PZT(52/48) / Pt stack — calibrated to give
                # Pr ≈ 50 µC/cm², Vc ≈ 2 V for a 30 nm film.
                #
                # Landau convention: E = a·P + b·P³ + c·P⁵,  V = E·d
                # Renormalized at run-time:
                #   a_tilde = a0·(T − T0) + a_strain + a_depol
                #   b_tilde = b + 4·Q12²/(s11+s12)
                #   c_tilde = c
                #
                # With lattice_a(fe) == lattice_a(substrate) the strain term
                # is zero, so a_tilde ≈ a0·(300 − 673) = −2.0×10⁸ J·m/C².
                # With permittivity_e = 1e6 the depolarization term is ~0.
                # b_tilde = −1.287×10⁹ + 8.87×10⁸ = −4.0×10⁸  (first-order)
                # c_tilde = 5.0×10⁹
                # → Pr ≈ 0.494 C/m² = 49 µC/cm², Ec ≈ 61 MV/m, Vc(30nm) ≈ 1.8 V
                #
                # kinetic_damping adds frequency dependence via
                #   dP/dt = (V − V_Landau(P)) / γ
                # γ = 2×10⁻⁷ V·s·m²/C  →  characteristic switching time ≈ 200 ns
                # so loops shrink noticeably above ~1 MHz.
                'ferroelectric': {
                    'a0': 5.362e5,      # J·m/(C²·K)  — positive (ferroelectric below T0)
                    'b': -1.287e9,      # J·m⁵/C⁴     — negative (first-order transition)
                    'c': 5.0e9,         # J·m⁹/C⁶
                    'T0': 673.0,        # K  (PZT 52/48 Curie temperature)
                    'Q12': -0.046,      # m⁴/C²  electrostrictive coefficient
                    's11': 14.1e-12,    # m²/N   elastic compliance
                    's12': -4.56e-12,   # m²/N
                    'lattice_a': 0.395e-9,   # m  (matched to SRO → zero epitaxial strain)
                    'film_thickness': 20e-9, # m
                    'epsilon_r': 50,         # relative permittivity (reduced for clean demo loop)
                    'leakage_resistance': 10e12,  # Ω  (low-leakage device)
                },
                'substrate': {   # SrRuO3 bottom electrode / substrate
                    'lattice_a': 0.395e-9  # m
                },
                'electrode': {   # Pt top electrode
                    'screening_lambda': 0.05e-9,  # m  (Thomas-Fermi length)
                    'permittivity_e': 1e6,         # large → depolarization ≈ 0
                    'area': 1.0e-10               # m²
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
