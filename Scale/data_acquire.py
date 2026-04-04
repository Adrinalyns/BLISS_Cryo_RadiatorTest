#!/usr/bin/env python3

"""
This code allow to read the data from the scale and compute in real time the flow rate measured.
It also stores the data in a csv file so that it can be analyzed later. 
"""

import serial
import time
import pandas as pd
import tkinter as tk

PORT = "COM3"
BAUDRATE = 9600 # parameter of the scale
INTERVAL = 0.1 #best parameter 
DENSITY = 1.0 # in g/mL
FLOW_WINDOW = 10 # number of measures to compute the mean

ser = serial.Serial(PORT, BAUDRATE, bytesize=8, parity=serial.PARITY_NONE, stopbits=1, timeout=1)

def parse_mass(line):
    try:
        number_str = ''.join(c for c in line if c.isdigit() or c == '.' or c == '-')
        return float(number_str)
    except:
        return None

data = []
last_measures = []
start_time = time.time()

# TKinter interface
root = tk.Tk()
root.title("Flow Rate Monitor")

flow_label = tk.Label(root, text="Flow: 0.00 mL/min", font=("Arial", 80), fg="white", bg="darkblue")
flow_label.pack(padx=50, pady=50)

def update_display(flow):
    flow_label.config(text=f"Flow: {flow:.2f} mL/min")
    # Changement de couleur selon débit
    if flow < 1:
        flow_label.config(bg="darkblue")
    elif flow < 5:
        flow_label.config(bg="green")
    elif flow < 10:
        flow_label.config(bg="orange")
    else:
        flow_label.config(bg="red")
    root.update_idletasks()

# Read the values of the scale
try:
    while True:
        ser.write(b'P\r\n')
        line = ser.readline().decode(errors='ignore').strip()
        current_time = time.time() - start_time
        
        if line:
            mass = parse_mass(line)
            if mass is not None:
                last_measures.append((current_time, mass))
                if len(last_measures) > FLOW_WINDOW:
                    last_measures.pop(0)
                
                # Compute the flow rate 
                if len(last_measures) >= 2:
                    t_vals = [t for t, m in last_measures]
                    m_vals = [m for t, m in last_measures]
                    delta_mass = m_vals[-1] - m_vals[0]
                    delta_time = t_vals[-1] - t_vals[0]
                    flow_mass_per_s = delta_mass / delta_time if delta_time > 0 else 0
                    flow_mL_per_min = (flow_mass_per_s / DENSITY) * 60
                else:
                    flow_mL_per_min = 0
                
                data.append([current_time, mass, flow_mL_per_min])
                
                # Update of the display
                update_display(flow_mL_per_min)
                print(f"{current_time:.1f}s → {mass} g → {flow_mL_per_min:.2f} mL/min")
        
        time.sleep(INTERVAL)
        root.update() # tkinter still works

except KeyboardInterrupt:
    print("End of the acquisition")
finally:
    ser.close()
    df = pd.DataFrame(data, columns=["time_s", "mass_g", "flow_mL_per_min"])
    df.to_csv("mass_timeseries.csv", index=False)
    print("Data downloaded in mass_timeseries.csv")
    root.destroy()