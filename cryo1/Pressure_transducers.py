"""
Dual Pressure Sensor Reader
Hardware: Raspberry Pi 4 + ADS1115 ADC (I2C) + 2x DATAQ 2000361-N1530H sensors
Sensor output: 0.5V–4.5V maps to -14.5 PSI to +30 PSI (linear)

Install dependencies before running:
    pip install adafruit-circuitpython-ads1x15
"""

import time
import board
import busio
from adafruit_ads1x15 import ADS1115, AnalogIn, ads1x15

# ── Pressure conversion constants ──────────────────────────────────────────────
V_MIN = 0.5    # Volts → minimum sensor output
V_MAX = 4.5    # Volts → maximum sensor output
P_MIN = -14.5  # PSIG  → pressure at V_MIN
P_MAX = 30.0   # PSIG  → pressure at V_MAX

def voltage_to_psi(voltage):
    """
    Convert sensor voltage to PSI using a linear mapping:

        PSI = (V - V_MIN) / (V_MAX - V_MIN) * (P_MAX - P_MIN) + P_MIN

    Example: 2.5 V → midpoint → ~7.75 PSI
    """
    return (voltage - V_MIN) / (V_MAX - V_MIN) * (P_MAX - P_MIN) + P_MIN

# ── Setup I2C bus and ADS1115 ───────────────────────────────────────────────────
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

# ── Main reading loop ───────────────────────────────────────────────────────────
try:
    while True:
        # Read raw voltage from each channel (Adafruit library handles the conversion)
        v1 = channel0.voltage   # Sensor 1 voltage (V)
        v2 = channel1.voltage   # Sensor 2 voltage (V)

        # Convert voltages to PSI
        psi1 = voltage_to_psi(v1)
        psi2 = voltage_to_psi(v2)

        # Print results in the requested format
        print(f"Pressure 1: {psi1:.1f} PSI")
        print(f"Pressure 2: {psi2:.1f} PSI")

        time.sleep(1)   # Wait 1 second before the next reading

except KeyboardInterrupt:
    print("\nStopped by user.")