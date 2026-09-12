"""Isolation and replay for the explicit FE numerical fixture plant."""
import numpy as np
from tests.fixtures.virtual_setups import fe_bench


def test_fe_acquisition_and_reset_are_isolated_and_replay():
    a, awg_a, scope_a = fe_bench()
    b, awg_b, scope_b = fe_bench()
    awg_a.output_trigger()
    first = scope_a.get_data()
    assert b.models['material'].output_voltage is None
    assert b.timebase.current_time == 0.
    awg_b.output_trigger()
    np.testing.assert_array_equal(scope_b.get_data(), first)
    time_b = b.timebase.current_time
    a.reset()
    assert a.models['material'].output_voltage is None
    np.testing.assert_array_equal(scope_b.get_data(), first)
    assert b.timebase.current_time == time_b
    awg_a.output_trigger()
    np.testing.assert_array_equal(scope_a.get_data(), first)
