"""
Simulation module for material models, role-specific contracts, and virtual benches.
"""

from __future__ import annotations

from .contracts import (
    AngleDependentResistanceContract,
    AwgWaveformHook,
    CalibratorFieldHook,
    CapacitiveLoad,
    DeterministicTimebase,
    DiodeLoad,
    DmmVoltageReaderHook,
    ElectricalLoadContract,
    FieldResponsiveMaterialContract,
    LoadMode,
    LoadResponse,
    LockinTransportHook,
    ResistorLoad,
    ScopeChannelHook,
    SimulationRole,
    SourcemeterLoadHook,
    StepperAngleHook,
    WaveformResponsiveMaterialContract,
)
from .fe_material import (
    Dielectric,
    Ferroelectric,
    Material,
    Resistor,
)
from .hysteretic_magnetic_material import HystereticMagneticMaterial
from .magnetic_material import MagneticSample

__all__ = [
    "AngleDependentResistanceContract",
    "AwgWaveformHook",
    "CalibratorFieldHook",
    "CapacitiveLoad",
    "DeterministicTimebase",
    "Dielectric",
    "DiodeLoad",
    "DmmVoltageReaderHook",
    "ElectricalLoadContract",
    "Ferroelectric",
    "FieldResponsiveMaterialContract",
    "HystereticMagneticMaterial",
    "LoadMode",
    "LoadResponse",
    "LockinTransportHook",
    "MagneticSample",
    "Material",
    "Resistor",
    "ResistorLoad",
    "ScopeChannelHook",
    "SimulationRole",
    "SourcemeterLoadHook",
    "StepperAngleHook",
    "WaveformResponsiveMaterialContract",
]
