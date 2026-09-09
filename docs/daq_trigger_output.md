# DAQ trigger pulse output

`Daq.send_trigger_pulse(channel, pulse_width, active_high=True, *, resource='digital',
require_hardware_timing=False, cancel_event=None)` emits one pulse and blocks until
completion or cancellation. Widths are in seconds. `get_trigger_pulse_capabilities()`
reports available resources, their channel numbers, timing, and accepted width bounds.
`validate_trigger_pulse()` checks a request without changing outputs.

The general implementation uses `set_DIO_mode` and `write_DO` to request idle,
active, then idle. USB231 inherits this software fallback. USB and operating-system
latency affect both launch time and width; a requested width is not a timing guarantee.
Drivers without implemented digital commands reject it. Driver authors should
override with hardware timing where supported, or inherit/override the software
implementation when unsupported, as documented in `daq.py`.

USB1208HS also exposes resource `timer`, channel 0 (the TMR terminal). It requests
one hardware pulse with Universal Library `pulse_out_start`, 50% duty cycle, and
the requested polarity. It waits the actual returned period and then calls
`pulse_out_stop`. Hardware controls width; the launch still originates in software.
Accepted widths are 25 ns through 50 s. Returned metadata includes the quantized
programmed width, not a measured width or physical timestamp.

## One generic emulator

`DaqAsAwg` uses only the general DAQ methods; it contains no model-specific dispatch.
Configure the physical resource explicitly before firing:

```python
awg = DaqAsAwg(daq)
# USB1208HS TMR terminal:
awg.configure_trigger_output(0, 0.001, resource='timer', require_hardware_timing=True)
result = awg.output_trigger()

# USB231 DIO0 (also available as an explicit software option on USB1208HS):
awg.configure_trigger_output(0, 0.001, resource='digital')
result = awg.output_trigger()
```

The configuration argument `pulse_channel` uses DAQ resource numbering, independent
of the emulator's analog channel numbering. Timer 0 and digital 0 are different
terminals: there is no automatic fallback that changes pins, including after errors.
`require_hardware_timing=True` rejects software and simulated timing before I/O.
VirtualDaq records completed digital pulses in `state['trigger_pulses']`, marks them
`simulated`, and restores the simulated idle level.

An external pulse does not arm, launch, or synchronize the emulator's analog waveform.
Triggered analog playback remains unsupported. Reserve the selected terminal and
match its electrical levels to the receiving input. A direction change may itself
produce device-specific edges. Concurrent pulse calls are serialized; other users
of the terminal must coordinate separately. Cancellation attempts cleanup and raises
`InterruptedError`. I/O failures propagate, with idle restoration/timer stop attempted
in `finally`; failed hardware is not guaranteed to obey cleanup commands.

## Manufacturer references and verification

- [USB1208HS Universal Library support](https://files.digilent.com/manuals/Mcculw_WebHelp/Users_Guide/Analog_Input_Boards/USB-1208HS_Series.htm): timer 0, frequency limits, polarity and finite pulse count.
- [pulse_out_start](https://files.digilent.com/manuals/Mcculw_WebHelp/Function_Reference/Ctr-python/pulse_out_start.htm): actual frequency, duty and delay return values.
- [pulse_out_stop](https://files.digilent.com/manuals/Mcculw_WebHelp/Function_Reference/Ctr-python/pulse_out_stop.htm): timer shutdown.
- [USB231 manual](https://files.digilent.com/manuals/USB-231.pdf): software-paced digital I/O.

`tests/test_daq_trigger_pulses.py` checks sequencing, validation, cancellation,
error cleanup, timer command arguments, simulation and generic emulator dispatch.
Physical pulse widths, electrical behavior and synchronization have not been bench tested.
