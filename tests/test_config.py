import argparse
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import gnss_config  # noqa: E402
import gnss_logger  # noqa: E402
from gnss_config import ConfigError  # noqa: E402


def write(tmp_path, data, name='cfg.json'):
    p = tmp_path / name
    p.write_text(data if isinstance(data, str) else json.dumps(data))
    return str(p)


def test_full_config_is_normalised(tmp_path):
    cfg = gnss_config.load_config(write(tmp_path, {
        'port': 'COM4', 'mode': 'warm', 'duration': 60,
        'output': 'x.txt', 'start_time': '235959',
        'ref_coords': [44.0886, -87.6576], 'bins': 20}))
    assert cfg == {'port': 'COM4', 'mode': 'warm', 'duration': 60,
                   'output': 'x.txt', 'start_time': '235959',
                   'ref_lat': 44.0886, 'ref_lon': -87.6576, 'bins': 20}


def test_ref_coords_object_form():
    cfg = gnss_config.validate_config({'ref_coords': {'lat': 1, 'lon': 2}})
    assert (cfg['ref_lat'], cfg['ref_lon']) == (1.0, 2.0)


@pytest.mark.parametrize('data', [
    [],
    {'prot': 'COM4'},
    {'mode': 'lukewarm'},
    {'duration': 0},
    {'duration': '900'},
    {'duration': True},
    {'bins': -1},
    {'start_time': '1234'},
    {'start_time': '246000'},
    {'start_time': 123456},
    {'ref_coords': [91, 0]},
    {'ref_coords': [0, 181]},
    {'ref_coords': [1]},
    {'ref_coords': {'lat': 1}},
    {'ref_coords': ['1', '2']},
    {'port': ''},
])
def test_bad_values_rejected(data):
    with pytest.raises(ConfigError):
        gnss_config.validate_config(data)


def test_bad_json_and_missing_file(tmp_path):
    with pytest.raises(ConfigError, match='invalid JSON'):
        gnss_config.load_config(write(tmp_path, '{port: COM4'))
    with pytest.raises(ConfigError, match='cannot read'):
        gnss_config.load_config(str(tmp_path / 'nope.json'))


def test_merge_precedence():
    out = gnss_config.merge({'a': None, 'b': 'cli'}, {'a': 'cfg', 'b': 'cfg'},
                            {'a': 'def', 'b': 'def', 'c': 'def'})
    assert out == {'a': 'cfg', 'b': 'cli', 'c': 'def'}


def logger_parser():
    return gnss_logger.build_parser()


def test_logger_defaults_unchanged_without_config():
    a = gnss_logger.parse_args(logger_parser(), ['COM3'])
    assert (a.port, a.mode, a.duration, a.output) == ('COM3', 'cold', 900, 'nmea_capture.txt')


def test_logger_uses_config_values(tmp_path):
    cfg = write(tmp_path, {'port': 'COM9', 'mode': 'hot', 'duration': 30,
                           'output': 'o.txt', 'ref_coords': [1, 2]})
    a = gnss_logger.parse_args(logger_parser(), ['--config', cfg])
    assert (a.port, a.mode, a.duration, a.output) == ('COM9', 'hot', 30, 'o.txt')


def test_logger_cli_overrides_config(tmp_path):
    cfg = write(tmp_path, {'port': 'COM9', 'mode': 'hot', 'duration': 30})
    a = gnss_logger.parse_args(logger_parser(),
                               ['COM1', '--mode', 'warm', '--config', cfg])
    assert (a.port, a.mode, a.duration) == ('COM1', 'warm', 30)


def test_logger_missing_port_errors(capsys):
    with pytest.raises(SystemExit) as e:
        gnss_logger.parse_args(logger_parser(), [])
    assert e.value.code == 2
    assert 'port' in capsys.readouterr().err


def test_logger_bad_config_errors(tmp_path, capsys):
    cfg = write(tmp_path, {'mode': 'lukewarm'})
    with pytest.raises(SystemExit) as e:
        gnss_logger.parse_args(logger_parser(), ['COM1', '--config', cfg])
    assert e.value.code == 2
    assert 'mode' in capsys.readouterr().err
