#!/usr/bin/env python3
"""
Minimal MAX31855 Type K Thermocouple Reader
No dependencies except Adafruit library

Install these libraries first:
pip install adafruit-circuitpython-max31855

"""

import board
import busio
import time

def read_max31855(i2c_address=0x6A):
    """Read temperature from MAX31855."""
    
    # Initialize I2C
    i2c = busio.I2C(board.SCL, board.SDA)
    
    print(f"Reading from MAX31855 at address 0x{i2c_address:02X}...")
    
    try:
        while True:
            # Read 4 bytes from MAX31855
            data = bytearray(4)
            i2c.readfrom_into(i2c_address, data)
            
            # Extract thermocouple temperature (upper 14 bits)
            temp_raw = (data[0] << 8) | data[1]
            
            # Handle negative temperatures (2's complement)
            if temp_raw & 0x8000:
                temp_raw = -(0x10000 - temp_raw)
            
            # Convert to Celsius (divide by 4, then multiply by 0.25)
            temp_c = (temp_raw >> 2) * 0.25
            
            # Check for faults
            status = data[3] & 0x07
            if status & 0x01:
                print(f"ERROR: Open circuit")
            elif status & 0x02:
                print(f"ERROR: Short to ground")
            elif status & 0x04:
                print(f"ERROR: Short to VCC")
            else:
                print(f"Temp: {temp_c:7.2f}°C")
            
            time.sleep(0.2)  # Read every 200ms
    
    except KeyboardInterrupt:
        print("\nStopped")
    finally:
        i2c.deinit()

if __name__ == '__main__':
    read_max31855()