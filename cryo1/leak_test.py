#!/usr/bin/env python3
"""
Leak Test Dashboard — designed for 1920×1080
2x pressure sensors (ADS1115) + 3x MAX31865 RTD + MAX31855 Type K

pip install adafruit-circuitpython-max31855 adafruit-circuitpython-max31865 matplotlib pillow
"""
import time
import csv
import os
import io
import collections
import board
import digitalio
import busio
import adafruit_max31855
import adafruit_max31865
from adafruit_ads1x15 import ADS1115, AnalogIn, ads1x15
import tkinter as tk
from PIL import Image, ImageTk
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# =============================================================================
# USER-DEFINED PARAMETERS
# =============================================================================
INITIAL_PRESSURE_DELAY_S = 300          # seconds before recording initial pressure (5 min)
LEAK_THRESHOLD_PSIG_MIN  = 0.02         # PSIG/min — displayed next to leak rate

# =============================================================================
# PRESSURE CONVERSION CONSTANTS
# =============================================================================
V_MIN = 0.5     # Volts
V_MAX = 4.5     # Volts
P_MIN = -14.5   # PSIG
P_MAX = 30.0    # PSIG

# =============================================================================
# TEMPERATURE THRESHOLDS
# =============================================================================
T_SAFE   = 65.0
T_DANGER = 88.0

# =============================================================================
# HISTORY / PLOT PARAMETERS
# =============================================================================
PLOT_HISTORY_S = 7200           # 2 hours of history in RAM
SENSOR_HZ      = 1              # 1 Hz target
PLOT_MAXLEN    = PLOT_HISTORY_S * SENSOR_HZ
PLOT_UPDATE_MS = 2000           # redraw plots every 2 s

# Plot sized to leave room for the UI rows above on a 1080p screen.
# Header ~50 px + UI rows ~380 px + padding ~30 px → ~460 px used.
# Remaining for plots: 1080 - 460 = ~620 px total → 300 px per plot.
PLOT_W_PX = 1100
PLOT_H_PX = 290                 # height per individual pressure plot

# =============================================================================
# LEAK RATE
# =============================================================================
LEAK_WINDOW_S = 60              # sliding window for linear regression (seconds)

# =============================================================================
# CSV
# =============================================================================
CSV_FILE = "leak_test.csv"
if not os.path.exists(CSV_FILE):
    with open(CSV_FILE, "w", newline="") as f:
        csv.writer(f).writerow([
            "timestamp", "elapsed_s",
            "typeK_C",
            "rtd1_C", "rtd2_C", "rtd3_C",
            "pressure1_psig", "pressure2_psig",
        ])

# =============================================================================
# HARDWARE SETUP
# =============================================================================
spi = board.SPI()

cs_k = digitalio.DigitalInOut(board.D5)
sensor_k = adafruit_max31855.MAX31855(spi, cs_k)

cs1 = digitalio.DigitalInOut(board.D6)
sensor1 = adafruit_max31865.MAX31865(spi, cs1, wires=4, rtd_nominal=100.02, ref_resistor=430)

cs2 = digitalio.DigitalInOut(board.D12)
sensor2 = adafruit_max31865.MAX31865(spi, cs2, wires=4, rtd_nominal=99.99,  ref_resistor=430)

cs3 = digitalio.DigitalInOut(board.D13)
sensor3 = adafruit_max31865.MAX31865(spi, cs3, wires=4, rtd_nominal=100.01, ref_resistor=430)

try:
    i2c      = busio.I2C(board.SCL, board.SDA)
    ads      = ADS1115(i2c)
    ads.gain = 1
    channel0 = AnalogIn(ads, ads1x15.Pin.A0)
    channel1 = AnalogIn(ads, ads1x15.Pin.A1)
    print("ADS1115 ready.\n")
except Exception as e:
    print(f"ERROR: Could not initialise ADS1115.\n  → {e}")
    raise SystemExit(1)

# =============================================================================
# HELPERS
# =============================================================================
def voltage_to_psi(voltage):
    return (voltage - V_MIN) / (V_MAX - V_MIN) * (P_MAX - P_MIN) + P_MIN

def temp_color(temp):
    if temp is None:         return "#FF0000"
    if temp < T_SAFE:        return "#00CC00"
    if temp <= T_DANGER:     return "#FF8000"
    return "#FF0000"

def fmt(val, decimals=2):
    return "---" if val is None else f"{val:.{decimals}f}"

# =============================================================================
# STATE
# =============================================================================
t_start          = None
initial_p1       = None
initial_p2       = None
initial_recorded = False
time_from_init   = None
leak_rate_p1     = None
leak_rate_p2     = None

# History buffers
hist_time = collections.deque(maxlen=PLOT_MAXLEN)
hist_p1   = collections.deque(maxlen=PLOT_MAXLEN)
hist_p2   = collections.deque(maxlen=PLOT_MAXLEN)

# =============================================================================
# MATPLOTLIB FIGURE — two stacked pressure plots
# =============================================================================
plt.style.use("dark_background")
fig, (ax_p1, ax_p2) = plt.subplots(
    2, 1,
    figsize=(PLOT_W_PX / 100, (PLOT_H_PX * 2) / 100),
    dpi=100,
    facecolor="#0d0d0d",
)
fig.subplots_adjust(left=0.08, right=0.97, top=0.94, bottom=0.10, hspace=0.55)

for ax, title in ((ax_p1, "Pressure 1 (PSIG)"), (ax_p2, "Pressure 2 (PSIG)")):
    ax.set_facecolor("#1a1a1a")
    ax.tick_params(colors="#888888", labelsize=8)
    for spine in ax.spines.values():
        spine.set_edgecolor("#333333")
    ax.set_title(title, color="#AAAAAA", fontsize=10, pad=3)
    ax.set_ylabel("PSIG", color="#AAAAAA", fontsize=9)
    ax.set_xlabel("Time since start (s)", color="#AAAAAA", fontsize=9)

line_p1, = ax_p1.plot([], [], color="#00BFFF", linewidth=1.4)
line_p2, = ax_p2.plot([], [], color="#FF6347", linewidth=1.4)

# Vertical dashed line marking when initial pressure was recorded
vline_p1 = ax_p1.axvline(x=0, color="#FFD700", linewidth=1.0,
                          linestyle="--", visible=False, label="Initial P")
vline_p2 = ax_p2.axvline(x=0, color="#FFD700", linewidth=1.0,
                          linestyle="--", visible=False, label="Initial P")
ax_p1.legend(loc="upper right", fontsize=7, framealpha=0.3)
ax_p2.legend(loc="upper right", fontsize=7, framealpha=0.3)


def redraw_plot():
    times = list(hist_time)
    if len(times) < 2:
        root.after(PLOT_UPDATE_MS, redraw_plot)
        return

    line_p1.set_data(times, list(hist_p1))
    ax_p1.relim(); ax_p1.autoscale_view()

    line_p2.set_data(times, list(hist_p2))
    ax_p2.relim(); ax_p2.autoscale_view()

    if initial_recorded and time_from_init is not None:
        init_t = times[-1] - time_from_init
        vline_p1.set_xdata([init_t, init_t]); vline_p1.set_visible(True)
        vline_p2.set_xdata([init_t, init_t]); vline_p2.set_visible(True)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=100, facecolor=fig.get_facecolor())
    buf.seek(0)
    img   = Image.open(buf).copy()
    buf.close()
    photo = ImageTk.PhotoImage(img)

    plot_canvas.config(width=photo.width(), height=photo.height())
    plot_canvas.create_image(0, 0, anchor="nw", image=photo)
    plot_canvas.image = photo

    root.after(PLOT_UPDATE_MS, redraw_plot)

# =============================================================================
# WINDOW LAYOUT
# =============================================================================
BG       = "black"
FG_DIM   = "#555555"
FG_LABEL = "#AAAAAA"
FG_WHITE = "white"
FG_GREEN = "#00CC00"
SEP_COL  = "#333333"

root = tk.Tk()
root.title("Leak Test Monitor")
root.configure(bg=BG)
root.resizable(False, False)

# ── Header ────────────────────────────────────────────────────────────────────
hdr = tk.Frame(root, bg="#111111")
hdr.pack(fill="x")
tk.Label(hdr, text="LEAK TEST MONITOR", font=("Helvetica", 18, "bold"),
         fg=FG_WHITE, bg="#111111").pack(side="left", padx=24, pady=4)
clock_lbl = tk.Label(hdr, text="", font=("Courier New", 13),
                     fg=FG_DIM, bg="#111111")
clock_lbl.pack(side="right", padx=24)

# ── Body: left_col (pressures + plots) | right_col (temperatures) ─────────────
body = tk.Frame(root, bg=BG)
body.pack(fill="both", expand=True, padx=16, pady=8)

left_col = tk.Frame(body, bg=BG)
left_col.pack(side="left", fill="both", expand=False, padx=(0, 24))

right_col = tk.Frame(body, bg=BG)
right_col.pack(side="left", fill="y", anchor="n", padx=(0, 0))

# =============================================================================
# HELPER WIDGETS
# =============================================================================
def hsep(parent, pady=(3, 3)):
    tk.Frame(parent, bg=SEP_COL, height=1).pack(fill="x", pady=pady)

def section_hdr(parent, text):
    tk.Label(parent, text=text, font=("Helvetica", 13, "bold"),
             fg="#AAAAAA", bg=BG).pack(anchor="w", pady=(2, 2))
    hsep(parent, pady=(0, 4))

def info_row(parent, label_text, value_text="---", value_font=("Courier New", 18, "bold")):
    """Static label + dynamic value. Returns the value Label widget."""
    row = tk.Frame(parent, bg=BG)
    row.pack(fill="x", pady=1)
    tk.Label(row, text=label_text, font=("Helvetica", 11),
             fg=FG_LABEL, bg=BG, width=24, anchor="w").pack(side="left")
    val = tk.Label(row, text=value_text, font=value_font,
                   fg=FG_WHITE, bg=BG, anchor="w")
    val.pack(side="left")
    return val

def leak_row(parent, label_text):
    """
    Leak rate row: label | value | threshold note — all on one line.
    Returns the value Label widget.
    """
    row = tk.Frame(parent, bg=BG)
    row.pack(fill="x", pady=1)
    tk.Label(row, text=label_text, font=("Helvetica", 11),
             fg=FG_LABEL, bg=BG, width=24, anchor="w").pack(side="left")
    val = tk.Label(row, text="---", font=("Courier New", 18, "bold"),
                   fg=FG_WHITE, bg=BG, anchor="w")
    val.pack(side="left")
    tk.Label(row, text=f"  Threshold = {LEAK_THRESHOLD_PSIG_MIN} PSIG/min",
             font=("Helvetica", 10), fg=FG_DIM, bg=BG).pack(side="left", padx=(12, 0))
    return val

# =============================================================================
# LEFT COLUMN — SENSOR 1
# =============================================================================
section_hdr(left_col, "SENSOR 1")

init_p1_lbl = info_row(left_col, "Initial Pressure 1")

# P1 current row: label | big value | elapsed time
p1_row = tk.Frame(left_col, bg=BG)
p1_row.pack(fill="x", pady=0)
tk.Label(p1_row, text="P1  (current)", font=("Helvetica", 11),
         fg=FG_LABEL, bg=BG, width=24, anchor="w").pack(side="left")
p1_lbl = tk.Label(p1_row, text="---", font=("Courier New", 38, "bold"),
                  fg=FG_GREEN, bg=BG)
p1_lbl.pack(side="left")
time_p1_lbl = tk.Label(p1_row, text="", font=("Helvetica", 10),
                        fg=FG_DIM, bg=BG)
time_p1_lbl.pack(side="left", padx=(14, 0))

leak_p1_lbl = leak_row(left_col, "Leak rate P1")

hsep(left_col, pady=(8, 8))

# =============================================================================
# LEFT COLUMN — SENSOR 2
# =============================================================================
section_hdr(left_col, "SENSOR 2")

init_p2_lbl = info_row(left_col, "Initial Pressure 2")

p2_row = tk.Frame(left_col, bg=BG)
p2_row.pack(fill="x", pady=0)
tk.Label(p2_row, text="P2  (current)", font=("Helvetica", 11),
         fg=FG_LABEL, bg=BG, width=24, anchor="w").pack(side="left")
p2_lbl = tk.Label(p2_row, text="---", font=("Courier New", 38, "bold"),
                  fg=FG_GREEN, bg=BG)
p2_lbl.pack(side="left")
time_p2_lbl = tk.Label(p2_row, text="", font=("Helvetica", 10),
                        fg=FG_DIM, bg=BG)
time_p2_lbl.pack(side="left", padx=(14, 0))

leak_p2_lbl = leak_row(left_col, "Leak rate P2")

hsep(left_col, pady=(8, 4))

# Status / countdown
status_lbl = tk.Label(left_col, text="Waiting for 5 min warm-up...",
                       font=("Helvetica", 12, "bold"), fg="#888888", bg=BG)
status_lbl.pack(anchor="w", pady=(2, 4))

# =============================================================================
# LEFT COLUMN — PLOTS (below pressures)
# =============================================================================
hsep(left_col, pady=(4, 4))
tk.Label(left_col, text="PRESSURE HISTORY", font=("Helvetica", 12, "bold"),
         fg=FG_DIM, bg=BG).pack(anchor="w", pady=(0, 4))

plot_canvas = tk.Canvas(left_col, width=PLOT_W_PX, height=PLOT_H_PX * 2,
                         bg="#0d0d0d", highlightthickness=0)
plot_canvas.pack(anchor="w")

# =============================================================================
# RIGHT COLUMN — TEMPERATURES
# =============================================================================
section_hdr(right_col, "TEMPERATURES")

def temp_row(parent, label):
    row = tk.Frame(parent, bg=BG)
    row.pack(fill="x", pady=5)
    tk.Label(row, text=label, font=("Helvetica", 11),
             fg=FG_LABEL, bg=BG, width=14, anchor="w").pack(side="left")
    val = tk.Label(row, text="---", font=("Courier New", 20, "bold"),
                   fg=FG_WHITE, bg=BG)
    val.pack(side="left")
    return val

typek_lbl = temp_row(right_col, "Type K")
rtd1_lbl  = temp_row(right_col, "RTD 1  (D6)")
rtd2_lbl  = temp_row(right_col, "RTD 2  (D12)")
rtd3_lbl  = temp_row(right_col, "RTD 3  (D13)")

# =============================================================================
# LEAK RATE CALCULATION  (linear regression, called every 60 s)
# =============================================================================
def compute_leak_rates():
    """
    Fits a least-squares line through the last LEAK_WINDOW_S pressure samples.
    Slope (PSIG/s) × 60 = leak rate in PSIG/min.
    A negative value means pressure is dropping (leak).
    """
    global leak_rate_p1, leak_rate_p2

    n = min(len(hist_time), LEAK_WINDOW_S)
    if n < 2:
        root.after(60_000, compute_leak_rates)
        return

    times = list(hist_time)[-n:]
    p1s   = list(hist_p1)[-n:]
    p2s   = list(hist_p2)[-n:]

    # Remove NaN samples (nan != nan is True in IEEE 754)
    pairs1 = [(t, p) for t, p in zip(times, p1s) if p == p]
    pairs2 = [(t, p) for t, p in zip(times, p2s) if p == p]

    def slope_psig_per_min(pairs):
        """Ordinary least-squares slope, converted from PSIG/s to PSIG/min."""
        if len(pairs) < 2:
            return None
        n_  = len(pairs)
        ts  = [pair[0] for pair in pairs]
        ps  = [pair[1] for pair in pairs]
        t_m = sum(ts) / n_
        p_m = sum(ps) / n_
        num = sum((t - t_m) * (p - p_m) for t, p in zip(ts, ps))
        den = sum((t - t_m) ** 2 for t in ts)
        if den == 0:
            return None
        return (num / den) * 60.0      # PSIG/s → PSIG/min

    leak_rate_p1 = slope_psig_per_min(pairs1)
    leak_rate_p2 = slope_psig_per_min(pairs2)

    def leak_color(rate):
        """Green if below threshold, orange near threshold, red above."""
        if rate is None:
            return FG_WHITE
        if abs(rate) <= LEAK_THRESHOLD_PSIG_MIN:
            return FG_GREEN
        if abs(rate) <= LEAK_THRESHOLD_PSIG_MIN * 2:
            return "#FF8000"
        return "#FF0000"

    if leak_rate_p1 is not None:
        leak_p1_lbl.config(text=f"{leak_rate_p1:+.4f} PSIG/min",
                           fg=leak_color(leak_rate_p1))
    if leak_rate_p2 is not None:
        leak_p2_lbl.config(text=f"{leak_rate_p2:+.4f} PSIG/min",
                           fg=leak_color(leak_rate_p2))

    root.after(60_000, compute_leak_rates)

# =============================================================================
# MAIN UPDATE LOOP  (1 Hz target)
# =============================================================================
def update():
    global t_start, initial_p1, initial_p2, initial_recorded, time_from_init

    _t0 = time.perf_counter()

    if t_start is None:
        t_start = _t0
    elapsed = _t0 - t_start

    now_str = time.strftime("%Y-%m-%d %H:%M:%S")
    clock_lbl.config(text=now_str)

    # ── Type K ───────────────────────────────────────────────────────────────
    try:    tk_c = sensor_k.temperature
    except: tk_c = None
    typek_lbl.config(text=f"{fmt(tk_c, 1)} °C", fg=temp_color(tk_c))

    # ── RTDs ─────────────────────────────────────────────────────────────────
    try:    t1 = sensor1.temperature
    except: t1 = None
    try:    t2 = sensor2.temperature
    except: t2 = None
    try:    t3 = sensor3.temperature
    except: t3 = None

    rtd1_lbl.config(text=f"{fmt(t1, 1)} °C", fg=temp_color(t1))
    rtd2_lbl.config(text=f"{fmt(t2, 1)} °C", fg=temp_color(t2))
    rtd3_lbl.config(text=f"{fmt(t3, 1)} °C", fg=temp_color(t3))

    # ── Pressures ─────────────────────────────────────────────────────────────
    try:    p1 = voltage_to_psi(channel0.voltage)
    except: p1 = None
    try:    p2 = voltage_to_psi(channel1.voltage)
    except: p2 = None

    p1_lbl.config(text=f"{fmt(p1)} PSIG",
                  fg=FG_GREEN if p1 is not None else "#FF0000")
    p2_lbl.config(text=f"{fmt(p2)} PSIG",
                  fg=FG_GREEN if p2 is not None else "#FF0000")

    # ── Initial pressure (recorded once, after INITIAL_PRESSURE_DELAY_S) ─────
    if not initial_recorded and elapsed >= INITIAL_PRESSURE_DELAY_S:
        if p1 is not None and p2 is not None:
            initial_p1       = p1
            initial_p2       = p2
            initial_recorded = True
            time_from_init   = 0.0
            init_p1_lbl.config(text=f"{initial_p1:.2f} PSIG")
            init_p2_lbl.config(text=f"{initial_p2:.2f} PSIG")
            status_lbl.config(text="✔  Initial pressures recorded", fg=FG_GREEN)
            print(f"[{now_str}]  ★ Initial P1={initial_p1:.4f}  P2={initial_p2:.4f} PSIG")

    # ── Time from initial ─────────────────────────────────────────────────────
    if initial_recorded:
        time_from_init = elapsed - INITIAL_PRESSURE_DELAY_S
        h = int(time_from_init // 3600)
        m = int((time_from_init % 3600) // 60)
        s = int(time_from_init % 60)
        tstr = f"  +{h:02d}:{m:02d}:{s:02d} from initial"
        time_p1_lbl.config(text=tstr)
        time_p2_lbl.config(text=tstr)
    else:
        remaining = max(0, INITIAL_PRESSURE_DELAY_S - elapsed)
        m = int(remaining // 60)
        s = int(remaining % 60)
        status_lbl.config(
            text=f"Initial pressure in  {m:02d}:{s:02d} ...",
            fg="#888888")

    # ── History buffers ───────────────────────────────────────────────────────
    hist_time.append(elapsed)
    hist_p1.append(p1 if p1 is not None else float("nan"))
    hist_p2.append(p2 if p2 is not None else float("nan"))

    # ── Console ───────────────────────────────────────────────────────────────
    print(f"[{now_str}]  t={elapsed:.0f}s  "
          f"P1={fmt(p1)} P2={fmt(p2)} PSIG  "
          f"RTD1={fmt(t1,1)} RTD2={fmt(t2,1)} RTD3={fmt(t3,1)} °C")

    # ── CSV ───────────────────────────────────────────────────────────────────
    with open(CSV_FILE, "a", newline="") as f:
        csv.writer(f).writerow([
            now_str,
            f"{elapsed:.1f}",
            f"{tk_c:.4f}" if tk_c is not None else "",
            f"{t1:.4f}"   if t1   is not None else "",
            f"{t2:.4f}"   if t2   is not None else "",
            f"{t3:.4f}"   if t3   is not None else "",
            f"{p1:.4f}"   if p1   is not None else "",
            f"{p2:.4f}"   if p2   is not None else "",
        ])

    # ── Schedule next call (compensates for execution time) ──────────────────
    _elapsed_ms = int((time.perf_counter() - _t0) * 1000)
    _wait_ms    = max(1, 1000 - _elapsed_ms)
    root.after(_wait_ms, update)

# =============================================================================
# START
# =============================================================================
update()
root.after(PLOT_UPDATE_MS, redraw_plot)
root.after(60_000, compute_leak_rates)
root.mainloop()