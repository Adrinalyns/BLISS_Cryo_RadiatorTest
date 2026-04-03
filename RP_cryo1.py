#!/usr/bin/env python3

'''
This code will be implemented in the first Raspberry PI (named cryo1)

It will control/read the following devices:
- 1x pressure transducer through the driver ADS1115
- 1x RTD sensor through the driver MAX31865
- 1x Type K Thermocouple through the driver MAX31855
- 1x motor through the drive BTS7960
    It will control the motor by sending a PWM signal to the BTS7960, 
    which will then drive the motor accordingly. 
    The motor will be used to control the flow of a pump, 
    and a PID controller (using the motor's encoders) will be implemented to maintain a desired flow rate.
'''