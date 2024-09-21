from machine import Pin, I2C, ADC
from time import sleep

from fusb302 import FUSB302
from pdstacc import PDStacc

########################
#
# Hardware Stuff
#
########################

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

"""
Here's the summary of what you need to care about.
You must pick a PD profile within 500ms (or so)
after a PSU sends you the Source_Capabilities
message. As a result, the responder function has to be quick.
You cannot do user input in this function, or any long-winded processing.

If you don't pick a profile within the timeout, the PSU will shut off the default 5V power.
This is why the select_pdo functions are short and sweet.

Remember - after you request any profile, you can re-request profiles arbitrarily.
So, if you need to pick user-chosen profiles, you can initially pick the 5V profile,
and then take your time to think about it, sending a new Request as soon as you want to.

The last received PDOs are always available as `stacc.pdos`.
"""

# simple example - pick a fixed PDO with voltage of 5V, and request maximum current available

expected_voltage = 20
#expected_current = 1000

def select_pdo_for_voltage(pdos, voltage=5):
    """
    request the 5V profile and that's it
    requests the maximum current available
    """
    for i, pdo in enumerate(pdos):
        if pdo[0] != 'fixed': # skipping variable PDOs
            continue
        t, pdo_voltage, max_current, oc, flags = pdo
        if pdo_voltage//1000 == voltage:
            return i, max_current

# setting our callback to be used
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
        # this handles stack reset after unplug
        # this would best work as an actual explicit state machine
    except KeyboardInterrupt:
        # lets you exit the loop on ctrlc
        print("CtrlC again to exit")
        sleep(1)
