import os
import sys
import xml.etree.ElementTree as ET

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import gnss_kml  # noqa: E402

NS = {'k': 'http://www.opengis.net/kml/2.2'}

LOG = """# START 120000
$GPGGA,120005,4807.038,N,01131.000,E,0,00,,,M,,M,,*00
$GPGGA,120010.00,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47
$GPRMC,120010,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A
$GPGGA,120011,4807.039,N,01131.001,E,1,09,1.0,545.4,M,46.9,M,,*47
$GPGGA,120012,4807.040,S,01131.002,W,1,07,1.2,545.4,M,46.9,M,,*47
$GPGGA,12001x,4807.040,N,01131.002,E,1,07,1.2,545.4,M,46.9,M,,*47
"""


@pytest.fixture
def log(tmp_path):
    p = tmp_path / 'nmea_capture.txt'
    p.write_text(LOG)
    return p


def test_parse_fixes_keeps_only_valid_gga(log):
    fixes = gnss_kml.parse_fixes(str(log))
    assert [f['time_str'] for f in fixes] == ['120010', '120011', '120012']
    assert fixes[0]['lat'] == pytest.approx(48 + 7.038 / 60)
    assert fixes[0]['lon'] == pytest.approx(11 + 31.0 / 60)
    assert fixes[2]['lat'] < 0 and fixes[2]['lon'] < 0
    assert fixes[1]['num_sats'] == 9 and fixes[1]['hdop'] == pytest.approx(1.0)


def test_percentile_matches_numpy_linear():
    vals = [1.0, 2.0, 3.0, 4.0]
    assert gnss_kml.percentile(vals, 50) == pytest.approx(2.5)
    assert gnss_kml.percentile(vals, 95) == pytest.approx(3.85)


def test_circle_radius_is_correct():
    lat0, lon0 = 44.0, -87.6
    for lon, lat in gnss_kml.circle_coords(lat0, lon0, 10.0, n=12):
        assert gnss_kml.haversine(lat0, lon0, lat, lon) == pytest.approx(10.0, rel=1e-3)


def test_build_kml_without_reference_is_valid_xml(log):
    kml = gnss_kml.build_kml(gnss_kml.parse_fixes(str(log)))
    root = ET.fromstring(kml)
    names = [n.text for n in root.iterfind('.//k:Placemark/k:name', NS)]
    assert 'Track' in names
    assert 'Reference' not in names
    assert not any(n.startswith('CEP') for n in names)
    coords = root.find('.//k:LineString/k:coordinates', NS).text.split()
    assert len(coords) == 3


def test_build_kml_with_reference_has_cep_rings(log):
    fixes = gnss_kml.parse_fixes(str(log))[:2]
    kml = gnss_kml.build_kml(fixes, 48 + 7.038 / 60, 11 + 31.0 / 60)
    root = ET.fromstring(kml)
    names = [n.text for n in root.iterfind('.//k:Placemark/k:name', NS)]
    assert 'Reference' in names
    assert any(n.startswith('CEP50') for n in names)
    assert any(n.startswith('CEP95') for n in names)
    assert 'Error:' in kml


def test_build_kml_empty_raises():
    with pytest.raises(ValueError):
        gnss_kml.build_kml([])


def test_cli_writes_default_path(log, capsys):
    rc = gnss_kml.main([str(log), '--ref-lat', '48.1173', '--ref-lon', '11.5167'])
    assert rc == 0
    out = log.parent / 'fix_track.kml'
    assert out.exists()
    ET.parse(out)
    assert 'Wrote 3 fixes' in capsys.readouterr().out


def test_cli_requires_both_ref_coords(log):
    with pytest.raises(SystemExit):
        gnss_kml.main([str(log), '--ref-lat', '48.1'])


def test_cli_no_fixes_returns_error(tmp_path):
    p = tmp_path / 'empty.txt'
    p.write_text('# START 000000\n')
    assert gnss_kml.main([str(p), '-o', str(tmp_path / 'x.kml')]) == 1
