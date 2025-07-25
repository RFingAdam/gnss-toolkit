#!/usr/bin/env python3
"""
gnss_analysis_gui.py

Tkinter GUI for GNSS TTFF & CEP analysis from NMEA logs.

All outputs are saved next to the selected NMEA file:
  • error_histogram.png
  • scatter_with_cep.png
  • error_vs_hdop.png
  • sats_vs_time.png
  • summary_notes.txt        <- added

Distances computed via the Haversine formula on a WGS-84 sphere
(Earth radius ≈ 6 371 000 m), but for the plan view we use a
flat‐Earth ENU approximation to plot in meters.
"""

import os
import tkinter as tk
from tkinter import filedialog, messagebox
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


def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def run_analysis():
    try:
        # Inputs
        path = file_path_var.get().strip()
        if not path:
            raise ValueError("Select a NMEA log file.")
        out_dir = os.path.dirname(path) or '.'
        start_t = start_time_var.get().strip()
        if len(start_t) != 6 or not start_t.isdigit():
            raise ValueError("Enter GNSS Start Time as HHMMSS.")
        dt_start = datetime.strptime(start_t, '%H%M%S')
        lat0 = float(ref_lat_var.get())
        lon0 = float(ref_lon_var.get())

        # Parse & filter
        df = parse_nmea(path)
        good = df[(df.fix_quality > 0) & df.lat.notna()]
        if good.empty:
            raise ValueError("No valid fixes.")
        first = good.iloc[0]
        dt_fix = datetime.strptime(first.time_str, '%H%M%S')
        ttff = (dt_fix - dt_start).total_seconds()
        if ttff < 0:
            ttff += 86400

        # Stats
        good['error_m'] = good.apply(lambda r: haversine(lat0, lon0, r.lat, r.lon), axis=1)
        cep50 = np.percentile(good.error_m, 50)
        cep95 = np.percentile(good.error_m, 95)
        rms = math.sqrt((good.error_m**2).mean())

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

        # Display in GUI text
        summary_text.delete('1.0', tk.END)
        summary_text.insert(tk.END, summary)

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
