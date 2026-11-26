"""Tests for speed/track parsing from RMC and VTG."""
import math
from functools import reduce

import matplotlib

matplotlib.use("Agg")

import pytest

import gnss_nmea_analysis as ga


def nmea(body):
    cs = reduce(lambda acc, ch: acc ^ ord(ch), body, 0)
    return f"${body}*{cs:02X}"


def gga(t):
    return nmea(f"GPGGA,{t},4400.000,N,08730.000,W,1,08,1.0,200.0,M,-34.0,M,,")


def rmc(t, knots, track, status="A"):
    return nmea(f"GPRMC,{t},{status},4400.000,N,08730.000,W,{knots},{track},251126,003.1,W")


def vtg(track, knots, kmh, mode="A"):
    return nmea(f"GPVTG,{track},T,,M,{knots},N,{kmh},K,{mode}")


def write_log(tmp_path, lines):
    p = tmp_path / "capture.txt"
    p.write_text("\n".join(lines) + "\n")
    return str(p)


def test_reference_sentences_checksums():
    # Standard NMEA 0183 examples.
    assert nmea("GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W") \
        == "$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A"
    assert nmea("GPVTG,054.7,T,034.4,M,005.5,N,010.2,K") == "$GPVTG,054.7,T,034.4,M,005.5,N,010.2,K*48"


def test_parse_velocity_rmc_converts_knots_to_kmh(tmp_path):
    df = ga.parse_velocity(write_log(tmp_path, [rmc("123519", "022.4", "084.4")]))
    row = df.iloc[0]
    assert row.source == "RMC" and row.time_str == "123519"
    assert row.speed_kmh == pytest.approx(22.4 * 1.852)
    assert row.track_deg == pytest.approx(84.4)


def test_parse_velocity_skips_void_rmc(tmp_path):
    df = ga.parse_velocity(write_log(tmp_path, [rmc("120000", "", "", status="V")]))
    assert df.empty


def test_parse_velocity_vtg_uses_kmh_and_last_time(tmp_path):
    lines = [vtg("054.7", "005.5", "010.2"),  # before any time: dropped
             gga("120000"), vtg("054.7", "005.5", "010.2")]
    df = ga.parse_velocity(write_log(tmp_path, lines))
    assert len(df) == 1
    row = df.iloc[0]
    assert row.source == "VTG" and row.time_str == "120000"
    assert row.speed_kmh == pytest.approx(10.2)
    assert row.track_deg == pytest.approx(54.7)


def test_parse_velocity_vtg_falls_back_to_knots(tmp_path):
    df = ga.parse_velocity(write_log(tmp_path, [gga("120000"), vtg("", "010.0", "", mode="A")]))
    assert df.iloc[0].speed_kmh == pytest.approx(18.52)
    assert math.isnan(df.iloc[0].track_deg)


def test_velocity_per_epoch_prefers_rmc(tmp_path):
    lines = [gga("120000"), vtg("090.0", "001.0", "001.9"), rmc("120000", "002.0", "091.0"),
             gga("120001"), vtg("092.0", "003.0", "005.6")]
    vel = ga.velocity_per_epoch(ga.parse_velocity(write_log(tmp_path, lines)))
    assert list(vel.time_str) == ["120000", "120001"]
    assert list(vel.source) == ["RMC", "VTG"]
    assert vel.speed_kmh.iloc[0] == pytest.approx(2.0 * 1.852)


def test_analyze_reports_and_plots_velocity(tmp_path):
    lines = ["# START 115950"]
    for t, kn in (("120000", "000.0"), ("120001", "010.0"), ("120002", "020.0")):
        lines += [gga(t), rmc(t, kn, "045.0")]
    summary = ga.analyze(write_log(tmp_path, lines), "115950", 44.0, -87.5)
    assert "Mean speed: 18.52 km/h" in summary
    assert "Max speed: 37.04 km/h" in summary
    assert (tmp_path / "velocity_vs_time.png").stat().st_size > 0
    assert (tmp_path / "summary_notes.txt").read_text() == summary


def test_analyze_without_velocity_skips_plot(tmp_path):
    summary = ga.analyze(write_log(tmp_path, [gga("120000")]), "115950", 44.0, -87.5)
    assert "speed" not in summary
    assert not (tmp_path / "velocity_vs_time.png").exists()
