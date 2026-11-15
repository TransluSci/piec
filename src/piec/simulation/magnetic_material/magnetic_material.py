"""Backward-compatible alias module for Level-2 hysteretic magnetic material."""
from .hysteretic_magnetic_material import HystereticMagneticMaterial

MagneticMaterial = HystereticMagneticMaterial

__all__ = ["HystereticMagneticMaterial", "MagneticMaterial"]
