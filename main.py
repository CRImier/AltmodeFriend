from machine import Pin, I2C, ADC
from time import sleep

i2c = I2C(sda=Pin(18), scl=Pin(19), id=1)
print(i2c.scan())

a = ADC(Pin(28))
print(a.read_u16())

int_p = Pin(20, Pin.IN, Pin.PULL_UP)
int = int_p.value

def reset():
    # resets both the PD logic and the FUSB just in case
    i2c.writeto_mem(0x22, 0xc, bytes([0b11]))

def measure():
    # enables measurement blocks on CC1 and CC2
    x = i2c.readfrom_mem(0x22, 0x02, 1)[0]
    mask = 0b1100
    x |= mask
    i2c.writeto_mem(0x22, 0x02, bytes((x,)) )

def enable_tx(cc):
    # enables switch on either CC1 or CC2
    x = i2c.readfrom_mem(0x22, 0x03, 1)[0]
    mask = 0b10 if cc == 2 else 0b1
    x &= 0b11111100 # clearing both TX bits
    x |= mask
    x |= 0b100
    i2c.writeto_mem(0x22, 0x03, bytes((x,)) )

def power():
    # enables all power circuits
    x = i2c.readfrom_mem(0x22, 0x0b, 1)[0]
    mask = 0b1111
    x |= mask
    i2c.writeto_mem(0x22, 0x0b, bytes((x,)) )

def toggle():
    # turn autonomous toggle on, then off
    # better way to do this?
    i2c.writeto_mem(0x22, 0x8, bytes([0b10]))
    i2c.writeto_mem(0x22, 0x8, bytes([0b11]))

def polarity():
    # reads polarity and role bits from STATUS1A
    return (i2c.readfrom_mem(0x22, 0x3d, 1)[0] >> 3) & 0b111
    #'0b110001'

def interrupts():
    # show interrupt
    return i2c.readfrom_mem(0x22, 0x3e, 2)+i2c.readfrom_mem(0x22, 0x42, 1)

def clear_interrupts():
    # clear interrupt
    i2c.writeto_mem(0x22, 0x3e, bytes([0]))
    i2c.writeto_mem(0x22, 0x42, bytes([0]))

def cc_current():
    # show measured CC level interpreted as USB-C current levels
    return i2c.readfrom_mem(0x22, 0x40, 1)[0] & 0b11

def rxb_state():
    st = i2c.readfrom_mem(0x22, 0x41, 1)[0]
    return ((st & 0b110000) >> 4, (st & 0b11000000) >> 6)

def get_rxb():
    # show measured CC level interpreted as USB-C current levels
    return i2c.readfrom_mem(0x22, 0x43, 80)

# shorthands

polarity_values = (
  (0, 0), # 000: logic still running
  (1, 0),   # 001: cc1, src
  (2, 0),   # 010: cc2, src
  (-1, -1), # 011: unknown
  (-1, -1), # 100: unknown
  (1, 1),   # 101: cc1, snk
  (2, 1),   # 110: cc2, snk
  (0, 2),   # 111: audio accessory
)

current_values = (
    "Ra/low",
    "Rd-Default",
    "Rd-1.5",
    "Rd-3.0"
)

def p_pol():
    return polarity_values[polarity()]

def p_int(a=None):
    if a is None:
        a = interrupts()
    return [bin(x) for x in a]

def p_cur():
    return current_values[cc_current()]

# test sketch - prints polarity when plug-in is detected

reset()
measure()
power()

# some random packet I got and am gonna learn to parse
t = b'\xe0\xa1a,\x91\x01\x08,\xd1\x02\x00\x13\xc1\x03\x00\xdc\xb0\x04\x00\xa5@\x06\x00<!\xdc\xc0H\xc6\xe7\xc6\xe0\xa1a,\x91\x01\x08,\xd1\x02\x00\x13\xc1\x03\x00\xdc\xb0\x04\x00\xa5@\x06\x00<!\xdc\xc0H\xc6\xe7\xc6\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
ts = []
tsn = ""

def p_rxc():
    global tsn
    if rxb_state()[0] != 2:
        tsn = get_rxb()
        ts.append(tsn)
        print("Received:", tsn)

while True:
    a = interrupts()
    while not any(a):
        a = interrupts()
        sleep(0.1)
    print(p_int(a))
    toggle()
    while not polarity():
        sleep(0.1)
    print("pol:", p_pol(), "cur:", p_cur(), "rxb:", rxb_state())
    p_rxc()
    #enable_tx(p_pol()[0])
    clear_interrupts()

# enable_tx(p_pol()[0])
