"""Helpers for adapting DAQ capability metadata to other instrument APIs."""

from numbers import Real


def _numeric_values(capability):
    if isinstance(capability, Real) and not isinstance(capability, bool):
        return [float(capability)]
    if isinstance(capability, dict):
        values = []
        for child in capability.values():
            values.extend(_numeric_values(child))
        return values
    if isinstance(capability, (list, tuple)):
        values = []
        for child in capability:
            values.extend(_numeric_values(child))
        return values
    return []


def rate_bounds(daq, capability_name, fallback_max):
    """Return numeric minimum/maximum rates from a DAQ capability."""
    capability = getattr(daq, capability_name, None)
    if isinstance(capability, tuple) and len(capability) == 2:
        lower, upper = capability
        minimum = float(lower) if isinstance(lower, Real) else 1.0
        maximum = float(upper) if isinstance(upper, Real) else float(fallback_max)
        return minimum, maximum

    values = _numeric_values(capability)
    if values:
        return min(values), max(values)

    legacy_values = _numeric_values(getattr(daq, "max_rate", None))
    if legacy_values:
        return 1.0, max(legacy_values)
    return 1.0, float(fallback_max)


def supported_voltage_ranges(daq, capability_name):
    """Normalize a DAQ voltage capability to a list of ``(low, high)`` pairs."""
    capability = getattr(daq, capability_name, None)
    if (
        isinstance(capability, tuple)
        and len(capability) == 2
        and all(isinstance(value, Real) for value in capability)
    ):
        return [(float(capability[0]), float(capability[1]))]

    if isinstance(capability, list):
        ranges = []
        for item in capability:
            if (
                isinstance(item, (list, tuple))
                and len(item) == 2
                and all(isinstance(value, Real) for value in item)
            ):
                ranges.append((float(item[0]), float(item[1])))
        return ranges
    return []


def select_voltage_range(daq, capability_name, required_low, required_high):
    """Choose the narrowest advertised range that contains the required span."""
    ranges = supported_voltage_ranges(daq, capability_name)
    if not ranges:
        return None

    containing = [
        voltage_range
        for voltage_range in ranges
        if voltage_range[0] <= required_low and voltage_range[1] >= required_high
    ]
    def width(voltage_range):
        return voltage_range[1] - voltage_range[0]

    return min(containing, key=width) if containing else max(ranges, key=width)
