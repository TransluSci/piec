"""Interactive setups use private plants while external fallback remains available."""
import numpy as np
import pytest
from piec.drivers.awg.virtual_awg import VirtualAwg
from piec.drivers.oscilloscope.virtual_oscilloscope import VirtualScope
from piec.drivers.dc_calibrator.virtual_calibrator import VirtualCalibrator
from piec.drivers.dmm.virtual_dmm import VirtualDMM
from piec.drivers.lockin.virtual_lockin import VirtualLockin
from piec.drivers.stepper_motor.virtual_stepper import VirtualStepper
from piec.drivers.virtual_instrument import VirtualInstrument
from piec.simulation.setups import connect_fe_plant, connect_amr_plant, example_fe_parameters


def test_fe_consumer_pairs_ignore_shared_fallback_and_are_isolated(monkeypatch):
    monkeypatch.setattr(VirtualInstrument, '_shared_fe_sample', object())
    a, sa = VirtualAwg(simulation_points=50), VirtualScope()
    b, sb = VirtualAwg(simulation_points=50), VirtualScope()
    ma, mb = connect_fe_plant(a, sa), connect_fe_plant(b, sb)
    a.output_trigger()
    first = sa.get_data()
    assert mb.output_voltage is None
    b.output_trigger()
    np.testing.assert_array_equal(sb.get_data(), first)
    ma.reset()
    np.testing.assert_array_equal(sb.get_data(), first)


def test_amr_consumer_preserves_front_panel_and_uses_explicit_current(monkeypatch):
    monkeypatch.setattr(VirtualInstrument, '_shared_mag_sample', object())
    cal, dmm, stepper, lockin = VirtualCalibrator(), VirtualDMM(), VirtualStepper(), VirtualLockin()
    lockin.configure_gain_filters(sensitivity='100uv/pa')
    before = lockin.get_state()
    model = connect_amr_plant(cal, dmm, stepper, lockin, seed=42)
    assert lockin.get_state() == before
    cal.set_output(.01)
    cal.output(True)
    stepper.step(50, 1)
    assert model.current_angle == 90.
    assert dmm.get_voltage() == .01
    x, y = lockin.get_X_Y()
    assert x == pytest.approx(100e-6, abs=1e-7)
    assert y == 0.
    lockin.excitation_current = 0.
    assert lockin.get_X_Y() == (0., 0.)
    cal.output(False)
    assert dmm.get_voltage() == 0.


def test_example_parameters_are_independent_and_not_shared():
    first = example_fe_parameters()
    first['ferroelectric']['a0'] = -1
    assert example_fe_parameters()['ferroelectric']['a0'] > 0


def test_consumer_plant_rejects_physical_objects_before_wiring():
    with pytest.raises(TypeError):
        connect_fe_plant(object(), object())
    with pytest.raises(TypeError):
        connect_amr_plant(object(), object(), object(), object())
