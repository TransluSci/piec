"""Common base for measurement experiments."""

import time

import pandas as pd


class Experiment:
    """Manage the save directory, metadata, and history of an experiment.

    Subclasses should initialize their measurement parameters before calling
    ``super().__init__`` so those parameters appear in the initial metadata.
    Instrument attribute names listed in ``_metadata_instruments`` are stored
    as instrument IDs. ``_metadata_attributes`` also includes class attributes
    in the metadata, when present.
    """

    mtype = None
    _metadata_instruments = ()
    _metadata_attributes = ()

    def __init__(self, save_dir=r'\\scratch'):
        self.save_dir = save_dir
        self.history = []
        self._update_metadata()

    def _update_metadata(self):
        """Refresh measurement parameters, instrument IDs, and timestamp."""
        params = {
            key: value for key, value in self.__dict__.items()
            if not key.startswith('_')
            and not callable(value)
            and key not in ('data', 'metadata', 'history')
            and key not in self._metadata_instruments
        }
        self.metadata = pd.DataFrame([params])
        self.metadata['mtype'] = self.mtype
        for name in self._metadata_instruments:
            self.metadata[name] = getattr(self, name).idn()
        for name in self._metadata_attributes:
            if hasattr(self, name):
                self.metadata[name] = getattr(self, name)
        self.metadata['timestamp'] = time.time()
        self.metadata['processed'] = False

    def _update_history(self):
        """Append a copy of the current metadata to this experiment's history."""
        self.history.append(self.metadata.copy())
