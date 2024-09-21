from machine import Pin, I2C, ADC
from time import sleep

from fusb302 import FUSB302
from pdstacc import PDStacc

########################
#
# Hardware Stuff
#
########################

# non-documented hardware stuff for a specific board I got going on
# glad I've gotten to that point ^~^
p_5_a = Pin(2, Pin.OUT, value=0)
p_5_m = Pin(7, Pin.OUT, value=0)
p_vin = Pin(3, Pin.OUT, value=0)
p_discharge = Pin(6, Pin.OUT, value=0)
p_5_m.off()
p_5_a.off()
p_vin.off()
p_discharge.on()
p_led_1 = Pin(9, Pin.OUT, value=0)
p_led_2 = Pin(15, Pin.OUT, value=0)

i2c = I2C(sda=Pin(18), scl=Pin(19), id=1, freq=400000)
print(i2c.scan())

a = ADC(Pin(28))
print(a.read_u16())

int_p = Pin(20, Pin.IN, Pin.PULL_UP)

fusb = FUSB302(i2c, int_p=int_p)
stacc = PDStacc(fusb)

def get_adc_vbus():
    return (3.3*11*a.read_u16())/65536

print(get_adc_vbus(), "V")

def source_sanity_check():
    # sanity check
    # currently, both 5V and VIN pins are supposed to be shut off
    vbus_v = get_adc_vbus()
    if vbus_v > 1:
        # enable discharge FET and wait for VBUS to discharge
        print("VBUS is at {}, has to be discharged".format(vbus_v))
        p_discharge.on()
        sleep(0.3)
        vbus_v = get_adc_vbus()
        if vbus_v > 1:
            # blink and enter error state
            # maybe a FET is borked, maybe something else
            ## remove all pullups and pulldowns? TODO
            print("VBUS is still at {}, can't be discharged".format(vbus_v))
            while True:
                p_led_1.toggle()
                sleep(0.3)
                # infinite loop; TODO: add checks in case of longer discharge
    else:
        print("VBUS is at {}".format(vbus_v))

source_sanity_check()

def set_power_rail(rail):
    rail = rail.lower()
    p_led_1.off(); p_led_2.off()
    if rail == "off":
        p_5_m.off()
        p_5_a.off()
        p_vin.off()
        p_discharge.on()
    elif rail == "5v":
        p_vin.off()
        p_discharge.on()
        p_5_a.on()
        p_5_m.on()
        p_discharge.off()
    elif rail == "vin":
        p_5_m.off()
        p_discharge.off()
        p_5_a.on()
        p_vin.on()
        p_5_a.off()
        p_led_1.on(); p_led_2.off()
    else:
        # catch-all:
        p_5_m.off()
        p_5_a.off()
        p_vin.off()
        p_discharge.on()
        raise Exception("rail has to be one of 'off', '5v' or 'vin', was '{}'".format(rail))

# callbacks for main loop

def validate_profile(profile, d):
    if profile not in range(len(psu_advertisement)):
        set_power_rail('off')
    else:
        return True

def switch_to_profile(profile, d):
    if profile == 0:
        set_power_rail('5V')
    elif profile == 1:
        set_power_rail('VIN')

def en_5v_power_rail():
    set_power_rail('5V')

stacc.validate_profile_cb = validate_profile
stacc.switch_to_profile_cb = switch_to_profile
stacc.en_5v_power_rail_cb = en_5v_power_rail

psu_advertisement = stacc.create_pdo('fixed', 5000, 1500, 0, 8) + \
                    stacc.create_pdo('fixed', 19000, 5000, 0, 0)

########################
#
# it gets real here
#
########################

stacc.init_fusb()
while True:
    try:
        set_power_rail('off')
        stacc.setup_source()
        stacc.flow_source()
        # after flow_source exits, setup_source runs again
        # this would best work as an actual explicit state machine
    except KeyboardInterrupt:
        # lets you exit the loop on ctrlc
        print("CtrlC again to exit")
        sleep(1)
