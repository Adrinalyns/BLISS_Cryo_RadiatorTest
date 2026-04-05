import time
import argparse

#!/usr/bin/env python3
"""
BTS7960 / IBT-2 motor driver control for Raspberry Pi 4.

Wiring (BCM pins by default):
- R_EN  -> GPIO17
- L_EN  -> GPIO27
- RPWM  -> GPIO12
- LPWM  -> GPIO13
- GND   -> Pi GND (common ground with motor PSU)

Usage:
- create a BTS7960 instance ("motor = BTS7960()")
- set speed with "motor.set_speed(50)"
    The speed is a percentage from -100 (full reverse) to 100 (full forward). 0 stops the motor.
- stop with "motor.stop()"
- cleanup with "motor.cleanup()"
"""

import pigpio
import time

class BTS7960:
    def __init__(self, r_en=17, l_en=27, rpwm=12, lpwm=13, pwm_freq=10000):
        self.rpwm_pin = rpwm
        self.lpwm_pin = lpwm
        self.freq = pwm_freq
        self.current_speed = 0.0
        self.pi = pigpio.pi()

        self.pi.set_mode(r_en, pigpio.OUTPUT)
        self.pi.set_mode(l_en, pigpio.OUTPUT)
        self.pi.write(r_en, 1)
        self.pi.write(l_en, 1)

    def set_speed(self, speed_percent: float):
        speed = max(-100.0, min(100.0, float(speed_percent)))
        duty = int(abs(speed) / 100 * 255)

        if speed > 0:
            self.pi.set_PWM_frequency(self.rpwm_pin, self.freq)
            self.pi.set_PWM_dutycycle(self.rpwm_pin, duty)
            self.pi.set_PWM_dutycycle(self.lpwm_pin, 0)
        elif speed < 0:
            self.pi.set_PWM_frequency(self.lpwm_pin, self.freq)
            self.pi.set_PWM_dutycycle(self.lpwm_pin, duty)
            self.pi.set_PWM_dutycycle(self.rpwm_pin, 0)
        else:
            self.stop()

        self.current_speed = speed

    def set_speed_smooth(self, target_speed: float, step: float = 5.0, delay: float = 0.05, zero_pause: float = 0.1):
        """
        Changes the speed smoothly and safely towards target_speed.
        step       : increment of speed per step (default 5%)
        delay      : time between each step in seconds (default 50ms)
        zero_pause : pause at zero speed when inverting direction (default 100ms)
        """
        current = self.current_speed
        target = max(-100.0, min(100.0, float(target_speed)))

        inversion = (current > 0 and target < 0) or (current < 0 and target > 0)

        if inversion:
            self._ramp(current, 0, step, delay)
            time.sleep(zero_pause)
            self._ramp(0, target, step, delay)
        else:
            self._ramp(current, target, step, delay)

        self.current_speed = target

    def _ramp(self, from_speed: float, to_speed: float, step: float, delay: float):
        """Rampe linéaire entre deux vitesses. Usage interne."""
        if from_speed < to_speed:
            steps = range(int(from_speed), int(to_speed), int(step))
        else:
            steps = range(int(from_speed), int(to_speed), -int(step))

        for s in steps:
            self.set_speed(s)
            time.sleep(delay)

        self.set_speed(to_speed)

    def stop(self):
        self.pi.set_PWM_dutycycle(self.rpwm_pin, 0)
        self.pi.set_PWM_dutycycle(self.lpwm_pin, 0)

    def cleanup(self):
        self.stop()
        self.pi.stop()