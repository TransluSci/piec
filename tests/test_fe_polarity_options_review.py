"""Signed PUND pulse and pre-reservation option regression tests."""
from unittest.mock import Mock
import numpy as np
import pandas as pd
import pytest
from piec.analysis.pund import process_pund
from piec.measurement import HysteresisLoop, ThreePulsePund, MeasurementRunner

@pytest.mark.parametrize('reset_amp', [-2., 2., 0.])
@pytest.mark.parametrize('p_u_amp', [-1., 1., 0.])
def test_analysis_polarity_matches_programmed_awg(reset_amp, p_u_amp):
    awg = Mock()
    awg.arb_data_range = (2, 601)
    run = ThreePulsePund(awg, Mock(), reset_amp=reset_amp, p_u_amp=p_u_amp,
                         offset=.3, auto_timeshift=False, time_offset=0)
    run.configure_awg()
    programmed = np.asarray(awg.create_arb_waveform.call_args.kwargs['data'])
    amplitude = abs(reset_amp) + abs(p_u_amp)
    t = np.linspace(0, .007, 701)
    result = process_pund(pd.DataFrame({'time':t,'voltage':np.zeros(len(t))}),
        reset_amp=reset_amp, p_u_amp=p_u_amp, reset_width=.001, reset_delay=.001,
        p_u_width=.001, p_u_delay=.001, area=1e-5, offset=.3,
        auto_timeshift=False, time_offset=0)
    # Compare interior plateaus, independent of sample-grid edge rounding.
    for timestamp in (.0005, .0015, .0025, .0035, .0045, .0055):
        awg_index = round(timestamp / .006 * (len(programmed)-1))
        expected = programmed[awg_index] * amplitude + .3
        observed = result.data.loc[np.abs(result.data.time-timestamp).idxmin(), 'applied_voltage']
        assert observed == pytest.approx(expected)

@pytest.mark.parametrize('family', [HysteresisLoop, ThreePulsePund])
@pytest.mark.parametrize('option', ['auto_timeshift','save_plots','show_plots'])
@pytest.mark.parametrize('value', ['False', 0, None])
def test_invalid_options_rejected_before_reservation_or_io(family, option, value):
    awg, osc = Mock(), Mock()
    run = family(awg, osc)
    runner = MeasurementRunner(run)
    with pytest.raises(ValueError, match='must be a boolean'):
        runner.start(save=False, options={option:value})
    assert run.active_token is None
    assert not runner.is_worker_alive
    assert not awg.mock_calls
    assert not osc.mock_calls

@pytest.mark.parametrize('family', [HysteresisLoop, ThreePulsePund])
def test_boolean_false_options_remain_false(family, tmp_path):
    from piec.drivers.awg.virtual_awg import VirtualAwg
    from piec.drivers.oscilloscope.virtual_oscilloscope import VirtualScope
    run = family(VirtualAwg(simulation_points=50), VirtualScope(simulation_points=50),
                 output_dir=tmp_path, auto_timeshift=True, save_plots=True, time_offset=0)
    run.run_experiment(save=True, options={'save_plots':False,'show_plots':False,'auto_timeshift':False})
    assert not list(tmp_path.glob('*.png'))
    assert run.measurement_metadata['auto_timeshift'] is False
