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
#print(i2c.scan())
#int_p = Pin(20, Pin.IN, Pin.PULL_UP)

#fusb = FUSB302(i2c, int_p=int_p)
fusb = FUSB302(i2c, int_p=None)

def get_adc_vbus():
    return (3.3*11*a.read_u16())/65536

fusb.host_current = 0b01
fusb.hard_reset()
fusb.reset()
fusb.power()
fusb.unmask_all()

#ctrl0 = 0b00000100
#ctrl2 = 0b00101011

#fusb.bus.writeto_mem(fusb.addr, fusb.REG_CONTROL0, bytes((ctrl0,)) )
fusb.set_controls_sink()

# read before we start
print(bin( fusb.interrupt_a() ))

#fusb.bus.writeto_mem(fusb.addr, fusb.REG_CONTROL2, bytes((ctrl2,)) )
fusb.set_toggle(True)

def mask_all_except_toggle():
    fusb.bus.writeto_mem(fusb.addr, fusb.REG_MASK, bytes((0xfe,)) )
    fusb.bus.writeto_mem(fusb.addr, fusb.REG_MASKA, bytes((0xbf,)) )
    fusb.bus.writeto_mem(fusb.addr, fusb.REG_MASKB, bytes((0x01,)) )

mask_all_except_toggle()

while True:
    #inta = fusb.bus.readfrom_mem(fusb.addr, fusb.REG_INTERRUPTA, 1)[0]
    inta = fusb.interrupt_a()
    if (inta >> 6 & 0b1):
        print("int triggered")
        #print(bin( inta ))
        # status1a = fusb.bus.readfrom_mem(fusb.addr, fusb.REG_STATUS1A, 1)[0]
        # toggle_state = (status1a >> 3) & 0b111
        #toggle_state = fusb.polarity()
        # pol = polarity_values[toggle_state]
        pol = fusb.print_pol()
        #print(bin(inta), bin( status1a ), pol)
        print(pol)
        if pol != (0, 0):
            print("pol found")
            #print(bin( fusb.bus.readfrom_mem(fusb.addr, fusb.REG_INTERRUPTA, 1)[0] ))
            #print(bin( fusb.bus.readfrom_mem(fusb.addr, fusb.REG_INTERRUPTB, 1)[0] ))
            #print(bin( fusb.bus.readfrom_mem(fusb.addr, fusb.REG_INTERRUPT, 1)[0] ))
            print(list(map(bin, fusb.interrupts() )))
            # disable toggle logic
            #fusb.bus.writeto_mem(fusb.addr, fusb.REG_CONTROL2, bytes((0b00101010,)) )
            fusb.set_toggle(False)
            # re-set the toggle
            sleep(0.1)
            #fusb.bus.writeto_mem(fusb.addr, fusb.REG_CONTROL0, bytes((ctrl0,)) )
            fusb.set_controls_sink()
            #fusb.bus.writeto_mem(fusb.addr, fusb.REG_CONTROL2, bytes((ctrl2,)) )
            fusb.set_toggle(True)
            mask_all_except_toggle()
        else:
            print("other int", list(map(bin, fusb.interrupts() )))
    sleep(1)




"""
0b0 0b0
0b0 0b0
0b0 0b0
0b1000000 0b1000
0b0 0b1000
0b0 0b1000
0b0 0b1000
0b0 0b1000
0b0 0b1000
0b0 0b1000
"""
"""
    try:
        print("setup_sink")
        stacc.setup_sink()
        print("flow_sink")
        stacc.flow_sink()
        # after flow_sink exits, setup_sink runs again
        # this handles stack reset after unplug
        # this would best work as an actual explicit state machine
    except KeyboardInterrupt:
        # lets you exit the loop on ctrlc
        print("CtrlC again to exit")
        sleep(1)
"""
