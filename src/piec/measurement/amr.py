"""
AMR (Anisotropic Magnetoresistance) measurement module.

This module provides the measurement classes and helper functions for
performing AMR measurements. It re-exports the relevant classes from
the magneto_transport module to provide a clean, dedicated import path.

Usage:
    from piec.measurement.amr import AMR
    from piec.measurement.amr import MagnetoTransport
    from piec.measurement.amr import convert_angle_to_steps, convert_steps_to_angle
"""

from piec.measurement.magneto_transport import (
    MagnetoTransport,
    AMR,
    convert_angle_to_steps,
    convert_steps_to_angle,
    convert_field_to_voltage,
)

__all__ = [
    "MagnetoTransport",
    "AMR",
    "convert_angle_to_steps",
    "convert_steps_to_angle",
    "convert_field_to_voltage",
]
