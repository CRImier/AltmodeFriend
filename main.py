from machine import Pin, I2C, ADC
from time import sleep

i2c = I2C(sda=Pin(18), scl=Pin(19), id=1)
print(i2c.scan())

a = ADC(Pin(28))
print(a.read_u16())

int_p = Pin(20, Pin.IN, Pin.PULL_UP)
int = int_p.value

def get_adc_vbus():
    return (3.3*11*a.read_u16())/65536

def reset():
    # reset the entire FUSB
    i2c.writeto_mem(0x22, 0xc, bytes([0b1]))

def reset_pd():
    # resets the FUSB PD logic
    i2c.writeto_mem(0x22, 0xc, bytes([0b10]))

def unmask_all():
    # unmasks all interrupts
    i2c.writeto_mem(0x22, 0xa, bytes([0b0]))
    i2c.writeto_mem(0x22, 0xe, bytes([0b0]))
    i2c.writeto_mem(0x22, 0xf, bytes([0b0]))

def cc_current():
    # show measured CC level interpreted as USB-C current levels
    return i2c.readfrom_mem(0x22, 0x40, 1)[0] & 0b11

def read_cc(cc):
    # enable a CC pin for reading
    assert(cc in [1, 2])
    x = i2c.readfrom_mem(0x22, 0x02, 1)[0]
    x1 = x
    clear_mask = ~0b1100 & 0xFF
    x &= clear_mask
    mask = 0b1000 if cc == 2 else 0b100
    x |= mask
    print('rc', bin(x1), bin(x), cc)
    i2c.writeto_mem(0x22, 0x02, bytes((x,)) )

def measure():
    # read CC pins and see which one senses the pullup
    read_cc(1)
    sleep(0.001)
    cc1_c = cc_current()
    read_cc(2)
    sleep(0.001)
    cc2_c = cc_current()
    cc = [1, 2][cc1_c < cc2_c]
    print('m', bin(cc1_c), bin(cc2_c), cc)
    if cc1_c == cc2_c:
        return 0
    return cc

def set_controls():
    # boot: 0b00100100
    #ctrl0 = 0b00001100 # unmask all interrupts; don't autostart TX.. set pullup current to 3A? TODO
    ctrl0 = 0b00000000 # unmask all interrupts; don't autostart TX.. disable pullup current
    i2c.writeto_mem(0x22, 0x06, bytes((ctrl0,)) )
    # boot: 0b00000110
    ctrl3 = 0b00000111 # enable automatic packet retries
    i2c.writeto_mem(0x22, 0x09, bytes((ctrl3,)) )
    # boot: 0b00000010
    #ctrl2 = 0b00000000 # disable DRP toggle. setting it to Do Not Use o_o ???
    #i2c.writeto_mem(0x22, 0x08, bytes((ctrl2,)) )

def flush_receive():
    ctrl1 = 0b00000100 # flush receive
    i2c.writeto_mem(0x22, 0x07, bytes((ctrl1,)) )

def flush_transmit():
    ctrl0 = 0b01000100 # flush transmit
    i2c.writeto_mem(0x22, 0x06, bytes((ctrl0,)) )

def enable_tx(cc):
    # enables switch on either CC1 or CC2
    x = i2c.readfrom_mem(0x22, 0x03, 1)[0]
    x1 = x
    mask = 0b10 if cc == 2 else 0b1
    x &= 0b11111100 # clearing both TX bits
    x |= mask
    x |= 0b100
    print('et', bin(x1), bin(x), cc)
    i2c.writeto_mem(0x22, 0x03, bytes((x,)) )

def power():
    # enables all power circuits
    x = i2c.readfrom_mem(0x22, 0x0b, 1)[0]
    mask = 0b1111
    x |= mask
    i2c.writeto_mem(0x22, 0x0b, bytes((x,)) )

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

def rxb_state():
    st = i2c.readfrom_mem(0x22, 0x41, 1)[0]
    return ((st & 0b110000) >> 4, (st & 0b11000000) >> 6)

def get_rxb(l=80):
    # show measured CC level interpreted as USB-C current levels
    return i2c.readfrom_mem(0x22, 0x43, l)

def hard_reset():
    i2c.writeto_mem(0x22, 0x09, bytes([0b1000000]))
    return i2c.readfrom_mem(0x22, 0x09, 1)

# shorthands

polarity_values = (
  (0, 0),   # 000: logic still running
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

# test sketch - sets up for comms

#sleep(1)

reset()
power()
unmask_all()
set_controls()

def find_cc():
    cc = measure()
    flush_receive()
    enable_tx(cc)
    read_cc(cc)
    flush_transmit()
    flush_receive()
    reset_pd()
    return cc

def wait():
  while True:
    s = i2c.readfrom_mem(0x22, 0x3c, 7)
    print(s, rxb_state())
    sleep(0.5)

t_33 = b'\xe0\xa1a,\x91\x01\x08,\xd1\x02\x00\x13\xc1\x03\x00\xdc\xb0\x04\x00\xa5@\x06\x00<!\xdc\xc0H\xc6\xe7\xc6\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
t_fr = b'\xe0\xa1Q,\x91\x01\x08,\xd1\x02\x00,\xb1\x04\x00,A\x06\x00<!\xa4\xc9\xf5\x9b\x8bU\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
t_bl = b'\xe0\xa11,\x91\x01\x08\xc8\xd0\x02\x08\x96\xc0\x03\x08.\x0c\xbe\xda\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
t_lp = b"\xe0\xa1\x11,\x91\x01'\xb1\x9b&\x94\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"

l = [t_33, t_fr, t_bl, t_lp]

def myhex(b, j=" "):
    l = []
    for e in b:
        e = hex(e)[2:].upper()
        if len(e) < 2:
            e = ("0"*(2-len(e)))+e
        l.append(e)
    return j.join(l)

def mybin(b, j=" "):
    l = []
    for e in b:
        e = bin(e)[2:].upper()
        if len(e) < 8:
            e = ("0"*(8-len(e)))+e
        l.append(e)
    return j.join(l)

pdo_types = ['fixed', 'batt', 'var', 'pps']
pps_types = ['spr', 'epr', 'res', 'res']

def parse_pdo(pdo):
    pdo_t = pdo_types[pdo[3] >> 6]
    if pdo_t == 'fixed':
        current_h = pdo[1] & 0b11
        current_b = ( current_h << 8 ) | pdo[0]
        current = current_b * 10
        voltage_h = pdo[2] & 0b1111
        voltage_b = ( voltage_h << 6 ) | (pdo[1] >> 2)
        voltage = voltage_b * 50
        peak_current = (pdo[2] >> 4) & 0b11
        return (pdo_t, voltage, current, peak_current, pdo[3])
    elif pdo_t == 'batt':
        # TODO
        return ('batt', pdo)
    elif pdo_t == 'var':
        current_h = pdo[1] & 0b11
        current = ( current_h << 8 ) | pdo[0]*10
        # TODO
        return ('var', current, pdo)
    elif pdo_t == 'pps':
        t = (pdo[3] >> 4) & 0b11
        limited = (pdo[3] >> 5) & 0b1
        max_voltage_h = pdo[3] & 0b1
        max_voltage_b = (max_voltage_h << 7) | pdo[2] >> 1
        max_voltage = max_voltage_b * 100
        min_voltage = pdo[1] * 100
        max_current_b = pdo[0] & 0b1111111
        max_current = max_current_b * 50
        return ('pps', pps_types[t], max_voltage, min_voltage, max_current, limited)

def read_pdos():
    pdo_list = []
    header = get_rxb(1)[0]
    assert(header == 0xe0)
    b1, b0 = get_rxb(2)
    print(hex(b1), hex(b0))
    pdo_count = (b0 >> 4) & 0b111
    read_len = pdo_count*4
    pdos = get_rxb(read_len)
    crc = get_rxb(4)
    for pdo_i in range(pdo_count):
        pdo_bytes = pdos[(pdo_i*4):][:4]
        print(myhex(pdo_bytes))
        parsed_pdo = parse_pdo(pdo_bytes)
        pdo_list.append(parsed_pdo)
    return pdo_list

def request_pdo(num, current, max_current):
    sop_seq = [0x12, 0x12, 0x12, 0x13, 0x80]
    eop_seq = [0xff, 0x14, 0xfe, 0xa1]
    obj_count = 1
    pdo_len = 2 + (4*obj_count)
    pdo = [0 for i in range(pdo_len)]

    pdo[0] |= 0b10 << 6 # PD 3.0
    pdo[0] |= 0b00010 # request

    pdo[1] |= obj_count << 4

    max_current_b = max_current // 10
    max_current_l = max_current_b & 0xff
    max_current_h = max_current_b >> 8
    pdo[2] = max_current_l
    pdo[3] |= max_current_h

    current_b = current // 10
    current_l = current_b & 0x3f
    current_h = current_b >> 6
    pdo[3] |= current_l << 2
    pdo[4] |= current_h

    pdo[5] |= (num+1) << 4 # object position
    pdo[5] |= 0b1 # no suspend

    sop_seq[4] |= pdo_len

    print(myhex(sop_seq))
    print(myhex(pdo))
    print(myhex(eop_seq))

    i2c.writeto_mem(0x22, 0x43, bytes(sop_seq) )
    i2c.writeto_mem(0x22, 0x43, bytes(pdo) )
    i2c.writeto_mem(0x22, 0x43, bytes(eop_seq) )


cc = find_cc()
sleep(0)
wait()
