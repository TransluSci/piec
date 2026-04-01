"""
test_imports.py

Verifies that the piec package and its main sub-modules can be imported
correctly after installation.

Run with pytest tests/test_imports.py
"""


def test_import_piec():
    import piec 


def test_version_string():
    """The package must have a non-empty version string."""
    import piec
    assert hasattr(piec, "__version__"), "piec.__version__ is missing"
    assert isinstance(piec.__version__, str)
    assert len(piec.__version__) > 0


def test_import_drivers():
    import piec.drivers 


def test_import_analysis():
    import piec.analysis


def test_import_simulation():
    import piec.simulation 


def test_import_virtual_awg():
    from piec.drivers.awg.virtual_awg import VirtualAwg 


def test_import_virtual_scope():
    from piec.drivers.oscilloscope.virtual_oscilloscope import VirtualScope


def test_import_analysis_utilities():
    from piec.analysis.utilities import (
        interpolate_sparse_to_dense,
        metadata_and_data_to_csv,
        standard_csv_to_metadata_and_data,
        create_measurement_filename,
    )


def test_import_simulation_classes():
    from piec.simulation.fe_material import Ferroelectric, Resistor, Dielectric
