import re
import json
import time
import importlib
import inspect
from pathlib import Path
from .utilities import PiecManager
from .instrument import Instrument
from .scpi import Scpi

# Check for Digilent Library

from .digilent import Digilent


# Check for MCC Library
try:
    from mcculw import ul
    from mcculw.enums import InterfaceType
    MCC_AVAILABLE = True
except:
    MCC_AVAILABLE = False
    ul = None

MCC_REGEX = re.compile(r'Device ADDRESS = (\S+)')


class VirtualDriverAmbiguityError(RuntimeError):
    """Raised when a category defines more than one virtual driver."""


# Map shorthand aliases to actual driver directory names
INSTRUMENT_ALIASES = {
    'calibrator': 'dc_calibrator',
    'stepper': 'stepper_motor',
    'scope': 'oscilloscope'
}

# Keywords that should bypass MCC detection (used when address is a generic string)
NON_MCC_KEYWORDS = set(INSTRUMENT_ALIASES.keys()).union(INSTRUMENT_ALIASES.values()).union(
    {'dmm', 'lockin', 'awg', 'pulser', 'rf_source', 'motor', 'arduino'}
)

def _get_registry_path():
    """Returns absolute path to registry_cache.json."""
    return Path(__file__).parent / "registry_cache.json"

def _load_registry_cache():
    try:
        with open(_get_registry_path(), "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def _save_registry_cache(registry):
    try:
        with open(_get_registry_path(), "w") as f:
            json.dump(registry, f, indent=4)
    except Exception as e:
        print(f"Warning: Could not save registry. {e}")

def _import_class_from_path(class_path):
    try:
        module_path, class_name = class_path.rsplit('.', 1)
        module = importlib.import_module(module_path)
        return getattr(module, class_name)
    except Exception as e:
        print(f"Error importing {class_path}: {e}")
        return None


def _find_category_class(module):
    """Return the single Instrument subclass defined by a category module."""
    candidates = []

    for exported_name, cls_obj in inspect.getmembers(module, inspect.isclass):
        if cls_obj is Instrument:
            continue
        if cls_obj.__module__ != module.__name__:
            continue
        if exported_name != cls_obj.__name__:
            continue
        if issubclass(cls_obj, Instrument):
            candidates.append(cls_obj)

    return candidates[0] if len(candidates) == 1 else None


def _resolve_type_string(name):
    """
    Resolve a category folder name or convenience alias to its interface class.

    The category module must define exactly one canonical ``Instrument`` subclass.
    Its Python class name does not need to match the folder or module name.
    """
    name = name.lower()
    
    dir_name = INSTRUMENT_ALIASES.get(name, name)
    
    drivers_path = Path(__file__).parent
    target_dir = drivers_path / dir_name
    
    if target_dir.is_dir():
        # Look for the module piec.drivers.{dir_name}.{dir_name}
        try:
            module_str = f"piec.drivers.{dir_name}.{dir_name}"
            module = importlib.import_module(module_str)

            # Category modules define one Instrument subclass. Its class name
            # does not need to resemble the directory or module name.
            return _find_category_class(module)
        except:
            pass
    return None


def _find_virtual_driver_class(device_type):
    """Discover the single virtual driver defined in a category folder."""
    category = INSTRUMENT_ALIASES.get(device_type.lower(), device_type.lower())
    category_path = Path(__file__).parent / category
    if not category_path.is_dir():
        return None

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


def _dynamic_driver_scan(verbose=False):
    """Scans drivers folder for AUTODETECT_ID."""
    if verbose:
        print("  -> Scanning local drivers for match...")
    drivers_path = Path(__file__).parent
    found_registry = {}
    
    for file_path in drivers_path.glob('**/*.py'):
        if any(x in file_path.parts for x in ['__pycache__', 'z_old', 'old', 'example']):
            continue
            
        try:
            # Reconstruct the module path relative to 'piec'
            parts = list(file_path.parts)
            if 'piec' in parts:
                # Use the last occurrence of 'piec' to avoid matching a parent repo folder
                piec_idx = len(parts) - 1 - parts[::-1].index('piec')
                module_parts = parts[piec_idx:]
                module_str = ".".join(module_parts).replace(".py", "")
                
                module = importlib.import_module(module_str)
                
                for name, obj in inspect.getmembers(module, inspect.isclass):
                    if hasattr(obj, 'AUTODETECT_ID') and obj.__module__ == module.__name__:
                        idn_ids = getattr(obj, 'AUTODETECT_ID')
                        full_class_path = f"{obj.__module__}.{obj.__name__}"
                        
                        if isinstance(idn_ids, (list, tuple)):
                            for i in idn_ids:
                                found_registry[i] = full_class_path
                        else:
                            found_registry[idn_ids] = full_class_path
        except Exception:
            continue

    return found_registry

def _setup_mcc_device(target_identifier=None, board_num=0, verbose=False):
    if not MCC_AVAILABLE or ul is None: return False
    ul.ignore_instacal()
    devices = ul.get_daq_device_inventory(InterfaceType.ANY)
    if not devices: return False

    target_device = devices[0] 
    if target_identifier:
        t_str = str(target_identifier)
        for dev in devices:
            if t_str in dev.product_name or t_str in dev.unique_id or t_str == str(dev.product_id):
                target_device = dev
                break
    
    try:
        ul.create_daq_device(board_num, target_device)
        if verbose:
            print(f"Digilent: Configured {target_device.product_name} as Board {board_num}")
        return target_device.product_name
    except Exception as e:
        if verbose:
            print(f"Digilent Config Error: {e}")
        return None

def _get_real_close(target):
    """Return a real close method without triggering dynamic ``__getattr__``."""
    try:
        inspect.getattr_static(target, 'close')
    except AttributeError:
        return None

    close = getattr(target, 'close')
    return close if callable(close) else None


def _safe_close(instrument):
    """Close a driver or its wrapped resource without allowing cleanup errors."""
    if instrument is None:
        return

    try:
        close = _get_real_close(instrument)
        if close is not None:
            close()
            return

        # Bypass Instrument.__getattr__, which fabricates optional no-op
        resource = object.__getattribute__(instrument, 'instrument')
        if resource is instrument:
            return

        close = _get_real_close(resource)
        if close is not None:
            close()
    except Exception:
        pass

def autodetect(address=None, verbose=False, required_type=None, **kwargs):
    """
    Automatically detect and connect to a physical or virtual instrument.

    ``address`` may be a physical VISA address, a category folder name or alias,
    a category class, or an explicit ``VIRTUAL_<type>`` address. Category names
    resolve to the single ``Instrument`` subclass defined in the same-named
    category module; the class name itself may be different. Virtual requests
    similarly discover the single ``VirtualInstrument`` subclass defined in a
    ``virtual_*.py`` module inside that category folder.

    Physical probe failures return ``None`` rather than silently constructing a
    virtual instrument. Virtual behavior must be requested explicitly.

    Args:
        address: Address, category name, category class, or virtual address.
        verbose (bool): Print probing and matching details when true.
        required_type (type, optional): Restrict matches to this category class.
        **kwargs: Arguments forwarded to the selected driver.

    Returns:
        Instrument or None: The selected driver, or ``None`` when no match is
        found.
    """
    # 0. Check if address is actually a Class or a known Type String
    target_class = None
    if isinstance(address, type):
        target_class = address
    elif isinstance(address, str) and "::" not in address:
        target_class = _resolve_type_string(address)

    if target_class:
        if verbose:
            print(f"Autodetect: Scanning for instrument of type {target_class.__name__}...")
        
        pm = PiecManager()
        resources = pm.list_resources()
        
        for res_address in resources:
            if verbose:
                print(f"  -> Checking {res_address}...")
            try:
                inst = autodetect(address=res_address, verbose=verbose, required_type=target_class, **kwargs)
                if inst and isinstance(inst, target_class):
                    if required_type and not isinstance(inst, required_type):
                        _safe_close(inst)
                    else:
                        if verbose:
                            print(f"  -> MATCH: {res_address} is a {target_class.__name__}!")
                        return inst
                elif inst:
                    _safe_close(inst)
            except Exception as e:
                if verbose:
                    print(f"  -> Failed to check {res_address}: {e}")
                pass
        
        print(f"No instrument of type {target_class.__name__} found.")
        return None

    # 0.5. Virtual Instrument Logic
    if isinstance(address, str) and address.lower().startswith("virtual_"):
        device_type = address.lower()[len("virtual_"):]

        try:
            cls = _find_virtual_driver_class(device_type)
            if cls is None:
                if verbose:
                    print(f"Autodetect: No virtual driver found for {device_type}")
                return None

            if verbose:
                print(f"Autodetect: Loaded virtual instrument {cls.__name__} for address {address}")
            return cls(address=address, verbose=verbose, **kwargs)
        except VirtualDriverAmbiguityError:
            raise
        except Exception as e:
            if verbose:
                print(f"Autodetect: Failed to load virtual instrument for {address}: {e}")
        return None

    # 1. MCC Logic
    is_mcc = (address is None) or (MCC_AVAILABLE and "::" not in str(address))
    if isinstance(address, str) and address.lower() in NON_MCC_KEYWORDS:
        is_mcc = False

    if is_mcc and MCC_AVAILABLE:
        product_name = _setup_mcc_device(address, 0, verbose=verbose)
        if product_name:
            registry = _load_registry_cache()
            match = next((v for k, v in registry.items() if k in product_name), None)
            if not match:
                new_reg = _dynamic_driver_scan(verbose=verbose)
                registry.update(new_reg)
                _save_registry_cache(registry)
                match = next((v for k, v in registry.items() if k in product_name), None)
            if match:
                cls = _import_class_from_path(match)
                if cls and required_type and not issubclass(cls, required_type):
                    return None
                if cls: 
                    return cls(address=0, verbose=verbose, **kwargs)
            if required_type and not issubclass(Digilent, required_type):
                 return None
            return Digilent(address=0, verbose=verbose, **kwargs)
        elif address is None:
            pass
        elif is_mcc and "::" not in str(address):
             return None

    # 2. SCPI Logic
    if address and "::" in str(address):
        if verbose:
            print(f"Autodetect: Probing {address}...")
        temp_inst = None
        idn = ""
        try:
            temp_inst = Scpi(address=address)
            
            # Simple query-based probe with echo handling
            def _probe(query_cmd):
                try:
                    res = temp_inst.instrument.query(query_cmd).strip()
                    if query_cmd in res: # Echo handling
                        res = temp_inst.instrument.read().strip()
                    return res
                except:
                    return ""

            idn = _probe("*IDN?")
            if not idn or idn.isdigit() or idn == "0":
                idn = _probe("ID?")
            
            # Explicit status probe for EDC 522
            if not idn or idn.isdigit() or idn == "0":
                status = _probe("?")
                if status and any(x in status.upper() for x in ["NOTHING WRONG", "NOT PROGRAMMED", "DATA ERROR", "OVERLOAD"]):
                    idn = status

            _safe_close(temp_inst)
            if verbose:
                print(f"  -> IDN: {idn}")
        except Exception as e:
            if verbose:
                print(f"  -> Connection failed: {e}")
            _safe_close(temp_inst)
            return None

        # Registry Lookup
        registry = _load_registry_cache()
        match = next((v for k, v in registry.items() if k in idn), None)
        
        if not match:
            new_reg = _dynamic_driver_scan(verbose=verbose)
            registry.update(new_reg)
            _save_registry_cache(registry)
            match = next((v for k, v in registry.items() if k in idn), None)

        if match:
            cls = _import_class_from_path(match)
            if cls and required_type and not issubclass(cls, required_type):
                return None
            if cls:
                print(f"Autodetect: Loaded {match} for instrument at {address}")
                return cls(address=address, verbose=verbose, **kwargs)

        if required_type and not issubclass(Scpi, required_type):
             return None

        print(f"Autodetect: connected to generic SCPI instrument at {address}")
        return Scpi(address=address, verbose=verbose, **kwargs)
    
    return None
