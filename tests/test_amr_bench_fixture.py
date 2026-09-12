"""Four-instrument AMR fixture wiring and isolation."""
import pytest
from tests.fixtures.virtual_setups import amr_bench


def test_amr_field_motion_transport_and_reset_are_independent():
    a, ia = amr_bench(golden=True)
    b, ib = amr_bench(golden=True)
    ia['calibrator'].set_output(.01, mode='voltage')
    ia['calibrator'].output(True)
    ia['arduino'].step(50, 1)
    assert ia['dmm'].get_voltage() == .01
    assert ia['lockin'].get_X_Y() == pytest.approx((100e-6, 10e-6))
    assert ib['dmm'].get_voltage() == 0.
    assert ib['lockin'].get_X_Y() == pytest.approx((102e-6, 10.2e-6))
    b.reset()
    assert ia['arduino'].get_angle() == 90.
    assert ia['dmm'].get_voltage() == .01
    ia['lockin'].excitation_current = 0.
    assert ia['lockin'].get_X_Y() == (0., 0.)
    a.reset()
    assert ia['dmm'].get_voltage() == 0.
    assert ia['arduino'].get_angle() == 0.
