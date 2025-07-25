# GNSS Logger & Analysis Toolkit

A comprehensive **Python** suite for automated GNSS testing, logging, and performance analysis. Designed for Telit-based modules with standard NMEA output, this toolkit provides:

* \`\`
  Reset & power-on the GNSS engine, enable NMEA sentences, and capture raw NMEA logs.
* \`\`
  Command-line parser & analyzer: computes TTFF, CEP₅₀/₉₅, RMS error; generates industry-standard plots.
* \`\`
  Tkinter GUI front-end for one-click analysis and text-summary export.

---

## 📋 Table of Contents

1. [Prerequisites](#-prerequisites)
2. [Installation](#-installation)
3. [Usage](#-usage)

   * [1. GNSS Logger](#1-gnss-logger-gnss_loggerpy)
   * [2. NMEA Analysis](#2-nmea-analysis-gnss_nmea_analysispy)
   * [3. Analysis GUI](#3-analysis-gui-gnss_analysis_guipy)
4. [Metrics & Plots](#-metrics--plots)
5. [Customization](#-customization)
6. [License](#-license)

---

## 📋 Prerequisites

* **Python 3.7+**
* **pip** (Python package manager)
* **System packages (Linux)**:

  ```bash
  ```

i sudo apt-get install python3-tk  # if Tkinter is missing

````

---
## 🔧 Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/yourusername/gnss-toolkit.git
   cd gnss-toolkit
````

2. **Install dependencies**

   ```bash
   pip install pyserial pandas numpy matplotlib
   ```

---

## 🛠 Usage

### 1. GNSS Logger (`gnss_logger.py`)

Capture raw NMEA sentences from a Telit GNSS module:

```bash
python gnss_logger.py <COM_PORT> [--mode MODE] [--duration SECONDS] [--output FILE]
```

* \`\`: e.g. `COM4` (Windows) or `/dev/ttyUSB0` (Linux/macOS)
* \`\`: `cold` (default) | `warm` | `hot`
* \`\`: seconds to log (default: `900`)
* \`\`: filename for NMEA log (default: `nmea_capture.txt`)

**Console Output**:

* AT command responses & “OK” messages
* `# START HHMMSS` header for session timestamp
* 🎯 First-fix notification
* Live NMEA sentences

**Output**:

* Raw NMEA log file containing only NMEA sentences and a header

---

### 2. NMEA Analysis (`gnss_nmea_analysis.py`)

Parse an NMEA log, compute performance metrics, and generate plots:

```bash
python gnss_nmea_analysis.py \
  --nmea-file path/to/nmea_capture.txt \
  --start-time HHMMSS \
  --ref-lat <latitude> \
  --ref-lon <longitude>
```

* \`\`: log from `gnss_logger.py`
* \`\`: UTC start time used when logging (HHMMSS)
* `, `: survey-grade reference coordinates

**Generated Files** (same folder as `--nmea-file`):

* \`\`  – CSV summary of key metrics
* \`\`  – histogram with CEP₅₀/₉₅ annotations
* \`\` – ENU scatter plot with CEP circles
* \`\`  – HDOP vs horizontal error
* \`\`  – number of satellites vs UTC time

---

### 3. Analysis GUI (`gnss_analysis_gui.py`)

Tkinter GUI wrapping the same analysis logic with summary export:

```bash
python gnss_analysis_gui.py
```

1. **Browse** to select your NMEA log file
2. Enter **Start Time (HHMMSS)**
3. Enter **Reference Latitude & Longitude**
4. Click **Run Analysis**

**Outputs** (next to your log file):

* \`\`  – plaintext report of TTFF, CEP, RMS, sample fixes
* All four PNG plots (as above)

---

## 📈 Metrics & Plots

* **TTFF (s)**: Time-to-first-fix after GNSS power-on
* **CEP₅₀ / CEP₉₅ (m)**: Radii containing 50% / 95% of fixes
* **RMS Error (m)**: Root-mean-square horizontal error
* **Error Histogram**: Distribution of error with CEP markers
* **ENU Scatter**: East/North offsets in meters with CEP rings
* **HDOP vs Error**: Correlation between HDOP and observed error
* **Satellites vs Time**: Satellite count over the session

---

## ⚙️ Customization

* Modify histogram bins, plot styles, or add new NMEA sentence support
* Adjust CLI flags (e.g., logging duration, output paths)
* Integrate additional metrics (e.g., HDOP drift over time)

---

## ⚖️ License

This project is licensed under the **GNU General Public License v3.0**. See [LICENSE](LICENSE) for full details.
