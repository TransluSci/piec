"""Owned virtual instruments and explicit signal routing, independent of measurements."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import inspect
import math
from types import MappingProxyType

import numpy as np

from .contracts import DeterministicTimebase, ElectricalLoadContract, SimulationRole


class BenchResetError(RuntimeError):
    """Reset attempted every owned component, but one or more operations failed."""

    def __init__(self, errors):
        self.errors = tuple(errors)
        super().__init__('VirtualBench reset failed: ' + ', '.join(name for name, _ in errors))


def _driver_types():
    # Lazy imports avoid the drivers -> simulation.contracts -> simulation cycle.
    from piec.drivers.awg.virtual_awg import VirtualAwg
    from piec.drivers.dc_calibrator.virtual_calibrator import VirtualCalibrator
    from piec.drivers.dmm.virtual_dmm import VirtualDMM
    from piec.drivers.lockin.virtual_lockin import VirtualLockin
    from piec.drivers.oscilloscope.virtual_oscilloscope import VirtualScope
    from piec.drivers.sourcemeter.virtual_sourcemeter import VirtualSourcemeter
    from piec.drivers.stepper_motor.virtual_stepper import VirtualStepper
    return (VirtualAwg, VirtualCalibrator, VirtualDMM, VirtualLockin,
            VirtualScope, VirtualSourcemeter, VirtualStepper)


class VirtualBench:
    """Create, route and reset one independent virtual setup.

    Names identify owned objects and independent seeded random streams. Models
    must implement SimulationRole; drivers are the seven checkpoint-28 virtual
    classes. Existing instances are not accepted. No shared sample is installed.

    Use advance(seconds) before each time-dependent integration step. Neither
    instrument commands nor reads advance time implicitly. Calls within one bench
    must be serialized by its owner; different benches can run concurrently.
    Reset restores driver factory settings, initial model state, time and RNGs,
    preserving connections. It does not restore later instrument configuration.
    """

    def __init__(self, seed=None, start_time=0.0):
        self._clock = DeterministicTimebase(start_time)
        self._start_time = float(start_time)
        self._entropy = np.random.SeedSequence(seed).entropy
        self._models = {}
        self._instruments = {}
        self._routes = {}
        self._ports = set()
        self._streams = {}

    @property
    def timebase(self):
        return self._clock

    @property
    def models(self):
        return MappingProxyType(self._models)

    @property
    def instruments(self):
        return MappingProxyType(self._instruments)

    @property
    def routes(self):
        """Read-only connection inventory (names and endpoints)."""
        return MappingProxyType({name: route.endpoints for name, route in self._routes.items()})

    def _seed(self, name):
        digest = hashlib.sha256(f'{self._entropy}:{name}'.encode('utf-8')).digest()
        return int.from_bytes(digest[:8], 'big')

    def rng(self, name):
        """Return a named independent stream, replayed in place by reset."""
        if not isinstance(name, str) or not name:
            raise ValueError('stream name must be a nonempty string')
        if name not in self._streams:
            rng = np.random.default_rng(self._seed('stream:' + name))
            self._streams[name] = (rng, deepcopy(rng.bit_generator.state))
        return self._streams[name][0]

    def _new_name(self, name):
        if not isinstance(name, str) or not name:
            raise ValueError('name must be a nonempty string')
        if name in self._models or name in self._instruments or name in self._routes:
            raise ValueError(f'duplicate bench name: {name}')

    def add_model(self, name, model_class, **parameters):
        self._new_name(name)
        if not isinstance(model_class, type) or not issubclass(model_class, SimulationRole):
            raise TypeError('model_class must be a SimulationRole class, not an instance')
        if 'seed' in parameters or 'start_time' in parameters:
            raise ValueError('the bench owns model seed and start_time')
        model = model_class(seed=self._seed('model:' + name), start_time=self._start_time,
                            **deepcopy(parameters))
        model.timebase.set_time(self._clock.current_time)
        self._models[name] = model
        return model

    def add_instrument(self, name, driver_class, **parameters):
        self._new_name(name)
        if driver_class not in _driver_types():
            raise TypeError('driver_class must be one of the seven supported virtual driver classes')
        if 'seed' in parameters:
            raise ValueError('the bench owns instrument seeds')
        if 'seed' in inspect.signature(driver_class.__init__).parameters:
            parameters['seed'] = self._seed('instrument:' + name)
        instrument = driver_class(**parameters)
        # Some families only override the fallback they consume. Never assign
        # an inherited base descriptor, which would mutate the shared sample.
        from piec.drivers.virtual_instrument import VirtualInstrument
        for attribute in ('sample', 'mag_sample'):
            descriptor = inspect.getattr_static(driver_class, attribute)
            if descriptor is not inspect.getattr_static(VirtualInstrument, attribute):
                setattr(instrument, attribute, None)
        self._instruments[name] = instrument
        return instrument

    def advance(self, seconds):
        target = self._clock.current_time + seconds
        if not math.isfinite(seconds) or seconds < 0 or not math.isfinite(target):
            raise ValueError('seconds must be finite and nonnegative')
        if any(model.timebase.current_time > target for model in self._models.values()):
            raise ValueError('owned model clock was advanced outside the bench')
        self._clock.set_time(target)
        for model in self._models.values():
            model.timebase.set_time(target)
        return target

    def _instrument(self, name, kind):
        instrument = self._instruments[name]
        if type(instrument).__name__ != kind:
            raise TypeError(f'{name} must be {kind}')
        return instrument

    def _check_ports(self, name, ports):
        self._new_name(name)
        if any(port in self._ports for port in ports):
            raise ValueError('instrument port already connected')

    def connect_load(self, name, source, load):
        """Connect a sourcemeter to an owned two-terminal electrical load."""
        ports = [(source, 'load'), (load, 'electrical')]
        self._check_ports(name, ports)
        sm = self._instrument(source, 'VirtualSourcemeter')
        model = self._models[load]
        if not isinstance(model, ElectricalLoadContract):
            raise TypeError('load must implement ElectricalLoadContract')
        if sm.state['output_on'] is not False:
            raise ValueError('connect routes only with source output confirmed off')
        route = _LoadRoute(self, model, (source, load))
        sm.load_hook = route
        self._routes[name] = route
        self._ports.update(ports)

    def connect_moke(self, name, source, load, material, detector, calibration,
                     optical_gain=0.02, optical_offset=0.5, noise_std=0.0):
        """Route compliant terminal output through a calibration to optical volts.

        Calibration is the simulated plant calibration, copied on connection.
        It must cover zero output and match the material's field unit. Supply the
        measurement's calibration separately so conversion errors cannot cancel.
        field_reader(name) optionally supplies a noiseless simulated gaussmeter.
        """
        from piec.analysis.field_calibration import FieldCalibration
        from .contracts import FieldResponsiveMaterialContract
        ports = [(source, 'load'), (load, 'electrical'), (detector, 'voltage'), (material, 'field')]
        self._check_ports(name, ports)
        sm = self._instrument(source, 'VirtualSourcemeter')
        dmm = self._instrument(detector, 'VirtualDMM')
        electrical, magnetic = self._models[load], self._models[material]
        if not isinstance(electrical, ElectricalLoadContract):
            raise TypeError('load must implement ElectricalLoadContract')
        if not isinstance(magnetic, FieldResponsiveMaterialContract):
            raise TypeError('material must implement FieldResponsiveMaterialContract')
        if not isinstance(calibration, FieldCalibration):
            raise TypeError('calibration must be FieldCalibration')
        if calibration.field_unit != magnetic.declared_units['field']:
            raise ValueError('calibration and material field units must match')
        calibration = FieldCalibration(**calibration.to_dict())
        calibration.field_at_output(0.0)
        if not all(math.isfinite(x) for x in (optical_gain, optical_offset, noise_std)) or noise_std < 0:
            raise ValueError('optical parameters must be finite, with nonnegative noise_std')
        if sm.state['output_on'] is not False:
            raise ValueError('connect routes only with source output confirmed off')
        route = _MokeRoute(self, electrical, magnetic, calibration, sm,
                           (source, load, material, detector), optical_gain,
                           optical_offset, noise_std, self.rng(name + ':detector'))
        route.reset()
        sm.load_hook = route
        dmm.voltage_reader = route.read_voltage
        self._routes[name] = route
        self._ports.update(ports)

    def field_reader(self, route):
        """Return the MOKE route's optional scalar field reader (material units)."""
        connection = self._routes[route]
        if not isinstance(connection, _MokeRoute):
            raise TypeError('field_reader requires a MOKE route')
        return connection.read_field

    def connect_waveform(self, name, awg, scope, source_channel=1, scope_channel=1):
        """Route a triggered synthesized AWG waveform to one scope channel.

        This is sampled transport, not a simulation of hardware trigger latency
        or a continuous circuit. Reads before a trigger and unconnected channels
        raise. Output-off triggers store zero volts on the same time grid.
        """
        ports = [(awg, 'waveform'), (scope, 'waveform')]
        self._check_ports(name, ports)
        source = self._instrument(awg, 'VirtualAwg')
        reader = self._instrument(scope, 'VirtualScope')
        if (isinstance(source_channel, bool) or isinstance(scope_channel, bool)
                or source_channel not in source.channel or scope_channel not in reader.channel):
            raise ValueError('invalid waveform channel')
        route = _WaveformRoute((awg, scope), source_channel, scope_channel)
        source.waveform_hook = route.capture
        reader.waveform_hook = route.read
        self._routes[name] = route
        self._ports.update(ports)

    def reset(self):
        """Attempt all resets; preserve failures rather than declaring success."""
        errors = []
        for name, instrument in self._instruments.items():
            try:
                instrument.reset()
            except Exception as error:
                errors.append((name, error))
        for name, model in self._models.items():
            try:
                model.reset(seed=self._seed('model:' + name), start_time=self._start_time)
            except Exception as error:
                errors.append((name, error))
        self._clock.reset(self._start_time)
        for rng, state in self._streams.values():
            rng.bit_generator.state = deepcopy(state)
        for name, route in self._routes.items():
            try:
                route.reset()
            except Exception as error:
                errors.append((name, error))
        if errors:
            raise BenchResetError(errors)


class _LoadRoute:
    def __init__(self, bench, load, endpoints):
        self.bench, self.load, self.endpoints = bench, load, endpoints

    @property
    def timebase(self):
        return self.bench.timebase

    def evaluate(self, mode, stimulus, compliance, time=None):
        return self.load.evaluate(mode, stimulus, compliance, time=self.timebase.current_time)

    def reset(self):
        pass


class _MokeRoute(_LoadRoute):
    def __init__(self, bench, load, material, calibration, source, endpoints,
                 gain, offset, noise, rng):
        super().__init__(bench, load, endpoints)
        self.material, self.calibration, self.source = material, calibration, source
        self.gain, self.offset, self.noise, self.rng = gain, offset, noise, rng

    def _field(self, output):
        field = self.calibration.field_at_output(output)
        self.material.apply_field(field, time=self.timebase.current_time)

    def evaluate(self, mode, stimulus, compliance, time=None):
        from .contracts import LoadMode
        expected = LoadMode.VOLTAGE_SOURCE if self.calibration.output_unit == 'V' else LoadMode.CURRENT_SOURCE
        if mode != expected:
            raise ValueError('source mode does not match plant calibration output unit')
        response = super().evaluate(mode, stimulus, compliance, time)
        self._field(response.voltage if self.calibration.output_unit == 'V' else response.current)
        return response

    def __call__(self, output_on):
        if not output_on:
            self._field(0.0)

    def read_voltage(self):
        self.source.get_voltage()  # Refresh field; unconfirmed source state raises.
        value = self.offset + self.gain * self.material.magnetization
        return float(value + (self.rng.normal(0., self.noise) if self.noise else 0.))

    def read_field(self):
        self.source.get_voltage()
        return float(self.material.current_field)

    def reset(self):
        self._field(0.0)


class _WaveformRoute:
    def __init__(self, endpoints, source_channel, scope_channel):
        self.endpoints = endpoints
        self.source_channel, self.scope_channel = source_channel, scope_channel
        self.reset()

    def capture(self, v, t, channel, output_on):
        if channel != self.source_channel:
            raise ValueError('AWG channel is not connected to this route')
        self._sample = (np.array(v, copy=True) if output_on else np.zeros_like(v), np.array(t, copy=True))

    def read(self, channel):
        if channel != self.scope_channel:
            raise ValueError('scope channel is not connected to this route')
        if self._sample is None:
            raise RuntimeError('no waveform has been triggered')
        v, t = self._sample
        return v.copy(), t.copy()

    def reset(self):
        self._sample = None
