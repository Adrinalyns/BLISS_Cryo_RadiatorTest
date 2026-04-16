#!/usr/bin/env python3
"""
Thermal & Pressure Dashboard
MAX31855 (Type K) + 3x MAX31865 (PT100 RTD) + 2x pressure sensors
pip install adafruit-circuitpython-max31855 adafruit-circuitpython-max31865
"""
import time
import csv
import os
import collections
import board
import digitalio
import busio
import adafruit_max31855
import adafruit_max31865
from adafruit_ads1x15 import ADS1115, AnalogIn, ads1x15
import tkinter as tk

# =============================================================================
# USER-DEFINED PARAMETERS — set these before running
# =============================================================================
MOTOR_COMMAND        = 1850          # Motor command value
MASS_FLOW_RATE_G_MIN = 62.3      # g/min  — mass flow rate (convert to kg/s in code)
C_P                  = 3700.0        # J/(kg·K) — specific heat capacity depends on the temperature

# =============================================================================
# Convert mass flow rate to kg/s for power calculations
# =============================================================================
MASS_FLOW_RATE = MASS_FLOW_RATE_G_MIN / 60.0 / 1000.0       # kg/s  — mass flow rate


# =============================================================================
# TEMPERATURE THRESHOLDS (Type K colour coding)
# =============================================================================
T_SAFE   = 65.0
T_DANGER = 85.0

# =============================================================================
# PRESSURE THRESHOLDS
# =============================================================================
P_GREEN_LO  = -7.0
P_GREEN_HI  =  7.0
P_ORANGE_LO = -11.0
P_ORANGE_HI =  22.0
# < -11 or > 22 → red | -11 to -7 or 7 to 22 → orange | -7 to 7 → green

# =============================================================================
# ── Pressure conversion constants 
# =============================================================================
V_MIN = 0.5    # Volts → minimum sensor output
V_MAX = 4.5    # Volts → maximum sensor output
P_MIN = -14.5  # PSIG  → pressure at V_MIN
P_MAX = 30.0   # PSIG  → pressure at V_MAX


# =============================================================================
# STEADY STATE PARAMETERS
# =============================================================================
SS_WINDOW_SEC   = 30           # seconds of data to watch (rolling window)
SS_UPDATE_HZ    = 2            # must match 1000/root.after value
SS_WINDOW_N     = SS_WINDOW_SEC * SS_UPDATE_HZ   # number of samples in window

SS_TEMP_DRIFT   = 0.5          # °C — max allowed mean drift across window
SS_TEMP_PP      = 1.0          # °C — max allowed peak-to-peak
SS_PRES_DRIFT   = 0.20         # bar — max allowed mean drift (1% of ~20 bar setpoint)
SS_PRES_PP      = 0.40         # bar — max allowed peak-to-peak (±2%)

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
# I2C SETUP FOR PRESSURE SENSORS
# =============================================================================

try:
    i2c = busio.I2C(board.SCL, board.SDA)   # SCL = GPIO3, SDA = GPIO2
    ads = ADS1115(i2c)                       # Default I2C address: 0x48
    ads.gain = 1                             # Gain=1 → ±4.096 V range (covers 0.5–4.5 V)

    # Define the two input channels using Pin constants from the ads1x15 module
    channel0 = AnalogIn(ads, ads1x15.Pin.A0)   # Sensor 1 → A0
    channel1 = AnalogIn(ads, ads1x15.Pin.A1)   # Sensor 2 → A1

    print("ADS1115 ready. Reading pressure sensors...\n")

except Exception as e:
    print(f"ERROR: Could not initialise ADS1115 over I2C.\n  → {e}")
    print("Check wiring: SDA=GPIO2, SCL=GPIO3, VCC=5V, ADDR pin to GND (addr 0x48).")
    raise SystemExit(1)


def voltage_to_psi(voltage):
    """
    Convert sensor voltage to PSI using a linear mapping:

        PSI = (V - V_MIN) / (V_MAX - V_MIN) * (P_MAX - P_MIN) + P_MIN

    Example: 2.5 V → midpoint → ~7.75 PSI
    """
    return (voltage - V_MIN) / (V_MAX - V_MIN) * (P_MAX - P_MIN) + P_MIN


# =============================================================================
# COLOUR HELPERS
# =============================================================================
def temp_color(temp):
    if temp is None:              return "#FF0000"
    if temp < T_SAFE:             return "#00CC00"
    if temp <= T_DANGER:          return "#FF8000"
    return "#FF0000"

def pressure_color(p):
    if p is None:                             return "#FF0000"
    if P_GREEN_LO <= p <= P_GREEN_HI:         return "#00CC00"
    if P_ORANGE_LO <= p <= P_ORANGE_HI:       return "#FF8000"
    return "#FF0000"

def fmt(val, decimals=1):
    if val is None:
        return "ERR"
    return f"{val:.{decimals}f}"

# =============================================================================
# STEADY STATE ENGINE
# =============================================================================
# One rolling deque per monitored signal
_signals = {
    "rtd1": collections.deque(maxlen=SS_WINDOW_N),
    "rtd2": collections.deque(maxlen=SS_WINDOW_N),
    "rtd3": collections.deque(maxlen=SS_WINDOW_N),
    "p1":   collections.deque(maxlen=SS_WINDOW_N),
    "p2":   collections.deque(maxlen=SS_WINDOW_N),
}
_ss_thresholds = {
    "rtd1": (SS_TEMP_DRIFT, SS_TEMP_PP),
    "rtd2": (SS_TEMP_DRIFT, SS_TEMP_PP),
    "rtd3": (SS_TEMP_DRIFT, SS_TEMP_PP),
    "p1":   (SS_PRES_DRIFT, SS_PRES_PP),
    "p2":   (SS_PRES_DRIFT, SS_PRES_PP),
}
_ss_stable_since = None   # timestamp when all signals first became stable

def push_ss(key, value):
    if value is not None:
        _signals[key].append(value)

def signal_stable(key):
    buf = _signals[key]
    if len(buf) < SS_WINDOW_N:
        return False, 0.0, 0.0          # not enough data yet
    half = SS_WINDOW_N // 2
    first_half  = list(buf)[:half]
    second_half = list(buf)[half:]
    drift = abs(sum(second_half)/len(second_half) - sum(first_half)/len(first_half))
    pp    = max(buf) - min(buf)
    max_drift, max_pp = _ss_thresholds[key]
    return (drift <= max_drift and pp <= max_pp), drift, pp

def compute_ss_state():
    global _ss_stable_since
    statuses = {}
    all_stable = True
    for key in _signals:
        stable, drift, pp = signal_stable(key)
        statuses[key] = (stable, drift, pp)
        if not stable:
            all_stable = False

    now = time.time()
    if all_stable:
        if _ss_stable_since is None:
            _ss_stable_since = now
        stable_for = now - _ss_stable_since
    else:
        _ss_stable_since = None
        stable_for = 0.0

    # Count how many signals have enough data
    filled = sum(1 for k in _signals if len(_signals[k]) >= SS_WINDOW_N)
    filling_pct = min(1.0, sum(len(_signals[k]) for k in _signals) /
                      (len(_signals) * SS_WINDOW_N))

    return all_stable, stable_for, statuses, filling_pct

# =============================================================================
# WINDOW LAYOUT
# =============================================================================
BG       = "black"
FG_DIM   = "#555555"
FG_WHITE = "white"
FG_GREEN = "#00CC00"
SEP_COL  = "#333333"

root = tk.Tk()
root.title("Cryo Thermal Monitor")
root.geometry("1600x1280")
root.configure(bg=BG)
root.resizable(False, False)

# ── Top header bar ────────────────────────────────────────────────────────────
hdr = tk.Frame(root, bg="#111111")
hdr.pack(fill="x", padx=0, pady=0)
tk.Label(hdr, text="CRYO THERMAL MONITOR", font=("Helvetica", 18, "bold"),
         fg=FG_WHITE, bg="#111111").pack(side="left", padx=24, pady=10)
clock_lbl = tk.Label(hdr, text="", font=("Courier New", 14),
                     fg=FG_DIM, bg="#111111")
clock_lbl.pack(side="right", padx=24)

# ── Two-column body ───────────────────────────────────────────────────────────
body = tk.Frame(root, bg=BG)
body.pack(fill="both", expand=True, padx=20, pady=10)

left_col  = tk.Frame(body, bg=BG)
left_col.pack(side="left", fill="both", expand=True, padx=(0, 10))

right_col = tk.Frame(body, bg=BG)
right_col.pack(side="left", fill="both", expand=True, padx=(10, 0))

def section_title(parent, text):
    tk.Label(parent, text=text, font=("Helvetica", 16, "bold"),
             fg="#AAAAAA", bg=BG).pack(anchor="w", pady=(0, 8))
    tk.Frame(parent, bg=SEP_COL, height=1).pack(fill="x", pady=(0, 16))

def make_row(parent, label_text, font_val=("Courier New", 28, "bold"),
             font_lbl=("Helvetica", 12)):
    row = tk.Frame(parent, bg=BG)
    row.pack(fill="x", pady=4)
    tk.Label(row, text=label_text, font=font_lbl,
             fg=FG_DIM, bg=BG, width=22, anchor="w").pack(side="left")
    val_lbl = tk.Label(row, text="---", font=font_val,
                       fg=FG_WHITE, bg=BG, anchor="w")
    val_lbl.pack(side="left")
    return val_lbl

# =============================================================================
# LEFT COLUMN — SAFETY
# =============================================================================
section_title(left_col, "SAFETY")

# Type K
tk.Label(left_col, text="TYPE K THERMOCOUPLE",
         font=("Helvetica", 13, "bold"), fg=FG_DIM, bg=BG).pack(anchor="w")
tk_temp_lbl = tk.Label(left_col, text="--.- °C",
                        font=("Helvetica", 100, "bold"), fg=FG_GREEN, bg=BG)
tk_temp_lbl.pack(anchor="w", pady=(0, 4))
tk_status_lbl = tk.Label(left_col, text="NORMAL",
                          font=("Helvetica", 18, "bold"), fg=FG_GREEN, bg=BG)
tk_status_lbl.pack(anchor="w", pady=(0, 24))

tk.Frame(left_col, bg=SEP_COL, height=1).pack(fill="x", pady=(0, 16))

# Pressures
tk.Label(left_col, text="PRESSURE SENSORS",
         font=("Helvetica", 13, "bold"), fg=FG_DIM, bg=BG).pack(anchor="w", pady=(0, 8))

p1_row = tk.Frame(left_col, bg=BG); p1_row.pack(fill="x", pady=6)
tk.Label(p1_row, text="P1", font=("Helvetica", 13), fg=FG_DIM, bg=BG,
         width=6, anchor="w").pack(side="left")
p1_lbl = tk.Label(p1_row, text="--.- bar", font=("Courier New", 40, "bold"),
                  fg=FG_GREEN, bg=BG)
p1_lbl.pack(side="left")

p2_row = tk.Frame(left_col, bg=BG); p2_row.pack(fill="x", pady=6)
tk.Label(p2_row, text="P2", font=("Helvetica", 13), fg=FG_DIM, bg=BG,
         width=6, anchor="w").pack(side="left")
p2_lbl = tk.Label(p2_row, text="--.- bar", font=("Courier New", 40, "bold"),
                  fg=FG_GREEN, bg=BG)
p2_lbl.pack(side="left")

# Pressure legend
legend = tk.Label(left_col,
    text="GREEN: -7 to 7 bar   ORANGE: -11 to -7 or 7 to 22   RED: outside",
    font=("Helvetica", 10), fg=FG_DIM, bg=BG)
legend.pack(anchor="w", pady=(10, 0))

# =============================================================================
# RIGHT COLUMN — MEASUREMENTS
# =============================================================================
section_title(right_col, "MEASUREMENTS")

# Static user-defined values (printed once, not updated)
cmd_row = tk.Frame(right_col, bg=BG); cmd_row.pack(fill="x", pady=4)
tk.Label(cmd_row, text="Motor command", font=("Helvetica", 12),
         fg=FG_DIM, bg=BG, width=22, anchor="w").pack(side="left")
tk.Label(cmd_row, text=f"{MOTOR_COMMAND}", font=("Courier New", 28, "bold"),
         fg=FG_WHITE, bg=BG).pack(side="left")

mdot_row = tk.Frame(right_col, bg=BG); mdot_row.pack(fill="x", pady=4)
tk.Label(mdot_row, text="Mass flow rate", font=("Helvetica", 12),
         fg=FG_DIM, bg=BG, width=22, anchor="w").pack(side="left")
tk.Label(mdot_row, text=f"{MASS_FLOW_RATE_G_MIN:.1f} g/min",
         font=("Courier New", 28, "bold"), fg=FG_WHITE, bg=BG).pack(side="left")

tk.Frame(right_col, bg=SEP_COL, height=1).pack(fill="x", pady=(12, 12))

# RTD temperatures
rtd1_lbl = make_row(right_col, "RTD 1  (D6)")
rtd2_lbl = make_row(right_col, "RTD 2  (D12)")
rtd3_lbl = make_row(right_col, "RTD 3  (D13)")

tk.Frame(right_col, bg=SEP_COL, height=1).pack(fill="x", pady=(12, 12))

# Power calcs
pin_lbl  = make_row(right_col, "Power Heating (In)  (W)",
                    font_val=("Courier New", 28, "bold"), font_lbl=("Helvetica", 12))
pout_lbl = make_row(right_col, "Power Radiated (Out) (W)",
                    font_val=("Courier New", 28, "bold"), font_lbl=("Helvetica", 12))

tk.Frame(right_col, bg=SEP_COL, height=1).pack(fill="x", pady=(12, 12))

# Steady state indicator
tk.Label(right_col, text="STEADY STATE", font=("Helvetica", 13, "bold"),
         fg=FG_DIM, bg=BG).pack(anchor="w", pady=(0, 6))

ss_state_lbl = tk.Label(right_col, text="COLLECTING DATA...",
                         font=("Helvetica", 22, "bold"), fg="#888888", bg=BG)
ss_state_lbl.pack(anchor="w")

ss_timer_lbl = tk.Label(right_col, text="",
                         font=("Courier New", 14), fg=FG_DIM, bg=BG)
ss_timer_lbl.pack(anchor="w", pady=(2, 8))

# Progress bar (canvas-based, shows window fill then stability)
SS_BAR_W = 600
SS_BAR_H = 20
ss_canvas = tk.Canvas(right_col, width=SS_BAR_W, height=SS_BAR_H,
                       bg="#1a1a1a", highlightthickness=0)
ss_canvas.pack(anchor="w", pady=(0, 8))

# Per-signal stability grid
sig_frame = tk.Frame(right_col, bg=BG)
sig_frame.pack(anchor="w", fill="x")

_sig_labels = {}
for key, disp in [("rtd1","RTD 1"),("rtd2","RTD 2"),("rtd3","RTD 3"),
                   ("p1","P1"),("p2","P2")]:
    row = tk.Frame(sig_frame, bg=BG)
    row.pack(side="left", padx=8)
    tk.Label(row, text=disp, font=("Helvetica", 10), fg=FG_DIM, bg=BG).pack()
    dot = tk.Label(row, text="●", font=("Helvetica", 18), fg="#444444", bg=BG)
    dot.pack()
    _sig_labels[key] = dot

def draw_ss_bar(ratio, color):
    ss_canvas.delete("all")
    ss_canvas.create_rectangle(0, 0, SS_BAR_W, SS_BAR_H, fill="#1a1a1a", outline="")
    w = int(ratio * SS_BAR_W)
    if w > 0:
        ss_canvas.create_rectangle(0, 0, w, SS_BAR_H, fill=color, outline="")

# =============================================================================
# UPDATE LOOP
# =============================================================================
def update():
    now_str = time.strftime("%Y-%m-%d %H:%M:%S")
    clock_lbl.config(text=now_str)

    # ── Type K ───────────────────────────────────────────────────────────────
    try:
        tk_c = sensor_k.temperature
        c = temp_color(tk_c)
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
    try:    p1 = psi1 = voltage_to_psi(channel0.voltage)
    except: p1 = None
    try:    p2 = psi2 = voltage_to_psi(channel1.voltage)
    except: p2 = None

    p1_lbl.config(text=f"{fmt(p1, 2)} PSIG", fg=pressure_color(p1))
    p2_lbl.config(text=f"{fmt(p2, 2)} PSIG", fg=pressure_color(p2))

    # ── Power calcs ───────────────────────────────────────────────────────────
    if t1 is not None and t3 is not None:
        p_in  = C_P * MASS_FLOW_RATE * (t1 - t3)
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

    # ── Steady state ──────────────────────────────────────────────────────────
    push_ss("rtd1", t1)
    push_ss("rtd2", t2)
    push_ss("rtd3", t3)
    push_ss("p1",   p1)
    push_ss("p2",   p2)

    all_stable, stable_for, statuses, fill_pct = compute_ss_state()

    # Update per-signal dots
    for key, (stable, drift, pp) in statuses.items():
        n = len(_signals[key])
        if n < SS_WINDOW_N:
            color = "#444444"   # still filling
        elif stable:
            color = "#00CC00"   # stable
        else:
            color = "#FF4444"   # drifting
        _sig_labels[key].config(fg=color)

    # Bar and label
    if fill_pct < 1.0:
        draw_ss_bar(fill_pct, "#555555")
        ss_state_lbl.config(text=f"COLLECTING DATA  ({int(fill_pct*100)}%)",
                             fg="#888888")
        ss_timer_lbl.config(text=f"Need {SS_WINDOW_SEC}s of data")
    elif all_stable:
        draw_ss_bar(min(1.0, stable_for / SS_WINDOW_SEC), "#00CC00")
        ss_state_lbl.config(text="STEADY STATE", fg="#00CC00")
        ss_timer_lbl.config(text=f"Stable for {stable_for:.0f}s")
    else:
        # Partial: show how many signals are stable
        n_stable = sum(1 for k, (s, d, p) in statuses.items() if s)
        ratio = n_stable / len(statuses)
        draw_ss_bar(ratio, "#FF8000")
        ss_state_lbl.config(
            text=f"CONVERGING  ({n_stable}/{len(statuses)} signals stable)",
            fg="#FF8000")
        ss_timer_lbl.config(text="")

    # ── Console print ─────────────────────────────────────────────────────────
    tk_str = fmt(tk_c); t1s = fmt(t1); t2s = fmt(t2); t3s = fmt(t3)
    p1s = fmt(p1, 2);   p2s = fmt(p2, 2)
    print(f"[{now_str}]  K={tk_str}°C  "
          f"RTD1={t1s}  RTD2={t2s}  RTD3={t3s}°C  "
          f"P1={p1s}  P2={p2s} PSIG")

    # ── CSV ───────────────────────────────────────────────────────────────────
    with open(CSV_FILE, "a", newline="") as f:
        csv.writer(f).writerow([
            now_str,
            f"{tk_c:.2f}" if tk_c is not None else "",
            f"{t1:.2f}"   if t1   is not None else "",
            f"{t2:.2f}"   if t2   is not None else "",
            f"{t3:.2f}"   if t3   is not None else "",
            f"{p1:.3f}"   if p1   is not None else "",
            f"{p2:.3f}"   if p2   is not None else "",
            f"{p_in:.2f}" if p_in  is not None else "",
            f"{p_out:.2f}"if p_out is not None else "",
        ])

    root.after(500, update)   # 2 Hz

# =============================================================================
# START
# =============================================================================
update()
root.mainloop()