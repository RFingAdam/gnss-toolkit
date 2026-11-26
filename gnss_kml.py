#!/usr/bin/env python3
"""
gnss_kml.py

Export the GGA fix track from an NMEA log as a KML file for Google Earth.

The KML contains:
  - the fix track as a LineString (in time order)
  - every valid fix as a point placemark (time, sats, HDOP, error)
  - the reference point, with CEP50 and CEP95 rings around it when
    --ref-lat/--ref-lon are given

Standard library only, so it runs without the analysis dependencies.

    python gnss_kml.py nmea_capture.txt --ref-lat 44.0886 --ref-lon -87.6576
"""

import argparse
import math
import os
import re
import sys
from xml.sax.saxutils import escape

EARTH_R = 6371000.0
GGA_RE = re.compile(r'^\$..GGA')


def _dm_to_deg(value, hemi, deg_digits):
    deg = float(value[:deg_digits]) + float(value[deg_digits:]) / 60.0
    return -deg if hemi in ('S', 'W') else deg


def parse_fixes(nmea_path):
    """Return a list of valid GGA fixes (fix quality > 0 with a position)."""
    fixes = []
    with open(nmea_path, 'r', errors='ignore') as f:
        for line in f:
            if not GGA_RE.match(line):
                continue
            flds = line.strip().split('*')[0].split(',')
            if len(flds) < 9:
                continue
            t = flds[1].split('.')[0]
            if len(t) != 6 or not t.isdigit():
                continue
            if not flds[6].isdigit() or int(flds[6]) == 0:
                continue
            if not flds[2] or not flds[4]:
                continue
            try:
                lat = _dm_to_deg(flds[2], flds[3], 2)
                lon = _dm_to_deg(flds[4], flds[5], 3)
            except ValueError:
                continue
            alt = None
            if len(flds) > 9 and flds[9]:
                try:
                    alt = float(flds[9])
                except ValueError:
                    alt = None
            fixes.append({
                'time_str': t,
                'lat': lat,
                'lon': lon,
                'alt': alt,
                'num_sats': int(flds[7]) if flds[7].isdigit() else None,
                'hdop': float(flds[8]) if flds[8] else None,
            })
    return fixes


def haversine(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def percentile(values, q):
    """Linear-interpolated percentile (same method as numpy's default)."""
    s = sorted(values)
    if not s:
        raise ValueError("percentile of empty list")
    k = (len(s) - 1) * q / 100.0
    lo = math.floor(k)
    hi = math.ceil(k)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def circle_coords(lat0, lon0, radius_m, n=72):
    """Points of a circle of radius_m around (lat0, lon0), closed ring."""
    m_lat = math.pi / 180 * EARTH_R
    m_lon = m_lat * math.cos(math.radians(lat0))
    pts = []
    for i in range(n + 1):
        a = 2 * math.pi * i / n
        pts.append((lon0 + radius_m * math.sin(a) / m_lon,
                    lat0 + radius_m * math.cos(a) / m_lat))
    return pts


def _coord_str(pts):
    return ' '.join(f"{lon:.8f},{lat:.8f},0" for lon, lat in pts)


def build_kml(fixes, ref_lat=None, ref_lon=None, name="GNSS fix track"):
    """Build the KML document as a string."""
    if not fixes:
        raise ValueError("No valid fixes to export.")
    has_ref = ref_lat is not None and ref_lon is not None
    cep50 = cep95 = None
    if has_ref:
        errs = [haversine(ref_lat, ref_lon, f['lat'], f['lon']) for f in fixes]
        for f, e in zip(fixes, errs):
            f['error_m'] = e
        cep50 = percentile(errs, 50)
        cep95 = percentile(errs, 95)

    out = []
    w = out.append
    w('<?xml version="1.0" encoding="UTF-8"?>')
    w('<kml xmlns="http://www.opengis.net/kml/2.2">')
    w('<Document>')
    w(f'<name>{escape(name)}</name>')
    w('<Style id="fix"><IconStyle><scale>0.4</scale><Icon>'
      '<href>http://maps.google.com/mapfiles/kml/shapes/shaded_dot.png</href>'
      '</Icon></IconStyle><LabelStyle><scale>0</scale></LabelStyle></Style>')
    w('<Style id="track"><LineStyle><color>ffff7f00</color><width>2</width>'
      '</LineStyle></Style>')
    w('<Style id="cep50"><LineStyle><color>ffff0000</color><width>2</width>'
      '</LineStyle><PolyStyle><fill>0</fill></PolyStyle></Style>')
    w('<Style id="cep95"><LineStyle><color>ff00ff00</color><width>2</width>'
      '</LineStyle><PolyStyle><fill>0</fill></PolyStyle></Style>')
    w('<Style id="ref"><IconStyle><color>ff0000ff</color><Icon>'
      '<href>http://maps.google.com/mapfiles/kml/paddle/red-stars.png</href>'
      '</Icon></IconStyle></Style>')

    w('<Placemark><name>Track</name><styleUrl>#track</styleUrl>'
      '<LineString><tessellate>1</tessellate><coordinates>'
      + _coord_str([(f['lon'], f['lat']) for f in fixes])
      + '</coordinates></LineString></Placemark>')

    w('<Folder><name>Fixes</name>')
    for f in fixes:
        desc = [f"Time (UTC): {f['time_str']}"]
        if f['num_sats'] is not None:
            desc.append(f"Sats: {f['num_sats']}")
        if f['hdop'] is not None:
            desc.append(f"HDOP: {f['hdop']:.2f}")
        if 'error_m' in f:
            desc.append(f"Error: {f['error_m']:.2f} m")
        w(f'<Placemark><name>{f["time_str"]}</name><styleUrl>#fix</styleUrl>'
          f'<description>{escape(" | ".join(desc))}</description>'
          f'<Point><coordinates>{f["lon"]:.8f},{f["lat"]:.8f},0</coordinates>'
          '</Point></Placemark>')
    w('</Folder>')

    if has_ref:
        w('<Placemark><name>Reference</name><styleUrl>#ref</styleUrl>'
          f'<Point><coordinates>{ref_lon:.8f},{ref_lat:.8f},0</coordinates>'
          '</Point></Placemark>')
        for label, style, radius in (('CEP50', 'cep50', cep50),
                                     ('CEP95', 'cep95', cep95)):
            if radius <= 0:
                continue
            w(f'<Placemark><name>{label} {radius:.2f} m</name>'
              f'<styleUrl>#{style}</styleUrl><Polygon><outerBoundaryIs>'
              '<LinearRing><coordinates>'
              + _coord_str(circle_coords(ref_lat, ref_lon, radius))
              + '</coordinates></LinearRing></outerBoundaryIs></Polygon>'
              '</Placemark>')

    w('</Document>')
    w('</kml>')
    return '\n'.join(out) + '\n'


def export_kml(nmea_path, out_path, ref_lat=None, ref_lon=None):
    fixes = parse_fixes(nmea_path)
    kml = build_kml(fixes, ref_lat, ref_lon,
                    name=os.path.basename(nmea_path))
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(kml)
    return len(fixes)


def main(argv=None):
    p = argparse.ArgumentParser(
        description="Export the GGA fix track of an NMEA log to KML")
    p.add_argument('nmea_file', help='NMEA log (e.g. from gnss_logger.py)')
    p.add_argument('-o', '--output',
                   help='KML output path (default: fix_track.kml next to the log)')
    p.add_argument('--ref-lat', type=float, help='Reference latitude (deg)')
    p.add_argument('--ref-lon', type=float, help='Reference longitude (deg)')
    args = p.parse_args(argv)
    if (args.ref_lat is None) != (args.ref_lon is None):
        p.error('--ref-lat and --ref-lon must be given together')
    out = args.output or os.path.join(
        os.path.dirname(args.nmea_file) or '.', 'fix_track.kml')
    try:
        n = export_kml(args.nmea_file, out, args.ref_lat, args.ref_lon)
    except (OSError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(f"Wrote {n} fixes to {out}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
