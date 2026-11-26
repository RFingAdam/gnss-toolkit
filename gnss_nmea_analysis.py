#!/usr/bin/env python3
"""
gnss_analysis_gui.py

Tkinter GUI for GNSS TTFF & CEP analysis from NMEA logs.

All outputs are saved next to the selected NMEA file:
  • error_histogram.png
  • scatter_with_cep.png
  • error_vs_hdop.png
  • sats_vs_time.png
  • dop_vs_time.png         (when the log has GSA sentences)
  • snr_per_satellite.png   (when the log has GSV sentences)
  • velocity_vs_time.png    (when the log has RMC or VTG sentences)
  • summary_notes.txt        <- added

Distances computed via the Haversine formula on a WGS-84 sphere
(Earth radius ≈ 6 371 000 m), but for the plan view we use a
flat‐Earth ENU approximation to plot in meters.
"""

import os
import re
import math
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime


def parse_nmea(nmea_file):
    pat = re.compile(r'^\$..GGA')
    rows = []
    with open(nmea_file, 'r') as f:
        for line in f:
            if pat.match(line):
                flds = line.split(',')
                if len(flds) < 9: continue
                t = flds[1].split('.')[0]
                if len(t)!=6 or not t.isdigit(): continue
                fq = int(flds[6]) if flds[6].isdigit() else 0
                lat = lon = None
                if flds[2] and flds[4]:
                    la = float(flds[2][:2]) + float(flds[2][2:]) / 60
                    if flds[3] == 'S': la = -la
                    lo = float(flds[4][:3]) + float(flds[4][3:]) / 60
                    if flds[5] == 'W': lo = -lo
                    lat, lon = la, lo
                hd = float(flds[8]) if flds[8] else np.nan
                ns = int(flds[7]) if flds[7].isdigit() else np.nan
                rows.append({'time_str': t, 'fix_quality': fq,
                             'lat': lat, 'lon': lon,
                             'hdop': hd, 'num_sats': ns})
    df = pd.DataFrame(rows)
    if df.empty:
        raise ValueError("No valid GGA sentences found.")
    df['time'] = pd.to_datetime(df['time_str'], format='%H%M%S').dt.time
    return df


def _to_float(field):
    try:
        return float(field)
    except (TypeError, ValueError):
        return np.nan


def parse_gsa(nmea_file):
    """Parse GSA sentences into a DataFrame of PDOP/HDOP/VDOP.

    GSA (NMEA 0183) fields: mode, fix type (1=none, 2=2D, 3=3D), 12 PRN
    slots, PDOP, HDOP, VDOP and, from NMEA 4.10, an optional system ID.
    GSA carries no time, so each row is tagged with the UTC time of the
    most recent GGA/RMC sentence seen before it (empty if none yet).
    Returns an empty DataFrame when the log has no GSA sentences.
    """
    time_pat = re.compile(r'^\$..(GGA|RMC),')
    gsa_pat = re.compile(r'^\$..GSA,')
    rows = []
    last_time = ''
    with open(nmea_file, 'r') as f:
        for line in f:
            line = line.strip()
            if time_pat.match(line):
                t = line.split(',')[1].split('.')[0]
                if len(t) == 6 and t.isdigit():
                    last_time = t
                continue
            if not gsa_pat.match(line):
                continue
            flds = line.split('*')[0].split(',')
            if len(flds) < 18:
                continue
            fix_type = int(flds[2]) if flds[2].isdigit() else 0
            prns = [p for p in flds[3:15] if p]
            rows.append({'time_str': last_time,
                         'mode': flds[1],
                         'fix_type': fix_type,
                         'num_used': len(prns),
                         'pdop': _to_float(flds[15]),
                         'hdop': _to_float(flds[16]),
                         'vdop': _to_float(flds[17])})
    return pd.DataFrame(rows, columns=['time_str', 'mode', 'fix_type',
                                       'num_used', 'pdop', 'hdop', 'vdop'])


def dop_per_epoch(gsa_df):
    """Collapse multi-constellation GSA rows to one DOP row per epoch.

    Receivers emit one GSA per constellation per epoch with identical DOP
    values, so the first row with a 2D/3D fix for each time is kept.
    """
    if gsa_df.empty:
        return gsa_df
    fixed = gsa_df[(gsa_df.fix_type >= 2) & (gsa_df.time_str != '')]
    return fixed.groupby('time_str', sort=False).first().reset_index()


def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


CONSTELLATION_BY_TALKER = {
    'GP': 'GPS', 'GL': 'GLONASS', 'GA': 'Galileo', 'GB': 'BeiDou',
    'BD': 'BeiDou', 'GQ': 'QZSS', 'GI': 'NavIC', 'GN': 'GNSS',
}


def parse_gsv(nmea_file):
    """Parse GSV sentences into one row per satellite report.

    GSV (NMEA 0183) fields: total messages, message number, satellites in
    view, then up to four blocks of PRN, elevation (deg), azimuth (deg)
    and SNR (C/N0, dB-Hz; empty when not tracking). NMEA 4.10 adds an
    optional signal ID after the last block, which is ignored here.
    GSV carries no time, so rows are tagged with the UTC time of the most
    recent GGA/RMC sentence before them (empty if none yet).
    Returns an empty DataFrame when the log has no GSV sentences.
    """
    time_pat = re.compile(r'^\$..(GGA|RMC),')
    gsv_pat = re.compile(r'^\$(..)GSV,')
    rows = []
    last_time = ''
    with open(nmea_file, 'r') as f:
        for line in f:
            line = line.strip()
            if time_pat.match(line):
                t = line.split(',')[1].split('.')[0]
                if len(t) == 6 and t.isdigit():
                    last_time = t
                continue
            m = gsv_pat.match(line)
            if not m:
                continue
            talker = m.group(1)
            flds = line.split('*')[0].split(',')
            blocks = flds[4:]
            if len(blocks) % 4 == 1:  # NMEA 4.10 signal ID
                blocks = blocks[:-1]
            for i in range(0, len(blocks) - 3, 4):
                prn, elev, az, snr = blocks[i:i + 4]
                if not prn.isdigit():
                    continue
                rows.append({
                    'time_str': last_time,
                    'talker': talker,
                    'constellation': CONSTELLATION_BY_TALKER.get(talker, talker),
                    'prn': int(prn),
                    'elevation': float(elev) if elev else np.nan,
                    'azimuth': float(az) if az else np.nan,
                    'snr': float(snr) if snr else np.nan,
                })
    return pd.DataFrame(rows, columns=['time_str', 'talker', 'constellation', 'prn',
                                       'elevation', 'azimuth', 'snr'])


def snr_per_satellite(gsv_df):
    """Mean/max SNR and number of tracked epochs per satellite (tracked reports only)."""
    tracked = gsv_df.dropna(subset=['snr'])
    if tracked.empty:
        return pd.DataFrame(columns=['constellation', 'prn', 'mean_snr', 'max_snr', 'epochs'])
    out = (tracked.groupby(['constellation', 'prn'])['snr']
           .agg(mean_snr='mean', max_snr='max', epochs='count')
           .reset_index()
           .sort_values(['constellation', 'prn'])
           .reset_index(drop=True))
    return out


def compute_ttff(start_hhmmss, fix_hhmmss):
    """Seconds from GNSS start to first fix, both given as UTC HHMMSS.

    Wraps across midnight: a fix time earlier than the start time is
    treated as the next UTC day.
    """
    dt_start = datetime.strptime(start_hhmmss, '%H%M%S')
    dt_fix = datetime.strptime(fix_hhmmss, '%H%M%S')
    ttff = (dt_fix - dt_start).total_seconds()
    if ttff < 0:
        ttff += 86400
    return ttff


def compute_error_stats(errors_m):
    """Return (CEP50, CEP95, RMS) in metres for a sequence of horizontal errors."""
    errors = np.asarray(errors_m, dtype=float)
    if errors.size == 0:
        raise ValueError("No position errors to summarise.")
    cep50 = float(np.percentile(errors, 50))
    cep95 = float(np.percentile(errors, 95))
    rms = math.sqrt(float((errors ** 2).mean()))
    return cep50, cep95, rms


KNOTS_TO_KMH = 1.852


def parse_velocity(nmea_file):
    """Parse speed over ground and true track from RMC and VTG sentences.

    RMC (NMEA 0183): time, status (A=valid, V=void), position, speed in
    knots (field 7), true track in degrees (field 8). Void RMC sentences
    are skipped. VTG: true track (field 1), magnetic track (3), speed in
    knots (5) and km/h (7); VTG has no time, so it is tagged with the
    most recent GGA/RMC time. Returns columns time_str, source,
    speed_kmh, track_deg (empty DataFrame when neither sentence is present).
    """
    time_pat = re.compile(r'^\$..GGA,')
    rmc_pat = re.compile(r'^\$..RMC,')
    vtg_pat = re.compile(r'^\$..VTG,')
    rows = []
    last_time = ''

    def _time(field):
        t = field.split('.')[0]
        return t if len(t) == 6 and t.isdigit() else ''

    with open(nmea_file, 'r') as f:
        for line in f:
            line = line.strip()
            flds = line.split('*')[0].split(',')
            if time_pat.match(line):
                last_time = _time(flds[1]) or last_time
            elif rmc_pat.match(line):
                if len(flds) < 9:
                    continue
                t = _time(flds[1])
                if t:
                    last_time = t
                if flds[2] != 'A' or not t:
                    continue
                kn = float(flds[7]) if flds[7] else np.nan
                rows.append({'time_str': t, 'source': 'RMC',
                             'speed_kmh': kn * KNOTS_TO_KMH,
                             'track_deg': float(flds[8]) if flds[8] else np.nan})
            elif vtg_pat.match(line):
                if len(flds) < 8 or not last_time:
                    continue
                if flds[7]:
                    kmh = float(flds[7])
                elif flds[5]:
                    kmh = float(flds[5]) * KNOTS_TO_KMH
                else:
                    kmh = np.nan
                rows.append({'time_str': last_time, 'source': 'VTG',
                             'speed_kmh': kmh,
                             'track_deg': float(flds[1]) if flds[1] else np.nan})
    return pd.DataFrame(rows, columns=['time_str', 'source', 'speed_kmh', 'track_deg'])


def velocity_per_epoch(vel_df):
    """One row per epoch, preferring RMC over VTG when both are present."""
    if vel_df.empty:
        return vel_df
    ranked = vel_df.assign(_rank=(vel_df.source != 'RMC').astype(int))
    ranked = ranked.dropna(subset=['speed_kmh'])
    out = (ranked.sort_values('_rank', kind='stable')
           .groupby('time_str', sort=False).first().reset_index())
    order = {t: i for i, t in enumerate(dict.fromkeys(vel_df.time_str))}
    out = out.sort_values('time_str', key=lambda c: c.map(order)).reset_index(drop=True)
    return out.drop(columns='_rank')


def analyze(path, start_t, lat0, lon0, out_dir=None):
    """Run the full TTFF/CEP analysis on an NMEA log and save outputs.

    Writes summary_notes.txt and the PNG plots into ``out_dir`` (defaults
    to the log file's directory) and returns the summary text.
    """
    if not path:
        raise ValueError("Select a NMEA log file.")
    if out_dir is None:
        out_dir = os.path.dirname(path) or '.'
    if len(start_t) != 6 or not start_t.isdigit():
        raise ValueError("Enter GNSS Start Time as HHMMSS.")
    datetime.strptime(start_t, '%H%M%S')
    lat0 = float(lat0)
    lon0 = float(lon0)

    # Parse & filter
    df = parse_nmea(path)
    good = df[(df.fix_quality > 0) & df.lat.notna()].copy()
    if good.empty:
        raise ValueError("No valid fixes.")
    first = good.iloc[0]
    ttff = compute_ttff(start_t, first.time_str)

    # Stats
    good['error_m'] = good.apply(lambda r: haversine(lat0, lon0, r.lat, r.lon), axis=1)
    cep50, cep95, rms = compute_error_stats(good.error_m)

    # Build summary string
    summary = (
        f"GNSS Start Time (UTC): {start_t}\n"
        f"Reference (lat,lon): {lat0:.6f}, {lon0:.6f}\n"
        f"First Fix Time (UTC): {first.time_str}\n"
        f"TTFF (s): {ttff:.1f}\n"
        f"Num Fixes: {len(good)}\n"
        f"CEP50: {cep50:.2f} m\n"
        f"CEP95: {cep95:.2f} m\n"
        f"RMS Error: {rms:.2f} m\n\n"
        "Sample Fixes (Time | Sats | HDOP | Err(m)):\n"
    )
    samp = good[['time_str', 'num_sats', 'hdop', 'error_m']].head(20)
    samp.columns = ['Time', 'Sats', 'HDOP', 'Err(m)']
    summary += samp.to_string(index=False, float_format='%.2f')

    # DOP from GSA (PDOP / HDOP / VDOP)
    dop = dop_per_epoch(parse_gsa(path))
    if not dop.empty:
        summary += (
            "\n\nDOP from GSA (mean / max):\n"
            f"PDOP: {dop.pdop.mean():.2f} / {dop.pdop.max():.2f}\n"
            f"HDOP: {dop.hdop.mean():.2f} / {dop.hdop.max():.2f}\n"
            f"VDOP: {dop.vdop.mean():.2f} / {dop.vdop.max():.2f}\n"
        )
        fig, ax = plt.subplots(figsize=(6,4))
        dop_times = dop.time_str.astype(int)
        for col, lbl in (('pdop', 'PDOP'), ('hdop', 'HDOP'), ('vdop', 'VDOP')):
            ax.plot(dop_times, dop[col], '-o', markersize=3, label=lbl)
        ax.set(title="Dilution of Precision vs Time (GSA)",
               xlabel="UTC HHMMSS", ylabel="DOP")
        ax.grid()
        ax.legend(fontsize=8)
        fig.savefig(os.path.join(out_dir, 'dop_vs_time.png'))
    # Per-satellite SNR from GSV
    snr = snr_per_satellite(parse_gsv(path))
    if not snr.empty:
        summary += (
            "\n\nSNR from GSV (C/N0, dB-Hz):\n"
            f"Satellites tracked: {len(snr)}\n"
            f"Mean SNR: {snr.mean_snr.mean():.1f}  "
            f"Best: {snr.max_snr.max():.0f}\n"
        )
        labels = [f"{c[:3]} {p}" for c, p in zip(snr.constellation, snr.prn)]
        fig, ax = plt.subplots(figsize=(max(5, 0.35 * len(snr) + 2), 4))
        ax.bar(range(len(snr)), snr.mean_snr, edgecolor='k', alpha=0.7, label='Mean')
        ax.scatter(range(len(snr)), snr.max_snr, color='red', marker='_', s=120,
                   label='Max', zorder=3)
        ax.set_xticks(range(len(snr)))
        ax.set_xticklabels(labels, rotation=90, fontsize=7)
        ax.set(title="SNR per Satellite (GSV)", xlabel="Satellite",
               ylabel="C/N0 (dB-Hz)")
        ax.grid(axis='y')
        ax.legend(fontsize=8)
        fig.savefig(os.path.join(out_dir, 'snr_per_satellite.png'), bbox_inches='tight')
        plt.close(fig)

    # Save summary to .txt
    note_file = os.path.join(out_dir, 'summary_notes.txt')
    with open(note_file, 'w') as nf:
        nf.write(summary)

    # Histogram (with offset CEP labels)
    fig, ax = plt.subplots(figsize=(5,4))
    ax.hist(good.error_m, bins=15, edgecolor='k', alpha=0.7)
    ax.axvline(cep50, color='blue', ls='--')
    ax.axvline(cep95, color='green', ls='--')
    ax.set(title="Horizontal Position Error Histogram",
           xlabel="Error (m)", ylabel="Count")
    y_max = ax.get_ylim()[1]
    ax.text(cep50, y_max*0.9, f"CEP50\n{cep50:.2f} m",
            ha='right', va='bottom', color='blue',
            backgroundcolor='white', fontsize=8)
    ax.text(cep95, y_max*0.9, f"CEP95\n{cep95:.2f} m",
            ha='left', va='bottom', color='green',
            backgroundcolor='white', fontsize=8)
    fig.savefig(os.path.join(out_dir, 'error_histogram.png'))
    plt.close(fig)

    # ENU Scatter
    R = 6371000.0
    lat0r = math.radians(lat0)
    m_lat = math.pi/180 * R
    m_lon = math.pi/180 * R * math.cos(lat0r)
    east = (good.lon - lon0) * m_lon
    north = (good.lat - lat0) * m_lat
    fig, ax = plt.subplots(figsize=(5,5))
    ax.scatter(east, north, s=10, alpha=0.6, label='Fixes')
    angles = np.linspace(0, 2*np.pi, 200)
    for radius, color, lbl in [
        (cep50, 'blue', f"CEP50 {cep50:.2f}m"),
        (cep95, 'green', f"CEP95 {cep95:.2f}m")
    ]:
        dx = radius * np.cos(angles)
        dy = radius * np.sin(angles)
        ax.plot(dx, dy, '--', color=color, label=lbl)
    ax.scatter(0, 0, c='red', marker='x', s=80, label='Reference')
    ax.set(title="Local ENU Scatter with CEP₅₀/₉₅",
           xlabel="Eastward Offset (m)", ylabel="Northward Offset (m)")
    ax.grid()
    ax.set_aspect('equal', 'box')
    m_lim = max(np.abs(east).max(), np.abs(north).max(), cep95) * 1.1
    if not m_lim > 0:
        m_lim = 1.0
    ax.set_xlim(-m_lim, m_lim)
    ax.set_ylim(-m_lim, m_lim)
    ax.legend(loc='upper left', bbox_to_anchor=(1.02,1), borderaxespad=0, fontsize=8)
    fig.savefig(os.path.join(out_dir, 'scatter_with_cep.png'), bbox_inches='tight')
    plt.close(fig)

    # Error vs HDOP
    fig, ax = plt.subplots(figsize=(5,4))
    ax.scatter(good.hdop, good.error_m, alpha=0.6)
    ax.set(title="Horizontal Error vs HDOP", xlabel="HDOP", ylabel="Error (m)")
    ax.grid()
    fig.savefig(os.path.join(out_dir, 'error_vs_hdop.png'))
    plt.close(fig)

    # Satellites vs Time
    fig, ax = plt.subplots(figsize=(5,4))
    times = good.time_str.astype(int)
    ax.plot(times, good.num_sats, '-o', markersize=3)
    ax.set(title="Satellites Tracked vs Time",
           xlabel="UTC HHMMSS", ylabel="Sat Count")
    ax.grid()
    fig.savefig(os.path.join(out_dir, 'sats_vs_time.png'))
    plt.close(fig)

    # Velocity from RMC / VTG
    vel = velocity_per_epoch(parse_velocity(path))
    if not vel.empty:
        fig, ax = plt.subplots(figsize=(6,4))
        vel_times = vel.time_str.astype(int)
        ax.plot(vel_times, vel.speed_kmh, '-o', markersize=3, color='tab:blue',
                label='Speed')
        ax.set(title="Speed & Track vs Time (RMC/VTG)",
               xlabel="UTC HHMMSS", ylabel="Speed (km/h)")
        ax.grid()
        ax2 = ax.twinx()
        ax2.plot(vel_times, vel.track_deg, '.', color='tab:orange', label='Track')
        ax2.set_ylabel("Track, true (deg)")
        ax2.set_ylim(0, 360)
        fig.legend(loc='upper right', fontsize=8)
        fig.savefig(os.path.join(out_dir, 'velocity_vs_time.png'), bbox_inches='tight')
        plt.close(fig)
        speed_summary = (
            "\n\nVelocity from RMC/VTG:\n"
            f"Mean speed: {vel.speed_kmh.mean():.2f} km/h\n"
            f"Max speed: {vel.speed_kmh.max():.2f} km/h\n"
        )
        summary += speed_summary
        with open(note_file, 'a') as nf:
            nf.write(speed_summary)

    return summary


def main():
    """Build and run the Tkinter GUI."""
    import tkinter as tk
    from tkinter import filedialog, messagebox

    def run_analysis():
        try:
            path = file_path_var.get().strip()
            summary = analyze(path, start_time_var.get().strip(),
                              ref_lat_var.get(), ref_lon_var.get())
            summary_text.delete('1.0', tk.END)
            summary_text.insert(tk.END, summary)
            out_dir = os.path.dirname(path) or '.'
            messagebox.showinfo("Done",
                                f"Plots and notes saved to: {out_dir}")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    # --- GUI setup ---
    root = tk.Tk()
    root.title("GNSS Analysis GUI")

    tk.Label(root, text="NMEA Log File:").grid(row=0, column=0, sticky='e')
    file_path_var = tk.StringVar()
    tk.Entry(root, textvariable=file_path_var, width=40).grid(row=0, column=1)
    tk.Button(root, text="Browse…", command=lambda: file_path_var.set(filedialog.askopenfilename())).grid(row=0, column=2)

    tk.Label(root, text="Start Time (HHMMSS):").grid(row=1, column=0, sticky='e')
    start_time_var = tk.StringVar()
    tk.Entry(root, textvariable=start_time_var).grid(row=1, column=1, columnspan=2, sticky='we')

    tk.Label(root, text="Ref Latitude:").grid(row=2, column=0, sticky='e')
    ref_lat_var = tk.StringVar(); tk.Entry(root, textvariable=ref_lat_var).grid(row=2, column=1)
    tk.Label(root, text="Ref Longitude:").grid(row=2, column=2, sticky='e')
    ref_lon_var = tk.StringVar(); tk.Entry(root, textvariable=ref_lon_var).grid(row=2, column=3)

    tk.Button(root, text="Run Analysis", command=run_analysis).grid(row=3, column=0, columnspan=4, pady=10)

    summary_text = tk.Text(root, height=20, width=75)
    summary_text.grid(row=4, column=0, columnspan=4, padx=5, pady=5)

    root.mainloop()


if __name__ == "__main__":
    main()
