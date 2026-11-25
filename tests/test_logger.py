"""CLI workflow tests for gnss_logger using a fake serial port."""
import sys
from functools import reduce

import pytest

import gnss_logger


def nmea(body):
    cs = reduce(lambda acc, ch: acc ^ ord(ch), body, 0)
    return f"${body}*{cs:02X}"


class FakeSerial:
    """Answers every AT command with OK, then streams queued lines."""

    def __init__(self, lines):
        self.queue = [l.encode() + b"\r\n" for l in lines]
        self.written = []

    def write(self, data):
        self.written.append(data.decode().strip())
        self.queue.insert(0, b"OK\r\n")

    def readline(self):
        return self.queue.pop(0) if self.queue else b""

    def reset_input_buffer(self):
        pass


def test_send_at_returns_true_on_ok():
    ser = FakeSerial([])
    assert gnss_logger.send_at(ser, "AT", timeout=1.0) is True
    assert ser.written == ["AT"]


def test_send_at_returns_false_on_error():
    class ErrSerial(FakeSerial):
        def write(self, data):
            self.written.append(data.decode().strip())
            self.queue.insert(0, b"ERROR\r\n")

    assert gnss_logger.send_at(ErrSerial([]), "AT$BAD", timeout=1.0) is False


@pytest.mark.parametrize("mode,val", [("cold", "1"), ("warm", "2"), ("hot", "3")])
def test_main_logs_only_nmea_with_start_header(tmp_path, monkeypatch, capsys, mode, val):
    fix = nmea("GPGGA,120030,4400.000,N,08730.000,W,1,08,0.9,200.0,M,-34.0,M,,")
    nofix = nmea("GPGGA,120000,,,,,0,00,,,M,,M,,")
    fake = FakeSerial([nofix, "+CREG: 1", fix])
    monkeypatch.setattr(gnss_logger.serial, "Serial", lambda *a, **k: fake)
    out = tmp_path / "log.txt"
    monkeypatch.setattr(sys, "argv", ["gnss_logger.py", "COM9", "--mode", mode,
                                      "--duration", "1", "--output", str(out)])

    gnss_logger.main()

    lines = out.read_text().splitlines()
    assert lines[0].startswith("# START ") and len(lines[0].split()[-1]) == 6
    assert lines[1:] == [nofix, fix]
    assert fake.written[0] == f"AT$GPSR={val}"
    assert "AT$GPSP=1" in fake.written
    assert "FIRST FIX @ 120030" in capsys.readouterr().out


def test_main_exits_when_port_cannot_open(monkeypatch):
    def boom(*a, **k):
        raise OSError("no such port")

    monkeypatch.setattr(gnss_logger.serial, "Serial", boom)
    monkeypatch.setattr(sys, "argv", ["gnss_logger.py", "COM99"])
    with pytest.raises(SystemExit) as exc:
        gnss_logger.main()
    assert exc.value.code == 1
