"""
gnss_config.py

Load and validate a JSON config file shared by the GNSS toolkit scripts.

Recognised keys (all optional):

    {
      "port": "COM4",
      "mode": "cold",              # cold | warm | hot
      "duration": 900,             # seconds, > 0
      "output": "nmea_capture.txt",
      "start_time": "123456",      # HHMMSS (UTC)
      "ref_coords": [44.0886, -87.6576],   # or {"lat": .., "lon": ..}
      "bins": 15                   # histogram bins, > 0
    }

Unknown keys are rejected so a typo does not silently do nothing.
Values given on the command line always win over the config file.
"""

import json

MODES = ('cold', 'warm', 'hot')
KNOWN_KEYS = ('port', 'mode', 'duration', 'output', 'start_time',
              'ref_coords', 'bins')


class ConfigError(ValueError):
    """Raised when a config file is missing, malformed or has bad values."""


def _pos_int(key, v):
    if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
        raise ConfigError(f"'{key}' must be a positive integer, got {v!r}")
    return v


def _str(key, v):
    if not isinstance(v, str) or not v:
        raise ConfigError(f"'{key}' must be a non-empty string, got {v!r}")
    return v


def _ref_coords(v):
    if isinstance(v, dict):
        if set(v) != {'lat', 'lon'}:
            raise ConfigError("'ref_coords' object must have exactly 'lat' and 'lon'")
        lat, lon = v['lat'], v['lon']
    elif isinstance(v, (list, tuple)) and len(v) == 2:
        lat, lon = v
    else:
        raise ConfigError("'ref_coords' must be [lat, lon] or {\"lat\": .., \"lon\": ..}")
    for name, x, lim in (('lat', lat, 90), ('lon', lon, 180)):
        if isinstance(x, bool) or not isinstance(x, (int, float)):
            raise ConfigError(f"'ref_coords' {name} must be a number, got {x!r}")
        if not -lim <= x <= lim:
            raise ConfigError(f"'ref_coords' {name} out of range: {x}")
    return float(lat), float(lon)


def validate_config(data):
    """Validate a parsed config dict; return a normalised copy.

    ref_coords is returned as ref_lat / ref_lon.
    """
    if not isinstance(data, dict):
        raise ConfigError("config must be a JSON object")
    unknown = sorted(set(data) - set(KNOWN_KEYS))
    if unknown:
        raise ConfigError(f"unknown config key(s): {', '.join(unknown)}")
    out = {}
    if 'port' in data:
        out['port'] = _str('port', data['port'])
    if 'mode' in data:
        if data['mode'] not in MODES:
            raise ConfigError(f"'mode' must be one of {', '.join(MODES)}, got {data['mode']!r}")
        out['mode'] = data['mode']
    if 'duration' in data:
        out['duration'] = _pos_int('duration', data['duration'])
    if 'output' in data:
        out['output'] = _str('output', data['output'])
    if 'start_time' in data:
        st = data['start_time']
        if not isinstance(st, str) or len(st) != 6 or not st.isdigit() \
                or int(st[:2]) > 23 or int(st[2:4]) > 59 or int(st[4:]) > 59:
            raise ConfigError(f"'start_time' must be an HHMMSS string, got {st!r}")
        out['start_time'] = st
    if 'ref_coords' in data:
        out['ref_lat'], out['ref_lon'] = _ref_coords(data['ref_coords'])
    if 'bins' in data:
        out['bins'] = _pos_int('bins', data['bins'])
    return out


def load_config(path):
    """Read, parse and validate a JSON config file."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except OSError as e:
        raise ConfigError(f"cannot read config {path}: {e}") from e
    except json.JSONDecodeError as e:
        raise ConfigError(f"invalid JSON in {path}: {e}") from e
    return validate_config(data)


def merge(cli, config, defaults):
    """Pick each value from CLI (if not None), else config, else defaults."""
    out = dict(defaults)
    for k in set(defaults) | set(config) | set(cli):
        if cli.get(k) is not None:
            out[k] = cli[k]
        elif k in config:
            out[k] = config[k]
    return out
