"""Tests for GSA (PDOP/HDOP/VDOP) parsing and plotting."""
import math
from functools import reduce

import matplotlib

matplotlib.use("Agg")

import pytest

import gnss_nmea_analysis as ga


def nmea(body):
    cs = reduce(lambda acc, ch: acc ^ ord(ch), body, 0)
    return f"${body}*{cs:02X}"


def gga(t, lat="4400.000", ns="N", lon="08730.000", ew="W", fix=1):
    return nmea(f"GPGGA,{t},{lat},{ns},{lon},{ew},{fix},08,1.3,200.0,M,-34.0,M,,")


def gsa(pdop, hdop, vdop, fix_type=3, prns=("04", "05", "09", "12", "24"), talker="GP", sys_id=None):
    slots = list(prns) + [""] * (12 - len(prns))
    body = f"{talker}GSA,A,{fix_type}," + ",".join(slots) + f",{pdop},{hdop},{vdop}"
    if sys_id is not None:
        body += f",{sys_id}"
    return nmea(body)


def write_log(tmp_path, lines):
    p = tmp_path / "capture.txt"
    p.write_text("\n".join(lines) + "\n")
    return str(p)


def test_gsa_helper_matches_reference_sentence():
    # Standard NMEA 0183 GSA example.
    assert gsa("2.5", "1.3", "2.1", prns=("04", "05", "", "09", "12", "", "", "24")) \
        == "$GPGSA,A,3,04,05,,09,12,,,24,,,,,2.5,1.3,2.1*39"


def test_parse_gsa_extracts_dops_and_prn_count(tmp_path):
    path = write_log(tmp_path, [gga("120000"), gsa("2.5", "1.3", "2.1")])
    df = ga.parse_gsa(path)
    assert len(df) == 1
    row = df.iloc[0]
    assert row.time_str == "120000"
    assert row.fix_type == 3
    assert row.num_used == 5
    assert (row.pdop, row.hdop, row.vdop) == pytest.approx((2.5, 1.3, 2.1))


def test_parse_gsa_accepts_nmea41_system_id(tmp_path):
    path = write_log(tmp_path, [gga("120000"), gsa("1.8", "1.0", "1.5", talker="GN", sys_id="1")])
    row = ga.parse_gsa(path).iloc[0]
    assert (row.pdop, row.hdop, row.vdop) == pytest.approx((1.8, 1.0, 1.5))


def test_parse_gsa_handles_no_fix_and_empty_dops(tmp_path):
    path = write_log(tmp_path, [gsa("", "", "", fix_type=1, prns=())])
    row = ga.parse_gsa(path).iloc[0]
    assert row.time_str == ""
    assert row.fix_type == 1
    assert row.num_used == 0
    assert math.isnan(row.pdop) and math.isnan(row.vdop)


def test_parse_gsa_empty_when_absent(tmp_path):
    df = ga.parse_gsa(write_log(tmp_path, [gga("120000")]))
    assert df.empty
    assert {"pdop", "hdop", "vdop"} <= set(df.columns)


def test_dop_per_epoch_dedupes_constellations_and_drops_no_fix(tmp_path):
    lines = [
        gsa("9.9", "9.9", "9.9", fix_type=1, prns=()),  # before any time: dropped
        gga("120000"),
        gsa("2.0", "1.1", "1.7", talker="GN", sys_id="1"),
        gsa("2.0", "1.1", "1.7", talker="GN", prns=("70", "71"), sys_id="2"),
        gga("120001"),
        gsa("", "", "", fix_type=1, prns=()),            # no fix: dropped
        gga("120002"),
        gsa("2.2", "1.2", "1.8"),
    ]
    dop = ga.dop_per_epoch(ga.parse_gsa(write_log(tmp_path, lines)))
    assert list(dop.time_str) == ["120000", "120002"]
    assert list(dop.pdop) == pytest.approx([2.0, 2.2])
    assert list(dop.vdop) == pytest.approx([1.7, 1.8])


def test_analyze_reports_and_plots_dop(tmp_path):
    lines = ["# START 115950"]
    for k, (p, h, v) in enumerate([("2.0", "1.0", "1.7"), ("3.0", "1.5", "2.6"), ("4.0", "2.0", "3.5")]):
        lines += [gga(f"12000{k}"), gsa(p, h, v)]
    path = write_log(tmp_path, lines)
    summary = ga.analyze(path, "115950", 44.0, -87.5)
    assert "PDOP: 3.00 / 4.00" in summary
    assert "HDOP: 1.50 / 2.00" in summary
    assert "VDOP: 2.60 / 3.50" in summary
    assert (tmp_path / "dop_vs_time.png").stat().st_size > 0


def test_analyze_without_gsa_skips_dop_plot(tmp_path):
    path = write_log(tmp_path, [gga("120000"), gga("120001")])
    summary = ga.analyze(path, "115950", 44.0, -87.5)
    assert "PDOP" not in summary
    assert not (tmp_path / "dop_vs_time.png").exists()
