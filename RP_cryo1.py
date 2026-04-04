#!/usr/bin/env python3

"""
BLISS Cryo Radiator Test - RP4 Control System
Main entry point for cryo1 (first Raspberry Pi)

Phase 1: Type K Thermocouple reading with threading model
Phase 2: Add RTD sensor + motor control with PID
Phase 3: Add pressure sensor + safety features

Devices controlled:
- 1x Type K Thermocouple (MAX31855) via I2C
- 1x RTD Sensor (MAX31865) via I2C [Phase 2]
- 1x Pressure Transducer (ADS1115) via I2C [Phase 3]
- 1x Motor Driver (BTS7960) with PID controller [Phase 2]
- 1x Motor Encoder for feedback [Phase 2]
"""
