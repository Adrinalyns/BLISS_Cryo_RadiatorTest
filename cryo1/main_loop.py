#!/usr/bin/env python3
"""
MAX31855 (Type K) + 2x MAX31865 (PT100 RTD) — simple logger
Displays Type K with color coding, prints RTD temps plainly.
All readings saved to temperature_log.csv
pip install adafruit-circuitpython-max31855 adafruit-circuitpython-max31865
"""
import time
import csv
import os
import board
import digitalio
import adafruit_max31855
import adafruit_max31865
import tkinter as tk

# --- Thresholds (Type K display only) ---
T_SAFE   = 65.0
T_DANGER = 85.0

# --- CSV setup ---
CSV_FILE = "temperature_log.csv"
if not os.path.exists(CSV_FILE):
    with open(CSV_FILE, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "typeK_C", "rtd1_C", "rtd2_C"])

# --- SPI + Sensor Setup ---
spi  = board.SPI()

cs_k = digitalio.DigitalInOut(board.D5)
sensor_k = adafruit_max31855.MAX31855(spi, cs_k)

cs1 = digitalio.DigitalInOut(board.D6)
sensor1 = adafruit_max31865.MAX31865(spi, cs1, wires=4, rtd_nominal=100.01, ref_resistor=430)

cs2 = digitalio.DigitalInOut(board.D12)
sensor2 = adafruit_max31865.MAX31865(spi, cs2, wires=4, rtd_nominal=99.99, ref_resistor=430)

# --- Color logic (Type K only) ---
def get_color(temp):
    if temp is None:
        return "#FF0000"
    if temp < T_SAFE:
        return "#00CC00"
    elif temp <= T_DANGER:
        return "#FF8000"
    return "#FF0000"

# --- Tkinter Window ---
root = tk.Tk()
root.title("Temperature Monitor")
root.geometry("400x320")
root.configure(bg="black")
root.resizable(False, False)

# Type K — big colored display
tk.Label(root, text="TYPE K THERMOCOUPLE", font=("Helvetica", 13, "bold"),
         fg="white", bg="black").pack(pady=(18, 2))

temp_label = tk.Label(root, text="--.- °C", font=("Helvetica", 52, "bold"),
                      fg="#00CC00", bg="black")
temp_label.pack()

status_label = tk.Label(root, text="NORMAL", font=("Helvetica", 12, "bold"),
                        fg="#00CC00", bg="black")
status_label.pack(pady=(0, 12))

# Separator
tk.Frame(root, bg="#222222", height=1).pack(fill="x", padx=20)

# RTD — plain text
tk.Label(root, text="PT100 RTD", font=("Helvetica", 11, "bold"),
         fg="white", bg="black").pack(pady=(10, 4))

rtd_label = tk.Label(root, text="RTD-A: --.-°C    RTD-B: --.-°C",
                     font=("Courier New", 12), fg="white", bg="black")
rtd_label.pack()

# Timestamp
time_label = tk.Label(root, text="", font=("Courier New", 9),
                      fg="#555555", bg="black")
time_label.pack(pady=(8, 0))

# --- Update loop ---
def update():
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    time_label.config(text=now)

    # Type K
    try:
        tk_c = sensor_k.temperature
        color = get_color(tk_c)
        status = "NORMAL" if tk_c < T_SAFE else ("WARNING" if tk_c <= T_DANGER else "DANGER!")
        temp_label.config(text=f"{tk_c:.1f} °C", fg=color)
        status_label.config(text=status, fg=color)
    except Exception as e:
        tk_c = None
        temp_label.config(text="ERROR", fg="#FF0000")
        status_label.config(text=str(e)[:40], fg="#FF0000")

    # RTD — plain print + label
    try:
        t1 = sensor1.temperature
    except:
        t1 = None

    try:
        t2 = sensor2.temperature
    except:
        t2 = None

    t1_str = f"{t1:.1f}" if t1 is not None else "ERR"
    t2_str = f"{t2:.1f}" if t2 is not None else "ERR"
    rtd_label.config(text=f"RTD-A: {t1_str}°C    RTD-B: {t2_str}°C")
    print(f"[{now}]  K={tk_c:.1f}°C  RTD-A={t1_str}°C  RTD-B={t2_str}°C")

    # CSV logging
    with open(CSV_FILE, "a", newline="") as f:
        csv.writer(f).writerow([
            now,
            f"{tk_c:.2f}" if tk_c is not None else "",
            f"{t1:.2f}"   if t1  is not None else "",
            f"{t2:.2f}"   if t2  is not None else "",
        ])

    root.after(500, update)   # 2 Hz (0.5s)

# --- Start ---
update()
root.mainloop()