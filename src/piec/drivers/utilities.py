try:
    from pyvisa import ResourceManager
    from mcculw import ul
    from mcculw.enums import InterfaceType
except (FileNotFoundError, ImportError):
    print('Warning: if using digilent please check the readme file and install the required dependencies (UL) or try running pip install mcculw')
    ul = None
    InterfaceType = None
except Exception as e:
    print(f"Warning: Failed to import mcculw. MCC devices will not be available. Error: {e}")
    ul = None
    InterfaceType = None

import pyvisa # Keep this for _probe_scpi
import inspect
import importlib
from pathlib import Path
import json
import os

class PiecManager():
    """
    Basically Resource Manager that melds MCC digilent stuff into it.
    Allows for getting all resources from both VISA and MCC.
    """
    def __init__(self):
        """Initializes the underlying pyvisa ResourceManager."""
        self.rm = ResourceManager()

    def list_resources(self):
        """
        Runs list_resources() for both VISA and MCC and combines them.
        """
        visa_resources = self.rm.list_resources()
        mcc_resources = []
        try:
            mcc_resources = list_mcc_resources()
        except Exception as e:
            print(f'Warning: Could not list MCCULW resources. Error: {e}')
        
        return tuple(list(visa_resources) + mcc_resources)

    def list_open_resources(self):
        """Lists only the currently opened VISA resources."""
        return self.rm.list_opened_resources()

    def open_resource(self, address, baud_rate=None, **kwargs):
        """
        Opens a resource by address.

        If the address is for an MCCULW device, it uses the ul module.
        For standard VISA resources, it acts as a wrapper for pyvisa's open_resource,
        allowing for an explicit baud_rate argument.

        Args:
            address (str): The resource address string.
            baud_rate (int, optional): The baud rate for serial instruments. Defaults to None.
            **kwargs: Other keyword arguments to pass to pyvisa.open_resource.
        """
        # Check if the device is an MCC/Digilent device
        if 'MCC' in address or 'Digilent' in address:
            if ul is None:
                raise ImportError("Cannot open MCC device: 'mcculw' library is not installed.")
            # These devices are not opened via VISA, so kwargs are not used.
            return ul.open_device(address)
        else:
            # This is a standard VISA resource.
            # If the user provided a baud_rate, add it to the kwargs dictionary.
            # This gives the explicit argument priority.
            if baud_rate is not None:
                kwargs['baud_rate'] = baud_rate
            
            # Call the original pyvisa function with the (potentially modified) kwargs.
            return self.rm.open_resource(address, **kwargs)

"""
Helper Functions
"""
def list_mcc_resources():
    """Lists all connected MCC DAQ devices."""
    if ul is None:
        return []

    try:
        ul.ignore_instacal()
        devices = ul.get_daq_device_inventory(InterfaceType.ANY)
        formatted_list = []
        if devices:
            for device in devices:
                # Create a descriptive string for each device
                device_string = f"{device.product_name} ({device.unique_id}) - Device ADDRESS = {device.product_id}"
                formatted_list.append(device_string)
        return formatted_list
    except Exception as e:
        # Catch any other UL errors
        return []


def _probe_scpi(address, verbose=False):
    """
    Opens a temporary VISA connection and probes for an IDN string.

    Tries *IDN?, then ID?, then ? (EDC-522 fallback).
    Returns the IDN string or an empty string on failure.
    Closes the connection before returning.

    Args:
        address (str): The VISA resource address string.
        verbose (bool): If True, prints debug information.

    Returns:
        str: The IDN response, or '' if probing failed.
    """
    import pyvisa
    rm = None
    inst = None
    try:
        rm = pyvisa.ResourceManager()
        inst = rm.open_resource(address)

        def _query(cmd):
            try:
                res = inst.query(cmd).strip()
                # Echo handling: some instruments echo the command back
                if cmd in res:
                    res = inst.read().strip()
                return res
            except Exception:
                return ""

        idn = _query("*IDN?")
        if not idn or idn.isdigit() or idn == "0":
            idn = _query("ID?")

        # EDC-522 fallback: status probe
        if not idn or idn.isdigit() or idn == "0":
            status = _query("?")
            if status and any(x in status.upper() for x in ["NOTHING WRONG", "NOT PROGRAMMED", "DATA ERROR", "OVERLOAD"]):
                idn = status

        return idn
    except Exception as e:
        if verbose:
            print(f"  -> Could not probe {address}: {e}")
        return ""
    finally:
        try:
            if inst is not None:
                inst.close()
            if rm is not None:
                rm.close()
        except Exception:
            pass


def list_instruments(verbose=False):
    """
    Discovers all connected instruments and returns their identifying information.

    Loops through all resources from PiecManager.list_resources(), probes each
    VISA instrument with *IDN? to identify it, and attempts to match it against
    known drivers using the autodetect registry cache.

    Args:
        verbose (bool): If True, prints progress messages during discovery.

    Returns:
        list[dict]: Each dict has keys:
            - 'address' (str): The resource address.
            - 'idn' (str): The identification string (or product name for MCC).
            - 'type' (str): 'visa' or 'mcc'.
            - 'driver' (str): The name of the matching driver class, or 'Unknown'.
            - 'category' (str): The instrument category (e.g., 'awg', 'dmm').
    """
    # Import locally to avoid circular import
    from .autodetect import _load_registry_cache, _dynamic_driver_scan, _import_class_from_path, _save_registry_cache

    pm = PiecManager()
    resources = pm.list_resources()
    results = []

    if verbose:
        print(f"Found {len(resources)} resource(s). Probing...\n")

    registry = _load_registry_cache()
    registry_updated = False

    for address in resources:
        addr_str = str(address)
        idn = "Unknown"
        res_type = ""

        if "MCC" in addr_str or "Digilent" in addr_str:
            # MCC/Digilent device
            idn = addr_str
            res_type = "mcc"
            driver_class = "Digilent"
            category = "digilent"
            if verbose:
                print(f"  [MCC]  {addr_str}")
        else:
            # VISA instrument
            if verbose:
                print(f"  Probing {addr_str}...", end=" ")
            probed_idn = _probe_scpi(addr_str, verbose=verbose)
            if probed_idn:
                idn = probed_idn
            res_type = "visa"
            driver_class = "Scpi"
            category = "scpi"
            if verbose:
                print(f"-> {idn}")

        if idn != "Unknown":
            match = next((v for k, v in registry.items() if k in idn), None)
            
            # If not found, run dynamic scan once and retry
            if not match and not registry_updated:
                new_reg = _dynamic_driver_scan(verbose=verbose)
                if new_reg:
                    registry.update(new_reg)
                    _save_registry_cache(registry)
                registry_updated = True
                match = next((v for k, v in registry.items() if k in idn), None)
            
            if match:
                cls = _import_class_from_path(match)
                if cls:
                    driver_class = cls.__name__
                parts = match.split('.')
                if len(parts) >= 3:
                    category = parts[2]

        # Explicit lookup by address logic since autodetect does it and MCC does but let's just stick to the idn for resolving
        results.append({
            "address": addr_str,
            "idn": idn,
            "type": res_type,
            "driver": driver_class,
            "category": category
        })

    # Print summary table
    if results:
        print(f"\n{'Address':<35} {'Driver':<20} {'Category':<15} {'IDN'}")
        print("-" * 110)
        for r in results:
            print(f"{r['address']:<35} {r['driver']:<20} {r['category']:<15} {r['idn']}")
    else:
        print("No instruments found.")

    return results
