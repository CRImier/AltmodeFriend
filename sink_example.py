from machine import Pin, I2C, ADC
from time import sleep

from fusb302 import FUSB302
from pdstacc import PDStacc

########################
#
# Hardware Stuff
#
########################

#vl_pol = Pin(2, Pin.OUT, value=0)
#vl_amsel = Pin(3, Pin.OUT, value=1)
#vl_en = Pin(4, Pin.OUT, value=1)

#bl_en = Pin(10, Pin.OUT, value=1)
#bl_pwm = Pin(15, Pin.OUT, value=1)

i2c = I2C(sda=Pin(18), scl=Pin(19), id=1, freq=400000)
print(i2c.scan())
int_p = Pin(20, Pin.IN, Pin.PULL_UP)

a = ADC(Pin(28))
print(a.read_u16())

fusb = FUSB302(i2c, int_p=int_p)
stacc = PDStacc(fusb)

def get_adc_vbus():
    return (3.3*11*a.read_u16())/65536

print(get_adc_vbus(), "V")

def process_accept(d):
    # callback from sink loop, letting you take note when your profile is accepted
    print(get_adc_vbus(), "V")

stacc.process_accept_cb = process_accept

###################################
#
# Power profile selection examples
#
###################################

# simple example - pick a fixed PDO with voltage of 20, and request maximum current available

expected_voltage = 20
#expected_current = 1000

def select_pdo_for_voltage(pdos, voltage=None, current=None):
    if voltage is None: voltage = expected_voltage
    if current is None: current = expected_current
    for i, pdo in enumerate(pdos):
        if pdo[0] != 'fixed': # skipping variable PDOs
            continue
        t, pdo_voltage, max_current, oc, flags = pdo
        if pdo_voltage//1000 == voltage:
            current = current if current else max_current
            return i, current

# Another example

expected_resistance = 8

def select_pdo_for_resistance(pdos, resistance = None):
    # finding a PDO with maximum extractable power
    # for a given static resistance,
    # while making sure that we don't overcurrent the PSU
    # calculation storage lists
    if resistance is None: resistance = expected_resistance
    power_levels = []
    currents = []
    for pdo in pdos:
        if pdo[0] != 'fixed': # skipping variable PDOs for now
            # keeping indices in sync
            power_levels.append(0); currents.append(0)
            continue
        t, voltage, max_current, oc, flags = pdo
        voltage = voltage / 1000
        max_current = max_current / 1000
        # calculating the power needed
        current = voltage / resistance
        current = current * 1.10 # adding 10% leeway
        if current > max_current: # current too high, skipping
            # keeping indices in sync
            power_levels.append(0); currents.append(0)
            continue
        power = voltage * current
        power_levels.append(power)
        currents.append(int(current*1000))
    # finding the maximum power level
    i = power_levels.index(max(power_levels))
    # returning the PDO index + current we'd need
    return i, currents[i]

# example function used by default
stacc.select_pdo = select_pdo_for_voltage

########################
#
# it gets real here
#
########################

stacc.init_fusb()
while True:
    try:
        stacc.setup_sink()
        stacc.flow_sink()
        # after flow_sink exits, setup_sink runs again
        # this would best work as an actual explicit state machine
    except KeyboardInterrupt:
        # lets you exit the loop on ctrlc
        print("CtrlC again to exit")
        sleep(1)
