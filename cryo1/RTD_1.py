import board
import digitalio
import adafruit_max31865
import time
import adafruit_max31855



spi = board.SPI()
cs1 = digitalio.DigitalInOut(board.D6)
sensor1 = adafruit_max31865.MAX31865(spi,cs1,wires=4, rtd_nominal=100.01, ref_resistor=430)

#cs2 = digitalio.DigitalInOut(board.D12)
#sensor2 = adafruit_max31865.MAX31865(spi,cs2,wires=4, rtd_nominal=99.99, ref_resistor=430)

cs = digitalio.DigitalInOut(board.D5)
max31855 = adafruit_max31855.MAX31855(spi, cs)

while True:
    print('Temperature RTD 1: {0:0.3f}C'.format(sensor1.temperature))
    #print('Temperature RTD 2: {0:0.3f}C'.format(sensor2.temperature))
    print('Temperature Thermocouple: {0:0.3f}C'.format(max31855.temperature))
    #print('Resistance 1: {0:0.3f} Ohms'.format(sensor1.resistance))
    #print('Resistance 2: {0:0.3f} Ohms'.format(sensor2.resistance))
    time.sleep(1)


