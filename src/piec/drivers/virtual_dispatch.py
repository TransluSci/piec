"""Shared discovery helpers for category virtual drivers.

Virtual drivers are discovered from the category folder rather than from a
central registration table.  Keeping this lookup separate from autodetect
allows constructor-time virtual dispatch to use exactly the same rules.
"""

import importlib
import inspect
from pathlib import Path


class VirtualDriverAmbiguityError(RuntimeError):
    """Raised when a category defines more than one virtual driver."""


# Map shorthand aliases to actual driver directory names.  This is shared by
# autodetect and any future constructor-time virtual dispatch.
INSTRUMENT_ALIASES = {
    "calibrator": "dc_calibrator",
    "stepper": "stepper_motor",
    "scope": "oscilloscope",
}


def find_virtual_driver_class(device_type):
    """Discover the single virtual driver defined for a category.

    The category is resolved from ``virtual_<type>`` address syntax and the
    folder is scanned for ``virtual_*.py`` modules.  A module contributes a
    candidate only when it defines the virtual class locally, preventing
    imported base classes from being counted.  ``None`` means that the
    category does not exist or does not provide a virtual driver.

    Args:
        device_type (str): Category name or supported category alias, without
            the ``virtual_`` prefix.

    Raises:
        VirtualDriverAmbiguityError: If more than one local virtual driver is
            found for the category.
    """
    category = INSTRUMENT_ALIASES.get(device_type.lower(), device_type.lower())
    category_path = Path(__file__).parent / category
    if not category_path.is_dir():
        return None

    # Import lazily so importing this lightweight discovery module does not
    # eagerly initialize simulation materials or every virtual driver.
    from .virtual_instrument import VirtualInstrument

    candidates = []
    for file_path in sorted(category_path.glob("virtual_*.py")):
        module_str = f"piec.drivers.{category}.{file_path.stem}"
        module = importlib.import_module(module_str)

        for exported_name, cls_obj in inspect.getmembers(module, inspect.isclass):
            if cls_obj is VirtualInstrument:
                continue
            if cls_obj.__module__ != module.__name__:
                continue
            if exported_name != cls_obj.__name__:
                continue
            if issubclass(cls_obj, VirtualInstrument):
                candidates.append(cls_obj)

    if len(candidates) > 1:
        names = ", ".join(cls.__name__ for cls in candidates)
        raise VirtualDriverAmbiguityError(
            f"Multiple virtual drivers found for category {category!r}: {names}"
        )

    return candidates[0] if candidates else None

