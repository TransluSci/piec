"""
This is the parent class for Digilent WaveForms-SDK devices (Analog
Discovery 2/3, Analog Discovery Studio, ADP3xxx, etc).

Unlike the ``Digilent`` class in ``digilent.py`` (which is actually for
older Measurement Computing / MCC DAQ boards that used to be distributed
under the Digilent name and communicate through the 'mcculw' Universal
Library), this module talks to genuine Digilent Analog Discovery hardware
through the WaveForms Runtime shared library ('dwf').

This driver requires the free WaveForms application from Digilent
(https://digilent.com/shop/software/digilent-waveforms/) to be installed,
which installs the 'dwf' runtime library used here via ctypes. No extra
pip package is required.
"""
import ctypes
import ctypes.util
import sys

from .instrument import Instrument


# --- Load the WaveForms Runtime shared library ---
# We try to load the library the same way Digilent's own Python examples do.
# If it fails, we set the library handle to None and the driver raises a
# contextual error on initialization (matching the 'digilent.py' pattern).
try:
    if sys.platform.startswith("win"):
        _dwf = ctypes.cdll.dwf
    elif sys.platform.startswith("darwin"):
        _dwf = ctypes.cdll.LoadLibrary("/Library/Frameworks/dwf.framework/dwf")
    else:
        _dwf = ctypes.cdll.LoadLibrary("libdwf.so")
    dwf_imported = True
except OSError:
    print("Warning: Digilent WaveForms runtime ('dwf') not found.")
    print("Install WaveForms from https://digilent.com/shop/software/digilent-waveforms/ "
          "to use Analog Discovery devices.")
    _dwf = None
    dwf_imported = False


# --- WaveForms SDK constants (from dwfconstants.h / dwfconstants.py) ---
# Kept local so this driver has no dependency on the SDK's Python samples
# being importable. Values are stable across WaveForms SDK releases.
class _Dwfc:
    # Signal function types (FUNC)
    funcDC = 0
    funcSine = 1
    funcSquare = 2
    funcTriangle = 3
    funcRampUp = 4
    funcRampDown = 5
    funcNoise = 6
    funcCustom = 30
    funcPlay = 31

    # AnalogOut node (channel sub-signal: carrier / FM / AM)
    AnalogOutNodeCarrier = 0

    # Acquisition mode (ACQMODE)
    acqmodeSingle = 0

    # Trigger source (TRIGSRC)
    trigsrcNone = 0
    trigsrcPC = 1
    trigsrcDetectorAnalogIn = 2
    trigsrcAnalogIn = 4
    trigsrcExternal1 = 11

    # Trigger type (TRIGTYPE)
    trigtypeEdge = 0

    # Trigger slope (DwfTriggerSlope)
    DwfTriggerSlopeRise = 0
    DwfTriggerSlopeFall = 1
    DwfTriggerSlopeEither = 2

    # Instrument state (DwfState)
    DwfStateReady = 0
    DwfStateArmed = 1
    DwfStateDone = 2
    DwfStateTriggered = 3
    DwfStateConfig = 4
    DwfStatePrefill = 5
    DwfStateWait = 7


DWFC = _Dwfc


class AnalogDiscovery(Instrument):
    """
    Parent class for Digilent WaveForms-SDK instruments.

    Handles opening/closing the device and the standard PIEC command set
    (idn, reset, clear, error, wait, self_test, operation_complete). Model
    drivers (e.g. Analog Discovery 2 AWG / Oscilloscope) build on top of
    this by issuing AnalogOut / AnalogIn calls against ``self.hdwf``.

    The 'address' is either:
      * A WaveForms device enumeration index (e.g. ``0`` for the first
        connected device, or ``-1`` for "first available").
      * A serial-number string of the form ``"SN:210321A12345"``.
    """

    def __init__(self, address=-1, check_params=False, verbose=False, **kwargs):
        """
        Connects to a Digilent Analog Discovery device via the WaveForms SDK.

        Args:
            address (str or int): WaveForms device index, or "SN:<serial>".
            check_params (bool): Enable automatic parameter validation.
            verbose (bool): If True, prints status messages.
            **kwargs: Reserved for device-specific connection options.
        """
        if not dwf_imported or _dwf is None:
            raise ImportError(
                "Cannot connect to a Digilent Analog Discovery device because "
                "the 'dwf' WaveForms runtime library is not installed. Install "
                "WaveForms from digilent.com."
            )

        self._initialize_common_state(check_params=check_params, verbose=verbose)

        self.dwf = _dwf
        self.hdwf = ctypes.c_int()
        self.device_index = self._resolve_device_index(address)

        if self.verbose:
            print(f"AnalogDiscovery: Opening device index {self.device_index}...")

        self.dwf.FDwfDeviceOpen(ctypes.c_int(self.device_index), ctypes.byref(self.hdwf))
        if self.hdwf.value == 0:
            raise ConnectionError(
                f"Failed to open Analog Discovery device (index {self.device_index}). "
                f"Error: {self._last_error()}"
            )

        if self.verbose:
            print(f"AnalogDiscovery: Connected ({self.idn()})")

    # --- Address resolution helpers ---

    def _resolve_device_index(self, address):
        if address is None:
            return -1
        addr_str = str(address).strip()
        if addr_str == "" or addr_str == "-1":
            return -1
        if addr_str.upper().startswith("SN:"):
            return self._find_index_by_serial(addr_str[3:])
        try:
            return int(addr_str)
        except ValueError:
            raise ValueError(
                f"Invalid address {address!r}. Use a WaveForms device index "
                "(e.g. 0) or a serial number string (e.g. 'SN:210321A12345')."
            )

    def _find_index_by_serial(self, serial):
        count = ctypes.c_int()
        self.dwf.FDwfEnum(ctypes.c_int(0), ctypes.byref(count))
        target = serial.strip().upper()
        buf = ctypes.create_string_buffer(32)
        for i in range(count.value):
            self.dwf.FDwfEnumSN(ctypes.c_int(i), buf)
            sn = buf.value.decode(errors="replace").strip().upper()
            if target in sn:
                return i
        raise ConnectionError(f"No WaveForms device found with serial containing '{serial}'.")

    @staticmethod
    def list_devices():
        """
        Enumerates connected WaveForms-SDK devices without opening them.

        Returns:
            list[dict]: One entry per device with 'index', 'name', 'serial'.
        """
        if not dwf_imported or _dwf is None:
            raise ImportError("The 'dwf' WaveForms runtime library is not installed.")

        count = ctypes.c_int()
        _dwf.FDwfEnum(ctypes.c_int(0), ctypes.byref(count))

        devices = []
        name_buf = ctypes.create_string_buffer(64)
        sn_buf = ctypes.create_string_buffer(32)
        for i in range(count.value):
            _dwf.FDwfEnumDeviceName(ctypes.c_int(i), name_buf)
            _dwf.FDwfEnumSN(ctypes.c_int(i), sn_buf)
            devices.append({
                "index": i,
                "name": name_buf.value.decode(errors="replace").strip(),
                "serial": sn_buf.value.decode(errors="replace").strip(),
            })
        return devices

    def _last_error(self):
        buf = ctypes.create_string_buffer(512)
        self.dwf.FDwfGetLastErrorMsg(buf)
        return buf.value.decode(errors="replace").strip()

    # --- Standard PIEC Commands ---

    def idn(self):
        """
        Returns an identification string from the WaveForms SDK.

        This is the WaveForms-equivalent of the SCPI ``*IDN?`` command.

        Returns:
            str: Identification string in ``Manufacturer,Model,Serial,Version`` format.
        """
        name_buf = ctypes.create_string_buffer(64)
        sn_buf = ctypes.create_string_buffer(32)
        try:
            self.dwf.FDwfEnumDeviceName(ctypes.c_int(self.device_index), name_buf)
            self.dwf.FDwfEnumSN(ctypes.c_int(self.device_index), sn_buf)
            name = name_buf.value.decode(errors="replace").strip() or "Analog Discovery"
            serial = sn_buf.value.decode(errors="replace").strip() or "s/n_unknown"
        except Exception as e:
            if self.verbose:
                print(f"AnalogDiscovery: Could not get IDN. Error: {e}")
            name, serial = "Unknown_Device", "s/n_unknown"
        return f"Digilent,{name},{serial},WaveForms-SDK"

    def reset(self):
        """
        Resets the device to a known idle state (all AnalogOut/AnalogIn
        configuration cleared).

        This is the WaveForms-equivalent of the SCPI ``*RST`` command.
        """
        try:
            self.dwf.FDwfDeviceReset(self.hdwf)
        except Exception as e:
            if self.verbose:
                print(f"AnalogDiscovery: Reset failed: {e}")
        self._initialize_state()
        if self.verbose:
            print("AnalogDiscovery: Reset device.")

    def clear(self):
        """
        Clears the device's error state.

        This is the WaveForms-equivalent of the SCPI ``*CLS`` command.
        The SDK does not maintain a persistent status register beyond the
        last-error message, which this drains.
        """
        self._last_error()  # Draining the message is the closest analogue.
        if self.verbose:
            print("AnalogDiscovery: Clear (drained last-error message).")

    def error(self):
        """
        Queries the device's most recent error message.

        This is the WaveForms-equivalent of the SCPI ``*ESR?`` / ``SYST:ERR?`` query.

        Returns:
            str: The error message.
        """
        return self._last_error()

    def wait(self):
        """
        No-op: WaveForms SDK calls used by this driver are synchronous, so
        there is no pending-operation queue to wait on.

        This is the WaveForms-equivalent of the SCPI ``*WAI`` command.
        """

    def self_test(self):
        """
        Runs a basic connectivity self-test.

        This is the WaveForms-equivalent of the SCPI ``*TST?`` query.

        Returns:
            str: ``'0'`` for pass, ``'1'`` for fail.
        """
        try:
            return "0" if self.hdwf.value != 0 else "1"
        except Exception:
            return "1"

    def operation_complete(self):
        """
        WaveForms SDK calls used by this driver are synchronous, so any
        completed call already implies completion.

        This is the WaveForms-equivalent of the SCPI ``*OPC?`` query.

        Returns:
            str: ``'1'``.
        """
        return "1"

    def initialize(self):
        """
        Convenience method that resets and clears the device to bring it to
        a known good starting state.
        """
        self.reset()
        self.clear()

    def close(self):
        """
        Releases the device from the WaveForms SDK.
        """
        try:
            if getattr(self, "hdwf", None) is not None and self.hdwf.value != 0:
                if self.verbose:
                    print(f"AnalogDiscovery: Closing device index {self.device_index}...")
                self.dwf.FDwfDeviceClose(self.hdwf)
        except Exception as e:
            print(f"AnalogDiscovery: Error closing device. Error: {e}")
