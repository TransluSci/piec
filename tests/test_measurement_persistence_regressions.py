"""Persistence errors must propagate and text metadata must round trip intact."""
import io
from unittest.mock import patch

import pandas as pd
import pytest

from piec.analysis.utilities import metadata_and_data_to_csv
from piec.measurement.persistence import (
    REQUIRED_METADATA_FIELDS, read_measurement_csv, write_measurement_csv,
    write_measurement_handle,
)


def metadata():
    return dict(measurement_schema='iv_sweep', measurement_schema_version=1,
                run_id='00123', outcome='COMPLETED', partial=False,
                save_requested=True, column_units_json='{"voltage":"V"}')


@pytest.mark.parametrize('field', REQUIRED_METADATA_FIELDS)
@pytest.mark.parametrize('as_frame', [False, True])
def test_missing_metadata_fails_before_writing(field, as_frame):
    meta = metadata()
    del meta[field]
    if as_frame:
        meta = pd.DataFrame([meta])
    stream = io.StringIO()
    with pytest.raises(ValueError, match='Missing required'):
        write_measurement_handle(stream, meta, pd.DataFrame({'voltage': [1.]}))
    assert stream.getvalue() == ''


def test_invalid_path_write_does_not_truncate_or_create_directories(tmp_path):
    existing = tmp_path / 'existing.csv'
    existing.write_text('original', encoding='utf-8')
    new = tmp_path / 'new' / 'invalid.csv'
    for path in (existing, new):
        with pytest.raises(ValueError):
            write_measurement_csv(path, {}, pd.DataFrame({'voltage': [1.]}))
    assert existing.read_text(encoding='utf-8') == 'original'
    assert not new.parent.exists()


@pytest.mark.parametrize('utility', [False, True])
def test_disk_sync_failure_propagates(tmp_path, utility):
    data = pd.DataFrame({'voltage': [1.]})
    error = OSError('disk synchronization failed')
    with patch('os.fsync', side_effect=error):
        with pytest.raises(OSError) as caught:
            if utility:
                metadata_and_data_to_csv(pd.DataFrame([metadata()]), data, tmp_path / 'a.csv')
            else:
                write_measurement_csv(tmp_path / 'b.csv', metadata(), data)
    assert caught.value is error


def test_fileno_io_failure_is_not_treated_as_memory_stream():
    class BrokenHandle(io.StringIO):
        def fileno(self):
            raise OSError('broken descriptor')
    with pytest.raises(OSError, match='broken descriptor'):
        write_measurement_handle(BrokenHandle(), metadata(), pd.DataFrame({'voltage': [1.]}))


@pytest.mark.parametrize('as_frame', [False, True])
def test_missing_units_cell_can_be_filled_by_explicit_mapping(as_frame):
    meta = metadata()
    meta['column_units_json'] = None
    stream = io.StringIO()
    write_measurement_handle(stream, pd.DataFrame([meta]) if as_frame else meta,
                             pd.DataFrame({'voltage': [1.]}), column_units={'voltage': 'V'})
    stream.seek(0)
    assert read_measurement_csv(stream)[2] == {'voltage': 'V'}


@pytest.mark.parametrize('note', ['first\nsecond', 'first\r\nsecond', 'a,"b"\n\n山田'])
def test_text_and_multiline_metadata_round_trip(tmp_path, note):
    meta = dict(metadata(), note=note, sample='00007', operator='NA', label='False', empty='')
    data = pd.DataFrame({'voltage': [1., 2.]})
    stream = io.StringIO()
    write_measurement_handle(stream, meta, data)
    stream.seek(0)
    loaded, recovered, units = read_measurement_csv(stream)
    assert loaded == meta
    pd.testing.assert_frame_equal(recovered, data)
    assert units == {'voltage': 'V'}
    path = tmp_path / 'round_trip.csv'
    write_measurement_csv(path, meta, data)
    assert read_measurement_csv(path)[0] == meta


@pytest.mark.parametrize('units', ['{"voltage":12}', '{"voltage":{}}'])
def test_invalid_unit_values_rejected_before_write(units):
    stream = io.StringIO()
    with pytest.raises(TypeError):
        write_measurement_handle(stream, dict(metadata(), column_units_json=units),
                                 pd.DataFrame({'voltage': [1.]}))
    assert stream.getvalue() == ''
