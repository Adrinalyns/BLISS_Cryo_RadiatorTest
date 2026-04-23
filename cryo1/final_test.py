#!/usr/bin/env python3
"""
Thermal & Pressure Dashboard
MAX31855 (Type K) + 3x MAX31865 (PT100 RTD) + 2x pressure sensors
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
from PIL import Image, ImageTk          # pip install pillow
import matplotlib
matplotlib.use("Agg")                   # non-interactive backend — no second GUI loop
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import datetime

# =============================================================================
# USER-DEFINED PARAMETERS — set these before running
# =============================================================================
MOTOR_COMMAND        = 1850
POWER_INPUT_W        = 50
MASS_FLOW_RATE_G_MIN = 633.8280 - 0.3091 * MOTOR_COMMAND
C_P                  = 3700.0           # J/(kg·K)

# =============================================================================
# Convert mass flow rate to kg/s
# =============================================================================
MASS_FLOW_RATE = MASS_FLOW_RATE_G_MIN / 60.0 / 1000.0      # kg/s

# =============================================================================
# TEMPERATURE THRESHOLDS
# =============================================================================
T_SAFE   = 65.0
T_DANGER = 88.0

# =============================================================================
# PRESSURE THRESHOLDS
# =============================================================================
P_GREEN_LO  = -7.0
P_GREEN_HI  =  7.0
P_ORANGE_LO = -11.0
P_ORANGE_HI =  22.0

# =============================================================================
# PRESSURE CONVERSION CONSTANTS
# =============================================================================
V_MIN = 0.5     # Volts
V_MAX = 4.5     # Volts
P_MIN = -14.5   # PSIG
P_MAX = 30.0    # PSIG

# =============================================================================
# PLOT HISTORY — 2 hours at 2 Hz = 14 400 points max
# Reduce PLOT_HISTORY_S to save memory on long runs
# =============================================================================
PLOT_HISTORY_S  = 7200          # seconds of history kept in RAM
SENSOR_HZ       = 2             # must match 1000 / root.after interval
PLOT_MAXLEN     = PLOT_HISTORY_S * SENSOR_HZ

PLOT_UPDATE_MS  = 5000          # redraw plot every 5 s

# Plot canvas size (pixels) — keep modest for Pi
PLOT_W_PX = 780
PLOT_H_PX = 520

# =============================================================================
# CSV
# =============================================================================
CSV_FILE = "Results.csv"
if not os.path.exists(CSV_FILE):
    with open(CSV_FILE, "w", newline="") as f:
        csv.writer(f).writerow([
            "timestamp", "typeK_C",
            "rtd1_C", "rtd2_C", "rtd3_C",
            "pressure1", "pressure2",
            "P_in_W", "P_out_W",
        ])

# =============================================================================
# SPI + SENSOR SETUP
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

# =============================================================================
# I2C + PRESSURE SENSORS
# =============================================================================
try:
    i2c  = busio.I2C(board.SCL, board.SDA)
    ads  = ADS1115(i2c)
    ads.gain = 1
    channel0 = AnalogIn(ads, ads1x15.Pin.A0)
    channel1 = AnalogIn(ads, ads1x15.Pin.A1)
    print("ADS1115 ready.\n")
except Exception as e:
    print(f"ERROR: Could not initialise ADS1115.\n  → {e}")
    raise SystemExit(1)


def voltage_to_psi(voltage):
    return (voltage - V_MIN) / (V_MAX - V_MIN) * (P_MAX - P_MIN) + P_MIN

# =============================================================================
# COLOUR HELPERS
# =============================================================================
def temp_color(temp):
    if temp is None:          return "#FF0000"
    if temp < T_SAFE:         return "#00CC00"
    if temp <= T_DANGER:      return "#FF8000"
    return "#FF0000"

def pressure_color(p):
    if p is None:                       return "#FF0000"
    if P_GREEN_LO <= p <= P_GREEN_HI:   return "#00CC00"
    if P_ORANGE_LO <= p <= P_ORANGE_HI: return "#FF8000"
    return "#FF0000"

def fmt(val, decimals=1):
    return "ERR" if val is None else f"{val:.{decimals}f}"

# =============================================================================
# HISTORY BUFFERS  (timestamps + values)
# =============================================================================
hist_time = collections.deque(maxlen=PLOT_MAXLEN)   # datetime objects
hist_t1   = collections.deque(maxlen=PLOT_MAXLEN)
hist_t2   = collections.deque(maxlen=PLOT_MAXLEN)
hist_t3   = collections.deque(maxlen=PLOT_MAXLEN)
hist_pin  = collections.deque(maxlen=PLOT_MAXLEN)
hist_pout = collections.deque(maxlen=PLOT_MAXLEN)

# =============================================================================
# MATPLOTLIB FIGURE  (created once, reused every draw)
# =============================================================================
plt.style.use("dark_background")
fig, (ax_temp, ax_pow) = plt.subplots(
    2, 1,
    figsize=(PLOT_W_PX / 100, PLOT_H_PX / 100),
    dpi=100,
    facecolor="#0d0d0d",
)
fig.subplots_adjust(left=0.10, right=0.97, top=0.93, bottom=0.12, hspace=0.45)

for ax in (ax_temp, ax_pow):
    ax.set_facecolor("#1a1a1a")
    ax.tick_params(colors="#888888", labelsize=8)
    for spine in ax.spines.values():
        spine.set_edgecolor("#333333")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())

ax_temp.set_title("RTD Temperatures", color="#AAAAAA", fontsize=10, pad=4)
ax_temp.set_ylabel("°C", color="#AAAAAA", fontsize=9)

ax_pow.set_title("Power Estimates", color="#AAAAAA", fontsize=10, pad=4)
ax_pow.set_ylabel("W", color="#AAAAAA", fontsize=9)

# Pre-create line objects — updating data is cheaper than recreating lines
line_t1, = ax_temp.plot([], [], color="#00BFFF", linewidth=1.2, label="RTD 1")
line_t2, = ax_temp.plot([], [], color="#FF6347", linewidth=1.2, label="RTD 2")
line_t3, = ax_temp.plot([], [], color="#90EE90", linewidth=1.2, label="RTD 3")
ax_temp.legend(loc="upper left", fontsize=8, framealpha=0.3)

line_pin,  = ax_pow.plot([], [], color="#FFD700", linewidth=1.2, label="P heating (in)")
line_pout, = ax_pow.plot([], [], color="#FF69B4", linewidth=1.2, label="P radiated (out)")
ax_pow.legend(loc="upper left", fontsize=8, framealpha=0.3)


def redraw_plot():
    """Render the matplotlib figure to a PIL image, push to Tkinter canvas."""
    times = list(hist_time)
    if len(times) < 2:
        root.after(PLOT_UPDATE_MS, redraw_plot)
        return

    # Update temperature lines
    line_t1.set_data(times, list(hist_t1))
    line_t2.set_data(times, list(hist_t2))
    line_t3.set_data(times, list(hist_t3))
    ax_temp.relim()
    ax_temp.autoscale_view()
    ax_temp.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))

    # Update power lines
    line_pin.set_data(times,  list(hist_pin))
    line_pout.set_data(times, list(hist_pout))
    ax_pow.relim()
    ax_pow.autoscale_view()
    ax_pow.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))

    # Rotate x-tick labels
    for ax in (ax_temp, ax_pow):
        for lbl in ax.get_xticklabels():
            lbl.set_rotation(25)
            lbl.set_color("#888888")
            lbl.set_fontsize(8)

    # Render to PNG in memory → PIL → Tk PhotoImage
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=100, facecolor=fig.get_facecolor())
    buf.seek(0)
    img   = Image.open(buf)
    photo = ImageTk.PhotoImage(img)

    plot_canvas.config(width=photo.width(), height=photo.height())
    plot_canvas.create_image(0, 0, anchor="nw", image=photo)
    plot_canvas.image = photo      # hold reference — prevents garbage collection
    buf.close()

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
root.title("Cryo Thermal Monitor")
root.configure(bg=BG)
root.resizable(False, False)

# ── Top header bar ────────────────────────────────────────────────────────────
hdr = tk.Frame(root, bg="#111111")
hdr.pack(fill="x")
tk.Label(hdr, text="CRYO THERMAL MONITOR", font=("Helvetica", 18, "bold"),
         fg=FG_WHITE, bg="#111111").pack(side="left", padx=24, pady=10)
clock_lbl = tk.Label(hdr, text="", font=("Courier New", 14),
                     fg=FG_DIM, bg="#111111")
clock_lbl.pack(side="right", padx=24)

# ── Main body: left | right ───────────────────────────────────────────────────
body = tk.Frame(root, bg=BG)
body.pack(fill="both", expand=True, padx=20, pady=10)

left_col = tk.Frame(body, bg=BG)
left_col.pack(side="left", fill="both", expand=False, padx=(0, 10))

right_col = tk.Frame(body, bg=BG)
right_col.pack(side="left", fill="both", expand=True, padx=(10, 0))

def section_title(parent, text):
    tk.Label(parent, text=text, font=("Helvetica", 16, "bold"),
             fg="#AAAAAA", bg=BG).pack(anchor="w", pady=(0, 8))
    tk.Frame(parent, bg=SEP_COL, height=1).pack(fill="x", pady=(0, 16))

def make_row(parent, label_text,
             font_val=("Courier New", 28, "bold"),
             font_lbl=("Helvetica", 14),
             fg_lbl=None):
    row = tk.Frame(parent, bg=BG)
    row.pack(fill="x", pady=4)
    tk.Label(row, text=label_text, font=font_lbl,
             fg=fg_lbl or FG_DIM, bg=BG, width=24, anchor="w").pack(side="left")
    val_lbl = tk.Label(row, text="---", font=font_val, fg=FG_WHITE, bg=BG, anchor="w")
    val_lbl.pack(side="left")
    return val_lbl

def static_row(parent, label, value_str):
    row = tk.Frame(parent, bg=BG)
    row.pack(fill="x", pady=4)
    tk.Label(row, text=label, font=("Helvetica", 14),
             fg=FG_LABEL, bg=BG, width=24, anchor="w").pack(side="left")
    tk.Label(row, text=value_str, font=("Courier New", 28, "bold"),
             fg=FG_WHITE, bg=BG).pack(side="left")

# =============================================================================
# LEFT COLUMN — SAFETY
# =============================================================================
section_title(left_col, "SAFETY")

tk.Label(left_col, text="TYPE K THERMOCOUPLE",
         font=("Helvetica", 13, "bold"), fg=FG_DIM, bg=BG).pack(anchor="w")
tk_temp_lbl = tk.Label(left_col, text="--.- °C",
                        font=("Helvetica", 100, "bold"), fg=FG_GREEN, bg=BG)
tk_temp_lbl.pack(anchor="w", pady=(0, 4))
tk_status_lbl = tk.Label(left_col, text="NORMAL",
                          font=("Helvetica", 18, "bold"), fg=FG_GREEN, bg=BG)
tk_status_lbl.pack(anchor="w", pady=(0, 24))

tk.Frame(left_col, bg=SEP_COL, height=1).pack(fill="x", pady=(0, 16))

tk.Label(left_col, text="PRESSURE SENSORS",
         font=("Helvetica", 13, "bold"), fg=FG_DIM, bg=BG).pack(anchor="w", pady=(0, 8))

p1_row = tk.Frame(left_col, bg=BG); p1_row.pack(fill="x", pady=6)
tk.Label(p1_row, text="P1", font=("Helvetica", 13), fg=FG_DIM, bg=BG,
         width=6, anchor="w").pack(side="left")
p1_lbl = tk.Label(p1_row, text="--.- PSIG",
                  font=("Courier New", 40, "bold"), fg=FG_GREEN, bg=BG)
p1_lbl.pack(side="left")

p2_row = tk.Frame(left_col, bg=BG); p2_row.pack(fill="x", pady=6)
tk.Label(p2_row, text="P2", font=("Helvetica", 13), fg=FG_DIM, bg=BG,
         width=6, anchor="w").pack(side="left")
p2_lbl = tk.Label(p2_row, text="--.- PSIG",
                  font=("Courier New", 40, "bold"), fg=FG_GREEN, bg=BG)
p2_lbl.pack(side="left")

tk.Label(left_col,
    text="GREEN: -7 to 7 bar   ORANGE: -11 to -7 or 7 to 22   RED: outside",
    font=("Helvetica", 10), fg=FG_DIM, bg=BG).pack(anchor="w", pady=(10, 0))

# =============================================================================
# RIGHT COLUMN — SETUP + MEASUREMENTS + PLOT
# =============================================================================

# ── Setup ─────────────────────────────────────────────────────────────────────
section_title(right_col, "SETUP")
static_row(right_col, "Motor command",    f"{MOTOR_COMMAND}")
static_row(right_col, "Mass flow rate",   f"{MASS_FLOW_RATE_G_MIN:.1f} g/min")
static_row(right_col, "Electrical power", f"{POWER_INPUT_W} W")
tk.Frame(right_col, bg=SEP_COL, height=1).pack(fill="x", pady=(12, 12))

# ── Measurements ──────────────────────────────────────────────────────────────
section_title(right_col, "MEASUREMENTS")
rtd1_lbl = make_row(right_col, "RTD 1  (D6)",  fg_lbl=FG_LABEL)
rtd2_lbl = make_row(right_col, "RTD 2  (D12)", fg_lbl=FG_LABEL)
rtd3_lbl = make_row(right_col, "RTD 3  (D13)", fg_lbl=FG_LABEL)
tk.Frame(right_col, bg=SEP_COL, height=1).pack(fill="x", pady=(12, 12))

pin_lbl  = make_row(right_col, "Power Heating (In)  (W)",  fg_lbl=FG_LABEL)
pout_lbl = make_row(right_col, "Power Radiated (Out) (W)", fg_lbl=FG_LABEL)
tk.Frame(right_col, bg=SEP_COL, height=1).pack(fill="x", pady=(12, 12))

# ── Plot canvas ───────────────────────────────────────────────────────────────
tk.Label(right_col, text="LIVE PLOTS", font=("Helvetica", 13, "bold"),
         fg=FG_DIM, bg=BG).pack(anchor="w", pady=(0, 6))

plot_canvas = tk.Canvas(right_col, width=PLOT_W_PX, height=PLOT_H_PX,
                         bg="#0d0d0d", highlightthickness=0)
plot_canvas.pack(anchor="w")

# =============================================================================
# UPDATE LOOP  (sensor reads — 2 Hz)
# =============================================================================
def update():
    # ⏱ TIMING START — delete the 4 lines marked ⏱ to remove timing later
    _t0 = time.perf_counter()                                              # ⏱

    now_str = time.strftime("%Y-%m-%d %H:%M:%S")
    clock_lbl.config(text=now_str)

    # ── Type K ───────────────────────────────────────────────────────────────
    try:
        tk_c   = sensor_k.temperature
        c      = temp_color(tk_c)
        status = ("NORMAL" if tk_c < T_SAFE
                  else "WARNING" if tk_c <= T_DANGER else "DANGER!")
        tk_temp_lbl.config(text=f"{tk_c:.1f} °C", fg=c)
        tk_status_lbl.config(text=status, fg=c)
    except Exception as e:
        tk_c = None
        tk_temp_lbl.config(text="ERROR", fg="#FF0000")
        tk_status_lbl.config(text=str(e)[:50], fg="#FF0000")

    # ── RTDs ─────────────────────────────────────────────────────────────────
    try:    t1 = sensor1.temperature
    except: t1 = None
    try:    t2 = sensor2.temperature
    except: t2 = None
    try:    t3 = sensor3.temperature
    except: t3 = None

    rtd1_lbl.config(text=f"{fmt(t1)} °C")
    rtd2_lbl.config(text=f"{fmt(t2)} °C")
    rtd3_lbl.config(text=f"{fmt(t3)} °C")

    # ── Pressures ─────────────────────────────────────────────────────────────
    try:    p1 = voltage_to_psi(channel0.voltage)
    except: p1 = None
    try:    p2 = voltage_to_psi(channel1.voltage)
    except: p2 = None

    p1_lbl.config(text=f"{fmt(p1, 2)} PSIG", fg=pressure_color(p1))
    p2_lbl.config(text=f"{fmt(p2, 2)} PSIG", fg=pressure_color(p2))

    # ── Power calcs ───────────────────────────────────────────────────────────
    if t1 is not None and t3 is not None:
        p_in = C_P * MASS_FLOW_RATE * (t1 - t3)
        pin_lbl.config(text=f"{p_in:.1f} W")
    else:
        p_in = None
        pin_lbl.config(text="ERR")

    if t2 is not None and t3 is not None:
        p_out = C_P * MASS_FLOW_RATE * (t2 - t3)
        pout_lbl.config(text=f"{p_out:.1f} W")
    else:
        p_out = None
        pout_lbl.config(text="ERR")

    # ── History buffers ───────────────────────────────────────────────────────
    hist_time.append(datetime.datetime.now())
    hist_t1.append(t1    if t1    is not None else float("nan"))
    hist_t2.append(t2    if t2    is not None else float("nan"))
    hist_t3.append(t3    if t3    is not None else float("nan"))
    hist_pin.append(p_in  if p_in  is not None else float("nan"))
    hist_pout.append(p_out if p_out is not None else float("nan"))

    # ── Console ───────────────────────────────────────────────────────────────
    print(f"[{now_str}]  K={fmt(tk_c)}°C  "
          f"RTD1={fmt(t1)}  RTD2={fmt(t2)}  RTD3={fmt(t3)}°C  "
          f"P1={fmt(p1,2)}  P2={fmt(p2,2)} PSIG")

    # ⏱ TIMING END — delete these 2 lines to remove timing later
    _loop_ms = (time.perf_counter() - _t0) * 1000                         # ⏱
    print(f"  ↳ loop time (excl. sleep): {_loop_ms:.1f} ms")              # ⏱

    # ── CSV ───────────────────────────────────────────────────────────────────
    with open(CSV_FILE, "a", newline="") as f:
        csv.writer(f).writerow([
            now_str,
            f"{tk_c:.4f}" if tk_c  is not None else "",
            f"{t1:.4f}"   if t1    is not None else "",
            f"{t2:.4f}"   if t2    is not None else "",
            f"{t3:.4f}"   if t3    is not None else "",
            f"{p1:.4f}"   if p1    is not None else "",
            f"{p2:.4f}"   if p2    is not None else "",
            f"{p_in:.4f}" if p_in  is not None else "",
            f"{p_out:.4f}"if p_out is not None else "",
        ])

    root.after(500, update)     # 2 Hz — sensor loop

# =============================================================================
# START
# =============================================================================
update()                                        # first sensor read immediately
root.after(PLOT_UPDATE_MS, redraw_plot)         # first plot after 5 s
root.mainloop()
