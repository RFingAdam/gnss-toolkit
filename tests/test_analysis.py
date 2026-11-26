"""Unit and regression tests for gnss_nmea_analysis (parsing, TTFF, CEP, end-to-end)."""
import math
import os
from functools import reduce

import matplotlib

matplotlib.use("Agg")

import numpy as np
import pytest

import gnss_nmea_analysis as ga


def nmea(body):
    """Wrap a sentence body (no '$' / '*') with a valid NMEA 0183 checksum."""
    cs = reduce(lambda acc, ch: acc ^ ord(ch), body, 0)
    return f"${body}*{cs:02X}"


def gga(time_str, lat="", ns="", lon="", ew="", fix=1, sats="08", hdop="0.9", talker="GP"):
    body = (f"{talker}GGA,{time_str},{lat},{ns},{lon},{ew},{fix},{sats},{hdop},"
            "545.4,M,46.9,M,,")
    return nmea(body)


def write_log(tmp_path, lines, name="capture.txt"):
    p = tmp_path / name
    p.write_text("\n".join(lines) + "\n")
    return str(p)


# --- checksum helper sanity (classic NMEA 0183 example) -------------------

def test_checksum_helper_matches_reference_sentence():
    assert nmea("GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,") \
        == "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47"


# --- parse_nmea -----------------------------------------------------------

def test_parse_nmea_converts_ddmm_to_decimal_degrees(tmp_path):
    path = write_log(tmp_path, [gga("123519", "4807.038", "N", "01131.000", "E")])
    df = ga.parse_nmea(path)
    assert len(df) == 1
    row = df.iloc[0]
    assert row.lat == pytest.approx(48 + 7.038 / 60)
    assert row.lon == pytest.approx(11 + 31.0 / 60)
    assert row.fix_quality == 1
    assert row.num_sats == 8
    assert row.hdop == pytest.approx(0.9)
    assert row.time_str == "123519"


def test_parse_nmea_south_and_west_are_negative(tmp_path):
    path = write_log(tmp_path, [gga("000001", "3352.000", "S", "15112.000", "W")])
    row = ga.parse_nmea(path).iloc[0]
    assert row.lat == pytest.approx(-(33 + 52 / 60))
    assert row.lon == pytest.approx(-(151 + 12 / 60))


def test_parse_nmea_strips_fractional_seconds_and_accepts_any_talker(tmp_path):
    path = write_log(tmp_path, [gga("101010.00", "4500.000", "N", "08700.000", "W", talker="GN")])
    df = ga.parse_nmea(path)
    assert df.iloc[0].time_str == "101010"


def test_parse_nmea_no_fix_rows_have_no_position(tmp_path):
    path = write_log(tmp_path, [gga("120000", fix=0, sats="00", hdop="")])
    row = ga.parse_nmea(path).iloc[0]
    assert row.fix_quality == 0
    assert row.lat is None or (isinstance(row.lat, float) and math.isnan(row.lat))
    assert math.isnan(row.hdop)


def test_parse_nmea_ignores_header_and_other_sentences(tmp_path):
    lines = [
        "# START 120000",
        nmea("GPRMC,120001,A,4500.000,N,08700.000,W,0.0,0.0,251126,,,A"),
        gga("120001", "4500.000", "N", "08700.000", "W"),
        nmea("GPGSA,A,3,04,05,,09,12,,,24,,,,,2.5,1.3,2.1"),
        "garbage line",
    ]
    df = ga.parse_nmea(write_log(tmp_path, lines))
    assert len(df) == 1


def test_parse_nmea_skips_malformed_time(tmp_path):
    lines = [gga("12AB19", "4500.000", "N", "08700.000", "W"),
             gga("120002", "4500.000", "N", "08700.000", "W")]
    df = ga.parse_nmea(write_log(tmp_path, lines))
    assert list(df.time_str) == ["120002"]


def test_parse_nmea_raises_when_no_gga(tmp_path):
    path = write_log(tmp_path, ["# START 120000", nmea("GPGSA,A,1,,,,,,,,,,,,,99.9,99.9,99.9")])
    with pytest.raises(ValueError, match="No valid GGA"):
        ga.parse_nmea(path)


# --- haversine ------------------------------------------------------------

def test_haversine_zero_distance():
    assert ga.haversine(44.0, -87.6, 44.0, -87.6) == pytest.approx(0.0)


def test_haversine_one_degree_of_latitude():
    expected = 6371000 * math.pi / 180  # ~111 195 m on the 6371 km sphere
    assert ga.haversine(0.0, 0.0, 1.0, 0.0) == pytest.approx(expected, rel=1e-9)


def test_haversine_is_symmetric():
    a = ga.haversine(44.09, -87.65, 44.10, -87.60)
    b = ga.haversine(44.10, -87.60, 44.09, -87.65)
    assert a == pytest.approx(b)


# --- TTFF -----------------------------------------------------------------

def test_compute_ttff_simple():
    assert ga.compute_ttff("120000", "120045") == 45


def test_compute_ttff_wraps_midnight():
    assert ga.compute_ttff("235950", "000010") == 20


# --- CEP / RMS --------------------------------------------------------------

def test_compute_error_stats_known_values():
    errors = np.arange(1, 101, dtype=float)  # 1..100 m
    cep50, cep95, rms = ga.compute_error_stats(errors)
    assert cep50 == pytest.approx(50.5)
    assert cep95 == pytest.approx(95.05)
    assert rms == pytest.approx(math.sqrt(np.mean(errors ** 2)))


def test_compute_error_stats_constant_error():
    assert ga.compute_error_stats([3.0, 3.0, 3.0]) == pytest.approx((3.0, 3.0, 3.0))


def test_compute_error_stats_empty_raises():
    with pytest.raises(ValueError):
        ga.compute_error_stats([])


# --- end-to-end regression ------------------------------------------------

REF_LAT, REF_LON = 44.0, -87.5  # 4400.000 N, 08730.000 W


def _regression_log(tmp_path):
    lines = ["# START 120000",
             gga("120000", fix=0, sats="00", hdop=""),
             gga("120010", fix=0, sats="03", hdop="")]
    # Fixes every second from 120030, offset north by k * 0.001 arc-minutes.
    for k in range(10):
        lat = f"4400.{k:03d}"
        lines.append(gga(f"1200{30 + k:02d}", lat, "N", "08730.000", "W",
                         sats=f"{6 + k % 3:02d}", hdop=f"{1.0 + 0.1 * k:.1f}"))
    return write_log(tmp_path, lines)


def test_analyze_end_to_end_regression(tmp_path):
    path = _regression_log(tmp_path)
    summary = ga.analyze(path, "120000", REF_LAT, REF_LON)

    # Expected errors: k * 0.001' north of the reference on a 6371 km sphere.
    m_per_arcmin = 6371000 * math.pi / 180 / 60
    errors = np.array([k * 0.001 * m_per_arcmin for k in range(10)])
    cep50 = np.percentile(errors, 50)
    cep95 = np.percentile(errors, 95)
    rms = math.sqrt(np.mean(errors ** 2))

    assert "First Fix Time (UTC): 120030" in summary
    assert "TTFF (s): 30.0" in summary
    assert "Num Fixes: 10" in summary
    assert f"CEP50: {cep50:.2f} m" in summary
    assert f"CEP95: {cep95:.2f} m" in summary
    assert f"RMS Error: {rms:.2f} m" in summary

    for name in ("summary_notes.txt", "error_histogram.png", "scatter_with_cep.png",
                 "error_vs_hdop.png", "sats_vs_time.png"):
        assert (tmp_path / name).stat().st_size > 0, name
    assert (tmp_path / "summary_notes.txt").read_text() == summary


def test_analyze_honours_out_dir(tmp_path):
    path = _regression_log(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    ga.analyze(path, "120000", REF_LAT, REF_LON, out_dir=str(out))
    assert (out / "summary_notes.txt").exists()
    assert not (tmp_path / "summary_notes.txt").exists()


def test_analyze_rejects_bad_start_time(tmp_path):
    path = _regression_log(tmp_path)
    with pytest.raises(ValueError, match="HHMMSS"):
        ga.analyze(path, "12:00", REF_LAT, REF_LON)


def test_analyze_requires_a_path():
    with pytest.raises(ValueError, match="Select"):
        ga.analyze("", "120000", REF_LAT, REF_LON)


def test_analyze_without_any_fix_raises(tmp_path):
    path = write_log(tmp_path, [gga("120000", fix=0, sats="00", hdop="")])
    with pytest.raises(ValueError, match="No valid fixes"):
        ga.analyze(path, "120000", REF_LAT, REF_LON)


def test_module_imports_without_starting_gui():
    # Importing must not create a Tk root (it used to at import time).
    assert hasattr(ga, "main")
    assert not hasattr(ga, "root")
