"""Shared discovery helpers for category virtual drivers.

Virtual drivers are discovered from the category folder rather than from a
central registration table.  Keeping this lookup separate from autodetect
allows constructor-time virtual dispatch to use exactly the same rules.
"""

import importlib
import inspect
from copy import deepcopy
from functools import lru_cache
from pathlib import Path


class VirtualDriverDispatchError(RuntimeError):
    """Base exception for constructor-time virtual-driver dispatch errors."""


class VirtualDriverAmbiguityError(VirtualDriverDispatchError):
    """Raised when a category defines more than one virtual driver."""

    def __init__(self, category, candidates):
        self.category = category
        self.candidates = tuple(candidates)
        names = ", ".join(cls.__name__ for cls in self.candidates)
        super().__init__(
            f"Multiple virtual drivers found for category {category!r}: {names}"
        )


class VirtualDriverNotFoundError(VirtualDriverDispatchError):
    """Raised when a model category has no virtual driver implementation."""

    def __init__(self, model_class, category):
        self.model_class = model_class
        self.category = category
        model_name = f"{model_class.__module__}.{model_class.__qualname__}"
        super().__init__(
            f"Cannot create a virtual {model_name}: no virtual driver is "
            f"defined for category {category!r}"
        )


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
    return _find_virtual_driver_class_by_category(category)


@lru_cache(maxsize=None)
def _find_virtual_driver_class_by_category(category):
    """Discover and cache a virtual driver under its canonical category."""
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
        raise VirtualDriverAmbiguityError(category, candidates)

    return candidates[0] if candidates else None


def _category_for_model(model_class):
    """Return the driver-folder name for a concrete model class.

    Model modules use the canonical ``piec.drivers.<category>.<module>``
    layout.  Base classes and adapters in ``piec.drivers`` or
    ``piec.drivers.emulators`` do not identify a model category and therefore
    are left on the normal constructor path.
    """
    parts = model_class.__module__.split(".")
    if len(parts) < 4 or parts[-3] != "drivers":
        return None
    category = parts[-2]
    if category == "emulators":
        return None
    return category


def _model_capability_attributes(model_class):
    """Collect effective public data attributes from a physical model.

    The virtual implementation already inherits the category interface, but
    its defaults must be overridden by the model's effective capability
    values.  Methods and descriptors are intentionally excluded; the virtual
    class supplies behavior while this overlay supplies limits and metadata.
    """
    from .instrument import Instrument

    attributes = {}
    for base in reversed(model_class.__mro__):
        if base is object or base is Instrument:
            continue

        for name, value in base.__dict__.items():
            if name.startswith("_") or name == "AUTODETECT_ID":
                continue
            if callable(value) or isinstance(value, (property, staticmethod, classmethod)):
                continue

            try:
                attributes[name] = deepcopy(value)
            except Exception:
                # Capability values are normally simple lists, tuples, and
                # dictionaries.  Preserve an unusual immutable value if it
                # cannot be copied rather than preventing virtual startup.
                attributes[name] = value

    return attributes


@lru_cache(maxsize=None)
def _profiled_virtual_class(model_class):
    """Build and cache a virtual class profiled with ``model_class`` limits."""
    category = _category_for_model(model_class)
    if category is None:
        return None

    virtual_class = find_virtual_driver_class(category)
    if virtual_class is None:
        raise VirtualDriverNotFoundError(model_class, category)

    generated_name = (
        "Virtualized_"
        f"{model_class.__module__.replace('.', '_')}_{model_class.__name__}"
    )
    namespace = {
        "__module__": __name__,
        "__qualname__": generated_name,
        **_model_capability_attributes(model_class),
        "is_profiled_virtual_driver": True,
    }

    # Virtual drivers use AutoCheckMeta, so create the generated subclass with
    # the virtual class's metaclass rather than plain type().
    generated_class = type(virtual_class)(
        generated_name,
        (virtual_class,),
        namespace,
    )

    # Class objects are callable, so assigning these after AutoCheckMeta has
    # created the class prevents it from treating metadata as driver methods.
    generated_class.emulated_driver_class = model_class
    generated_class.virtual_driver_class = virtual_class

    # Register the generated class under a stable module-level name so normal
    # introspection and pickle lookups can resolve it within this process.
    globals()[generated_name] = generated_class
    return generated_class


def create_profiled_virtual_driver(model_class, *args, **kwargs):
    """Instantiate the category virtual driver profiled for a model.

    ``None`` is returned for base classes and adapters that do not live in a
    concrete category folder; those callers can continue through the normal
    constructor path.
    """
    generated_class = _profiled_virtual_class(model_class)
    if generated_class is None:
        return None
    return generated_class(*args, **kwargs)
