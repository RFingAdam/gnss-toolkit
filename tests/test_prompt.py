import io
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import gnss_logger  # noqa: E402


class FakeStdin(io.StringIO):
    def __init__(self, tty):
        super().__init__()
        self._tty = tty

    def isatty(self):
        return self._tty


def answers(*vals):
    it = iter(vals)

    def fn(prompt):
        v = next(it)
        if isinstance(v, BaseException):
            raise v
        return v
    return fn


def parse(argv, **kw):
    return gnss_logger.parse_args(gnss_logger.build_parser(), argv, **kw)


def test_port_on_cli_never_prompts():
    a = parse(['COM3'], stdin=FakeStdin(True),
              input_fn=answers(AssertionError('prompted')))
    assert (a.port, a.mode, a.duration, a.output) == ('COM3', 'cold', 900, 'nmea_capture.txt')


def test_missing_port_non_tty_errors_like_before(capsys):
    with pytest.raises(SystemExit) as e:
        parse([], stdin=FakeStdin(False),
              input_fn=answers(AssertionError('prompted')))
    assert e.value.code == 2
    assert 'required: port' in capsys.readouterr().err


def test_missing_port_tty_prompts(monkeypatch):
    monkeypatch.setattr(gnss_logger, 'list_serial_ports', lambda: [])
    a = parse(['--mode', 'hot'], stdin=FakeStdin(True),
              input_fn=answers('  /dev/ttyUSB0 '))
    assert a.port == '/dev/ttyUSB0' and a.mode == 'hot'


def test_tty_prompt_pick_by_number(monkeypatch, capsys):
    monkeypatch.setattr(gnss_logger, 'list_serial_ports', lambda: ['COM3', 'COM7'])
    a = parse([], stdin=FakeStdin(True), input_fn=answers('2'))
    assert a.port == 'COM7'
    assert '2) COM7' in capsys.readouterr().out


def test_tty_prompt_name_not_in_list(monkeypatch):
    monkeypatch.setattr(gnss_logger, 'list_serial_ports', lambda: ['COM3'])
    a = parse([], stdin=FakeStdin(True), input_fn=answers('COM12'))
    assert a.port == 'COM12'


@pytest.mark.parametrize('reply', ['', EOFError(), KeyboardInterrupt()])
def test_tty_prompt_empty_or_aborted_errors(monkeypatch, reply):
    monkeypatch.setattr(gnss_logger, 'list_serial_ports', lambda: [])
    with pytest.raises(SystemExit) as e:
        parse([], stdin=FakeStdin(True), input_fn=answers(reply))
    assert e.value.code == 2


def test_list_serial_ports_returns_list():
    assert isinstance(gnss_logger.list_serial_ports(), list)
