"""Common base for measurement experiments."""

import time

import pandas as pd
from piec.simulation.sample import Sample


class Experiment:
    """Manage the save directory, metadata, and history of an experiment.

    Subclasses should initialize their measurement parameters before calling
    ``super().__init__`` so those parameters appear in the initial metadata.
    Subclasses declare all required instrument attribute names in ``_instruments``.
    These instruments are stored as IDs in metadata and initialized by
    ``safe_close``. ``_metadata_attributes`` also includes class attributes in
    the metadata, when present.

    Simulation is optional. ``_default_virtual_sample`` defaults to ``None`` so
    new experiments do not need to reference simulation at all; when virtual
    instruments run with no global sample selected, ``Experiment`` falls back
    to a generic pass-through ``Sample``.
    """

    mtype = None
    _instruments = ()
    _metadata_attributes = ()
    _default_virtual_sample = None

    def __init__(self, save_dir=r'\\scratch'):
        self.save_dir = save_dir
        self.history = []
        self._ensure_virtual_sample()
        self._update_metadata()

    def safe_close(self):
        """Reset every declared instrument by calling its ``initialize`` method."""
        for name in self._instruments:
            getattr(self, name).initialize()

    def _ensure_virtual_sample(self):
        """Assign a default sample when virtual drivers have no global sample."""
        instruments = [getattr(self, name, None) for name in self._instruments]
        if any(getattr(inst, '_is_virtual_driver', False) is True for inst in instruments):
            from piec.drivers.virtual_instrument import VirtualInstrument
            if VirtualInstrument.sample is None:
                if self._default_virtual_sample is not None:
                    default = self._default_virtual_sample
                    VirtualInstrument.sample = default() if callable(default) else default
                else:
                    print(
                        f"WARNING: {type(self).__name__} does not define a specific "
                        "_default_virtual_sample; using generic pass-through Sample."
                    )
                    VirtualInstrument.sample = Sample()

    def _update_metadata(self):
        """Refresh measurement parameters, instrument IDs, and timestamp."""
        params = {
            key: value for key, value in self.__dict__.items()
            if not key.startswith('_')
            and not callable(value)
            and key not in ('data', 'metadata', 'history')
            and key not in self._instruments
        }
        self.metadata = pd.DataFrame([params])
        self.metadata['mtype'] = self.mtype
        for name in self._instruments:
            self.metadata[name] = getattr(self, name).idn()
        for name in self._metadata_attributes:
            if hasattr(self, name):
                self.metadata[name] = getattr(self, name)
        self.metadata['timestamp'] = time.time()
        self.metadata['processed'] = False

    def _update_history(self):
        """Append a copy of the current metadata to this experiment's history."""
        self.history.append(self.metadata.copy())
