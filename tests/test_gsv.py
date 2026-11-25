"""Tests for GSV (per-satellite SNR) parsing and plotting."""
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


def gsv(total, num, in_view, sats, talker="GP", signal_id=None):
    """sats: list of (prn, elev, az, snr) tuples of strings."""
    body = f"{talker}GSV,{total},{num},{in_view}"
    for blk in sats:
        body += "," + ",".join(blk)
    if signal_id is not None:
        body += f",{signal_id}"
    return nmea(body)


def write_log(tmp_path, lines):
    p = tmp_path / "capture.txt"
    p.write_text("\n".join(lines) + "\n")
    return str(p)


def test_gsv_helper_matches_reference_sentence():
    # Standard NMEA 0183 GSV example.
    assert gsv("3", "1", "11", [("03", "03", "111", "00"), ("04", "15", "270", "00"),
                                ("06", "01", "010", "00"), ("13", "06", "292", "00")]) \
        == "$GPGSV,3,1,11,03,03,111,00,04,15,270,00,06,01,010,00,13,06,292,00*74"


def test_parse_gsv_extracts_every_satellite_block(tmp_path):
    lines = [gga("120000"),
             gsv("2", "1", "5", [("02", "45", "120", "42"), ("05", "30", "200", "38"),
                                 ("12", "10", "300", ""), ("25", "60", "045", "47")]),
             gsv("2", "2", "5", [("29", "05", "090", "21")])]
    df = ga.parse_gsv(write_log(tmp_path, lines))
    assert list(df.prn) == [2, 5, 12, 25, 29]
    assert set(df.time_str) == {"120000"}
    assert df.iloc[0].elevation == 45 and df.iloc[0].azimuth == 120
    assert list(df.snr.iloc[:2]) == [42, 38]
    assert math.isnan(df.iloc[2].snr)  # not tracked
    assert set(df.constellation) == {"GPS"}


def test_parse_gsv_nmea41_signal_id_and_constellations(tmp_path):
    lines = [gga("120000"),
             gsv("1", "1", "2", [("70", "40", "100", "35"), ("71", "20", "150", "30")],
                 talker="GL", signal_id="1"),
             gsv("1", "1", "1", [("11", "55", "010", "44")], talker="GA", signal_id="7")]
    df = ga.parse_gsv(write_log(tmp_path, lines))
    assert list(df.prn) == [70, 71, 11]
    assert list(df.constellation) == ["GLONASS", "GLONASS", "Galileo"]
    assert list(df.snr) == [35, 30, 44]


def test_parse_gsv_empty_when_absent(tmp_path):
    df = ga.parse_gsv(write_log(tmp_path, [gga("120000")]))
    assert df.empty
    assert "snr" in df.columns


def test_snr_per_satellite_aggregates_tracked_reports(tmp_path):
    lines = []
    for t, snr in (("120000", "40"), ("120001", "44"), ("120002", "")):
        lines += [gga(t), gsv("1", "1", "2", [("07", "50", "100", snr), ("09", "20", "200", "30")])]
    stats = ga.snr_per_satellite(ga.parse_gsv(write_log(tmp_path, lines)))
    s7 = stats[stats.prn == 7].iloc[0]
    assert s7.mean_snr == pytest.approx(42.0)
    assert s7.max_snr == 44
    assert s7.epochs == 2
    assert stats[stats.prn == 9].iloc[0].epochs == 3


def test_analyze_reports_and_plots_snr(tmp_path):
    lines = ["# START 115950"]
    for t in ("120000", "120001"):
        lines += [gga(t), gsv("1", "1", "2", [("07", "50", "100", "40"), ("09", "20", "200", "30")])]
    summary = ga.analyze(write_log(tmp_path, lines), "115950", 44.0, -87.5)
    assert "Satellites tracked: 2" in summary
    assert "Mean SNR: 35.0" in summary
    assert "Best: 40" in summary
    assert (tmp_path / "snr_per_satellite.png").stat().st_size > 0


def test_analyze_without_gsv_skips_snr_plot(tmp_path):
    summary = ga.analyze(write_log(tmp_path, [gga("120000")]), "115950", 44.0, -87.5)
    assert "SNR" not in summary
    assert not (tmp_path / "snr_per_satellite.png").exists()
