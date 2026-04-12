#!/usr/bin/env python3
"""
Minimal MAX31855 Type K Thermocouple Reader
No dependencies except Adafruit library

Install these libraries first:
pip install adafruit-circuitpython-max31855

NEXT STEPS:
- Add a window to display the temperature in real time with color coding (green as long as T < 150F, then orange until 180F, then red)
"""

import time
import board
import digitalio
import adafruit_max31855
import adafruit_max31865
import tkinter as tk

#Temperature safe/danger
T_SAFE = 65.0
T_DANGER = 85.0
 
# --- SPI + Thermocouple Setup ---
spi = board.SPI()
cs = digitalio.DigitalInOut(board.D5)
max31855 = adafruit_max31855.MAX31855(spi, cs)

cs1 = digitalio.DigitalInOut(board.D6)
sensor1 = adafruit_max31865.MAX31865(spi,cs1,wires=4, rtd_nominal=100.01, ref_resistor=430)

cs2 = digitalio.DigitalInOut(board.D12)
sensor2 = adafruit_max31865.MAX31865(spi,cs2,wires=4, rtd_nominal=99.99, ref_resistor=430)
 
# --- Color Logic ---
def get_color(temp):
    if temp < T_SAFE:
        return "#00CC00"   # Green
    elif temp <= T_DANGER:
        return "#FF8000"   # Orange
    else:
        return "#FF0000"   # Red
 
# --- Tkinter Window ---
root = tk.Tk()
root.title("Thermocouple K - MAX31855")
root.geometry("400x220")
root.configure(bg="black")
root.resizable(False, False)
 
# Title
title = tk.Label(root, text="TYPE K THERMOCOUPLE", font=("Helvetica", 16, "bold"),
                 fg="white", bg="black")
title.pack(pady=(20, 5))
 
# Temperature display
temp_label = tk.Label(root, text="--.- °C", font=("Helvetica", 60, "bold"),
                      fg="#00CC00", bg="black")
temp_label.pack(pady=5)
 
# Status text
status_label = tk.Label(root, text="NORMAL", font=("Helvetica", 14, "bold"),
                        fg="#00CC00", bg="black")
status_label.pack(pady=5)
 
# --- Update Function ---
def update():
    try:
        tempC = max31855.temperature
        color = get_color(tempC)
 
        if tempC < T_SAFE:
            status = "NORMAL"
        elif tempC <= T_DANGER:
            status = "WARNING"
        else:
            status = "DANGER!"
 
        temp_label.config(text=f"{tempC:.1f} °C", fg=color)
        status_label.config(text=status, fg=color)

        
 
    except Exception as e:
        temp_label.config(text="ERROR", fg="#FF0000")
        status_label.config(text=str(e)[:40], fg="#FF0000")
 
    root.after(100, update)  # 0.1s = 100ms
 
# --- Start ---
update()
root.mainloop()