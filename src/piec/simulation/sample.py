"""Level-1 foundation for all simulated samples."""


class Sample:
    """Level-1 base class holding the fundamental parts of every simulated sample.

    Mirrors ``piec.drivers.instrument.Instrument``: defines only ``name``,
    ``parameter_dict``, a generic ``state`` dictionary for pass-through stimulus
    tracking between virtual instruments, and a ``__getattr__`` fallback that
    prints a one-time ``[UNSUPPORTED]`` notice and returns ``None``.
    """

    def __init__(self, parameter_dict=None, name="pass_through"):
        self.name = name
        self.parameter_dict = {} if parameter_dict is None else parameter_dict
        self.state = {}
        self._reported_unsupported = set()

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(
                f"'{type(self).__name__}' object has no attribute '{name}'"
            )

        def _skip(*args, **kwargs):
            if name not in self._reported_unsupported:
                self._reported_unsupported.add(name)
                print(
                    f"[UNSUPPORTED] {name} is not supported on "
                    f"{self.__class__.__name__} — skipping."
                )
            return None

        return _skip
