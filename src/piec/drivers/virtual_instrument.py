"""
Virtual Instrument Base Module

This module provides the base class for virtual instruments used in simulation and testing.
It manages shared sample state across virtual instrument instances without coupling to
concrete sample physics models.
"""

import operator
import warnings

from .instrument import Instrument


def coerce_simulation_points(value, default):
    """Validate a synthetic-data point count."""
    if value is None:
        value = default

    try:
        points = operator.index(value)
    except TypeError as exc:
        raise TypeError("simulation_points must be an integer") from exc

    if points < 2:
        raise ValueError("simulation_points must be at least 2")
    return points


def warn_for_large_simulation_points(points, label="simulation data"):
    """Warn when a simulation will process an unusually large data set.

    This is intentionally advisory: callers may still use any point count.
    Hardware capability limits and simulation-size guidance are separate
    concerns, so this helper never truncates or rejects the requested data.
    """
    try:
        points = operator.index(points)
    except TypeError:
        return

    threshold = VirtualInstrument.SIMULATION_POINTS_WARNING_THRESHOLD
    if points > threshold:
        warnings.warn(
            f"{label} contains {points:,} points, exceeding the recommended "
            f"simulation size of {threshold:,}; processing may be slow or "
            "memory-intensive.",
            RuntimeWarning,
            stacklevel=3,
        )


def warn_for_large_simulation_input(value, label="simulation data"):
    """Warn when a sequence-like simulation input exceeds the soft threshold."""
    try:
        points = len(value)
    except (TypeError, AttributeError):
        return
    warn_for_large_simulation_points(points, label=label)


class VirtualInstrument(Instrument):
    """
    Base class for shared virtual-instrument simulation state and policy.

    Manages a single shared ``Sample`` reference across all virtual
    instruments so sources and meters act on the same simulated device.
    """

    sample = None
    _is_virtual_driver = True
    is_profiled_virtual_driver = False

    # These are simulation policy values, not hardware capability limits.
    DEFAULT_SIMULATION_POINTS = 10000
    SIMULATION_POINTS_WARNING_THRESHOLD = 1000000

    def __init__(
        self,
        address="VIRTUAL",
        simulation_points=None,
        check_params=False,
        verbose=False,
        **kwargs,
    ):
        """
        Initialize virtual instrument state without eagerly creating a sample.

        Args:
            address (str): Explicit virtual address.
            simulation_points (int, optional): Default or maximum number of
                samples used by virtual drivers that generate synthetic arrays.
            check_params (bool): Enable automatic parameter validation.
            verbose (bool): Enable verbose virtual-driver output.
            **kwargs: Virtual-driver-specific options.
        """
        self._simulation_points = coerce_simulation_points(
            simulation_points,
            self.DEFAULT_SIMULATION_POINTS,
        )
        self._initialize_common_state(
            check_params=check_params,
            verbose=verbose,
        )
        # SCPI mixins send commands through ``self.instrument``. Dedicated
        # virtual drivers provide their corresponding write/query behavior.
        self.instrument = self

    def __setattr__(self, name, value):
        if name == "sample":
            VirtualInstrument.sample = value
        else:
            super().__setattr__(name, value)

    @property
    def simulation_points(self):
        """Default or maximum sample count for synthetic array generation."""
        return self._simulation_points

    # ------------------------------------------------------------------------
    # Simulated Lifecycle & Synchronization Methods
    # ------------------------------------------------------------------------
    def reset(self):
        """Reset simulated instrument state and clear internal buffers."""
        self._initialize_state()

    def clear(self):
        """Clear simulated instrument errors and communication status."""
        self._last_error = "0"

    def wait(self):
        """Simulated synchronization: returns immediately."""
        return None

    def error(self):
        """Return simulated error code (default '0' for no error)."""
        return getattr(self, "_last_error", "0")

    def self_test(self):
        """Simulated self-test routine (default '0' for pass)."""
        return "0"

    def operation_complete(self):
        """Queries whether the last commanded operation finished (default '1' for complete)."""
        return "1"

