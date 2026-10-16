"""Common base for simulated samples."""


class Sample:
    """Common name and model parameters for every simulated sample.

    The supplied dictionary is retained so models can read its parameters.
    Omitting it creates an independent empty dictionary for each sample.
    """

    def __init__(self, parameter_dict=None, name=None):
        self.name = name
        self.parameter_dict = {} if parameter_dict is None else parameter_dict
