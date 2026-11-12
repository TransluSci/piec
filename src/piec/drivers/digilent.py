"""
Deprecated compatibility shim for ``piec.drivers.digilent``.

Please import ``MCC`` from ``piec.drivers.mcc`` instead of ``Digilent`` from
``piec.drivers.digilent``.

# TODO: Remove digilent.py deprecation shim in v0.2.0 (after one release cycle).
"""

import warnings
from . import mcc as _mcc
from .mcc import (
    MCC,
    ul,
    BoardInfo,
    ErrorCode,
    ULError,
    DaqDeviceInfo,
    mcc_ul_imported,
)


def __getattr__(name):
    if name == "Digilent":
        warnings.warn(
            "'piec.drivers.digilent.Digilent' is deprecated and will be removed "
            "in v0.2.0; use 'from piec.drivers.mcc import MCC' instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return _mcc.MCC
    if hasattr(_mcc, name):
        return getattr(_mcc, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
