from machine import Pin, I2C, ADC
from time import sleep

from fusb302 import FUSB302

########################
#
# Hardware Stuff (exclusively)
# zero stack required for now
#
########################

# look into git history if you need this file annotated with lower-level code (i2c reads/writes)

i2c = I2C(sda=Pin(18), scl=Pin(19), id=1, freq=400000)
#import smbus
#i2c = smbus.SMBus(1)

fusb = FUSB302(i2c)

def get_adc_vbus():
    return (3.3*11*a.read_u16())/65536

fusb.host_current = 0b01
fusb.hard_reset()
fusb.reset()
fusb.power()
fusb.unmask_all()

fusb.set_controls_sink()

# read before we start
print(bin( fusb.interrupt_a() ))

fusb.set_toggle(True)

def mask_all_except_toggle():
    fusb.i2c_write(fusb.REG_MASK, bytes((0xfe,)) )
    fusb.i2c_write(fusb.REG_MASKA, bytes((0xbf,)) )
    fusb.i2c_write(fusb.REG_MASKB, bytes((0x01,)) )

mask_all_except_toggle()

while True:
    inta = fusb.interrupt_a()
    if (inta >> 6 & 0b1):
        print("int triggered")
        pol = fusb.str_pol()
        print(pol, fusb.polarity_names[pol[1]])
        if pol != (0, 0):
            print("pol found")
            print(list(map(bin, fusb.interrupts() )))
            # disable toggle logic to let it re-trigger, wait a little for uh idk what reason
            fusb.set_toggle(False)
            sleep(0.1)
            # re-set the toggle
            fusb.set_controls_sink()
            fusb.set_toggle(True)
            mask_all_except_toggle()
        else:
            print("other int", list(map(bin, fusb.interrupts() )))
    sleep(1)
