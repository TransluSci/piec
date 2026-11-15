"""Magnetic sample models (Level-2 hysteretic interface and Level-3 implementations)."""
from .hysteretic_magnetic_material import HystereticMagneticMaterial
from .magnetic_material import MagneticMaterial
from .arctan_moke import ArctanMOKE, MagneticSample

__all__ = ["HystereticMagneticMaterial", "MagneticMaterial", "ArctanMOKE", "MagneticSample"]
