from machine import Pin, I2C, ADC
from time import sleep, ticks_us, ticks_diff
import sys

is_source = True

if is_source:
    # non-documented hardware stuff.
    # This is starting to get to the point that things need to be pulled out into a separate library.
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
int_g = int_p.value

def get_adc_vbus():
    return (3.3*11*a.read_u16())/65536

print(get_adc_vbus(), "V")

if is_source:
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

########################
#
# FUSB-specific code
#
########################

FUSB302_I2C_SLAVE_ADDR = 0x22
TCPC_REG_DEVICE_ID = 0x01
TCPC_REG_SWITCHES0 = 0x02
TCPC_REG_SWITCHES1 = 0x03
TCPC_REG_MEASURE = 0x04
TCPC_REG_CONTROL0 = 0x06
TCPC_REG_CONTROL1 = 0x07
TCPC_REG_CONTROL2 = 0x08
TCPC_REG_CONTROL3 = 0x09
TCPC_REG_MASK = 0x0A
TCPC_REG_POWER = 0x0B
TCPC_REG_RESET = 0x0C
TCPC_REG_MASKA = 0x0E
TCPC_REG_MASKB = 0x0F
TCPC_REG_STATUS0A = 0x3C
TCPC_REG_STATUS1A = 0x3D
TCPC_REG_INTERRUPTA = 0x3E
TCPC_REG_INTERRUPTB = 0x3F
TCPC_REG_STATUS0 = 0x40
TCPC_REG_STATUS1 = 0x41
TCPC_REG_INTERRUPT = 0x42
TCPC_REG_FIFOS = 0x43

def reset():
    # reset the entire FUSB
    i2c.writeto_mem(FUSB302_I2C_SLAVE_ADDR, TCPC_REG_RESET, bytes([0b1]))

def reset_pd():
    # resets the FUSB PD logic
    i2c.writeto_mem(FUSB302_I2C_SLAVE_ADDR, TCPC_REG_RESET, bytes([0b10]))

def unmask_all():
    # unmasks all interrupts
    i2c.writeto_mem(FUSB302_I2C_SLAVE_ADDR, TCPC_REG_MASK, bytes([0b0]))
    i2c.writeto_mem(FUSB302_I2C_SLAVE_ADDR, TCPC_REG_MASKA, bytes([0b0]))
    i2c.writeto_mem(FUSB302_I2C_SLAVE_ADDR, TCPC_REG_MASKB, bytes([0b0]))

def cc_current():
    # show measured CC level interpreted as USB-C current levels
    return i2c.readfrom_mem(FUSB302_I2C_SLAVE_ADDR, TCPC_REG_STATUS0, 1)[0] & 0b11

def read_cc(cc):
    # enable a CC pin for reading
    assert(cc in [0, 1, 2])
    x = i2c.readfrom_mem(FUSB302_I2C_SLAVE_ADDR, TCPC_REG_SWITCHES0, 1)[0]
    x1 = x
    clear_mask = ~0b1100 & 0xFF
    x &= clear_mask
    mask = [0b0, 0b100, 0b1000][cc]
    x |= mask
    #print('TCPC_REG_SWITCHES0: ', bin(x1), bin(x), cc)
    i2c.writeto_mem(FUSB302_I2C_SLAVE_ADDR, TCPC_REG_SWITCHES0, bytes((x,)) )

def enable_pullups():
    # enable host pullups on CC pins, disable pulldowns
    x = i2c.readfrom_mem(0x22, 0x02, 1)[0]
    x |= 0b11000000
    i2c.writeto_mem(0x22, 0x02, bytes((x,)) )

def set_mdac(value):
    x = i2c.readfrom_mem(0x22, 0x04, 1)[0]
    x &= 0b11000000
    x |= value
    i2c.writeto_mem(0x22, 0x04, bytes((x,)) )

def enable_sop():
    # enable reception of SOP'/SOP" messages
    x = i2c.readfrom_mem(FUSB302_I2C_SLAVE_ADDR, TCPC_REG_CONTROL1, 1)[0]
    mask = 0b1100011
    x |= mask
    i2c.writeto_mem(FUSB302_I2C_SLAVE_ADDR, TCPC_REG_CONTROL1, bytes((x,)) )

def disable_pulldowns():
    x = i2c.readfrom_mem(FUSB302_I2C_SLAVE_ADDR, TCPC_REG_SWITCHES0, 1)[0]
    clear_mask = ~0b11 & 0xFF
    x &= clear_mask
    i2c.writeto_mem(FUSB302_I2C_SLAVE_ADDR, TCPC_REG_SWITCHES0, bytes((x,)) )

def measure_sink(debug=False):
    # read CC pins and see which one senses the pullup
    read_cc(1)
    sleep(0.001)
    cc1_c = cc_current()
    read_cc(2)
    sleep(0.001)
    cc2_c = cc_current()
    # picking the CC pin depending on which pin can detect a pullup
    cc = [1, 2][cc1_c < cc2_c]
    if debug: print('m', bin(cc1_c), bin(cc2_c), cc)
    if cc1_c == cc2_c:
        return 0
    return cc

def measure_source(debug=False):
    # read CC pins and see which one senses the correct host current
    read_cc(1)
    sleep(0.001)
    cc1_c = cc_current()
    read_cc(2)
    sleep(0.001)
    cc2_c = cc_current()
    if cc1_c == host_current:
        cc = 1
    elif cc2_c == host_current:
        cc = 2
    else:
        cc = 0
    if debug: print('m', bin(cc1_c), bin(cc2_c), cc)
    return cc

def set_controls_sink():
    # boot: 0b00100100
    ctrl0 = 0b00000000 # unmask all interrupts; don't autostart TX.. disable pullup current
    i2c.writeto_mem(FUSB302_I2C_SLAVE_ADDR, TCPC_REG_CONTROL0, bytes((ctrl0,)) )
    # boot: 0b00000110
    ctrl3 = 0b00000111 # enable automatic packet retries
    i2c.writeto_mem(FUSB302_I2C_SLAVE_ADDR, TCPC_REG_CONTROL3, bytes((ctrl3,)) )

host_current=0b10

def set_controls_source():
    # boot: 0b00100100
    ctrl0 = 0b00000000 # unmask all interrupts; don't autostart TX
    ctrl0 |= host_current << 2 # set host current advertisement pullups
    i2c.writeto_mem(FUSB302_I2C_SLAVE_ADDR, TCPC_REG_CONTROL0, bytes((ctrl0,)) )
    i2c.writeto_mem(0x22, 0x06, bytes((ctrl0,)) )
    # boot: 0b00000110
    ctrl3 = 0b00000110 # no automatic packet retries
    i2c.writeto_mem(FUSB302_I2C_SLAVE_ADDR, TCPC_REG_CONTROL3, bytes((ctrl3,)) )
    # boot: 0b00000010
    #ctrl2 = 0b00000000 # disable DRP toggle. setting it to Do Not Use o_o ???
    #i2c.writeto_mem(FUSB302_I2C_SLAVE_ADDR, TCPC_REG_CONTROL2, bytes((ctrl2,)) )

def set_wake(state):
    # boot: 0b00000010
    ctrl2 = i2c.readfrom_mem(0x22, 0x08, 1)[0]
    clear_mask = ~(1 << 3) & 0xFF
    ctrl2 &= clear_mask
    if state:
        ctrl2 | (1 << 3)
    i2c.writeto_mem(0x22, 0x08, bytes((ctrl2,)) )

def flush_receive():
    x = i2c.readfrom_mem(FUSB302_I2C_SLAVE_ADDR, TCPC_REG_CONTROL1, 1)[0]
    mask = 0b100 # flush receive
    x |= mask
    i2c.writeto_mem(FUSB302_I2C_SLAVE_ADDR, TCPC_REG_CONTROL1, bytes((x,)) )

def flush_transmit():
    x = i2c.readfrom_mem(FUSB302_I2C_SLAVE_ADDR, TCPC_REG_CONTROL0, 1)[0]
    mask = 0b01000000 # flush transmit
    x |= mask
    i2c.writeto_mem(FUSB302_I2C_SLAVE_ADDR, TCPC_REG_CONTROL0, bytes((x,)) )

def enable_tx(cc):
    # enables switch on either CC1 or CC2
    x = i2c.readfrom_mem(FUSB302_I2C_SLAVE_ADDR, TCPC_REG_SWITCHES1, 1)[0]
    x1 = x
    mask = 0b10 if cc == 2 else 0b1
    x &= 0b10011100 # clearing both TX bits and revision bits
    x |= mask
    x |= 0b100
    x |= 0b10 << 5 # revision 3.0
    #print('et', bin(x1), bin(x), cc)
    i2c.writeto_mem(FUSB302_I2C_SLAVE_ADDR, TCPC_REG_SWITCHES1, bytes((x,)) )

def set_roles(power_role = 0, data_role = 0):
    x = i2c.readfrom_mem(0x22, 0x03, 1)[0]
    x &= 0b01101111 # clearing both role bits
    x |= power_role << 7
    x |= data_role << 7
    i2c.writeto_mem(0x22, 0x03, bytes((x,)) )

def power():
    # enables all power circuits
    x = i2c.readfrom_mem(FUSB302_I2C_SLAVE_ADDR, TCPC_REG_POWER, 1)[0]
    mask = 0b1111
    x |= mask
    i2c.writeto_mem(FUSB302_I2C_SLAVE_ADDR, TCPC_REG_POWER, bytes((x,)) )

def polarity():
    # reads polarity and role bits from STATUS1A
    return (i2c.readfrom_mem(FUSB302_I2C_SLAVE_ADDR, TCPC_REG_STATUS1A, 1)[0] >> 3) & 0b111
    #'0b110001'

def interrupts():
    # return all interrupt registers
    return i2c.readfrom_mem(FUSB302_I2C_SLAVE_ADDR, TCPC_REG_INTERRUPTA, 2)+i2c.readfrom_mem(FUSB302_I2C_SLAVE_ADDR, TCPC_REG_INTERRUPT, 1)

# interrupts are cleared just by reading them, it seems
#def clear_interrupts():
#    # clear interrupt
#    i2c.writeto_mem(FUSB302_I2C_SLAVE_ADDR, TCPC_REG_INTERRUPTA, bytes([0]))
#    i2c.writeto_mem(FUSB302_I2C_SLAVE_ADDR, TCPC_REG_INTERRUPT, bytes([0]))

# this is a way better way to do things than the following function -
# the read loop should be ported to this function, and the next ome deleted
def rxb_state():
    # get read buffer interrupt states - (rx buffer empty, rx buffer full)
    st = i2c.readfrom_mem(FUSB302_I2C_SLAVE_ADDR, TCPC_REG_STATUS1, 1)[0]
    return ((st & 0b100000) >> 5, (st & 0b10000) >> 4)

# TODO: yeet
def rxb_state():
    st = i2c.readfrom_mem(FUSB302_I2C_SLAVE_ADDR, TCPC_REG_STATUS1, 1)[0]
    return ((st & 0b110000) >> 4, (st & 0b11000000) >> 6)

def get_rxb(l=80):
    # read from FIFO
    return i2c.readfrom_mem(FUSB302_I2C_SLAVE_ADDR, TCPC_REG_FIFOS, l)

def hard_reset():
    i2c.writeto_mem(FUSB302_I2C_SLAVE_ADDR, TCPC_REG_CONTROL3, bytes([0b1000000]))
    return i2c.readfrom_mem(FUSB302_I2C_SLAVE_ADDR, TCPC_REG_CONTROL3, 1)

def find_cc(fn=measure_sink, debug=False):
    cc = fn(debug=debug)
    flush_receive()
    enable_tx(cc)
    read_cc(cc)
    flush_transmit()
    flush_receive()
    #import gc; gc.collect()
    reset_pd()
    return cc

# FUSB toggle logic shorthands
# currently unused

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

########################
#
# USB-C stacc code
#
########################

pdo_requested = False
pdos = []
timing_start = 0
timing_end = 0

# set to -1 because it's incremented before each command is sent out
msg_id = -1

def increment_msg_id():
    global msg_id
    msg_id += 1
    if msg_id == 8: msg_id = 0
    return msg_id

def reset_msg_id():
    global msg_id
    msg_id = -1

sent_messages = []

def source_flow():
  global psu_advertisement, advertisement_counter, sent_messages
  psu_advertisement = create_pdo('fixed', 5000, 1500, 0, 8) + \
                       create_pdo('fixed', 19000, 5000, 0, 0)
  counter = 0
  reset_msg_id()
  sleep(0.3)
  print("sending advertisement")
  send_advertisement(psu_advertisement)
  advertisement_counter = 1
  profile_selected = False
  try:
   timeout = 0.00001
   while True:
    if rxb_state()[0] == 0: # buffer non-empty
        d = get_message()
        msg_types = control_message_types if d["c"] else data_message_types
        msg_name = msg_types[d["t"]]
        # now we do things depending on the message type that we received
        if msg_name == "GoodCRC": # example
            print("GoodCRC")
        elif msg_name == "Request":
            profile_selected = True
            process_psu_request(psu_advertisement, d)
        """elif msg_name == "Source_Capabilities":
            # need to request a PDO!
            pdos = get_pdos(d)
            pdo_i, current = select_pdo(pdos)
            # sending a message, need to increment message id
            request_fixed_pdo(pdo_i, current, current)
            # print("PDO requested!")
            pdo_requested = True
            sys.stdout.write(str(pdos))
            sys.stdout.write('\n')
        elif msg_name in ["Accept", "PS_RDY"]:
            print(get_adc_vbus(), "V")
        elif msg_name == "Vendor_Defined":
            parse_vdm(d)
            react_vdm(d)"""
        show_msg(d)
    for message in sent_messages:
        sys.stdout.write('> ')
        sys.stdout.write(myhex(message))
        sys.stdout.write('\n')
    sent_messages = []
    sleep(timeout) # so that ctrlc works
    counter += 1
    if counter == 10000:
        counter = 0
        if not profile_selected and advertisement_counter < 30:
            print("sending advertisement")
            send_advertisement(psu_advertisement)
            advertisement_counter += 1
    if int_g() == 0:
        i = interrupts()
        print(i)
        i_reg = i[2]
        if i_reg & 0x80: # I_VBUSOK
            print("I_VBUSOK")
            #pass # just a side effect of vbus being attached
        if i_reg & 0x40: # I_ACTIVITY
            print("I_ACTIVITY")
            pass # just a side effect of CC comms I think?
        if i_reg & 0x20: # I_COMP_CHNG
            print("I_COMP_CHNG")
            # this is where detach can occur, let's check
            cc = find_cc(fn=measure_source)
            if cc == 0:
                print("Disconnect detected!")
                return # we exiting this
        if i_reg & 0x10: # I_CRC_CHK
            pass # new CRC, just a side effect of CC comms
        if i_reg & 0x8: # I_ALERT
            print("I_ALERT")
            x = i2c.readfrom_mem(0x22, 0x41, 1)[0]
            print(bin(x))
        if i_reg & 0x4: # I_WAKE
            print("I_WAKE")
        if i_reg & 0x2: # I_COLLISION
            print("I_COLLISION")
        if i_reg & 0x1: # I_BC_LVL
            print("I_BC_LVL")
  except KeyboardInterrupt:
    print("CtrlC")
    raise

def sink_flow():
  global pdo_requested, pdos, sent_messages
  reset_msg_id()
  try:
   timeout = 0.00001
   while True:
    if rxb_state()[0] == 0: # buffer non-empty
        d = get_message()
        msg_types = control_message_types if d["c"] else data_message_types
        msg_name = msg_types[d["t"]]
        # now we do things depending on the message type that we received
        if msg_name == "GoodCRC": # example
            pass # print("GoodCRC")
        elif msg_name == "Source_Capabilities":
            # need to request a PDO!
            pdos = get_pdos(d)
            pdo_i, current = select_pdo(pdos)
            # sending a message, need to increment message id
            request_fixed_pdo(pdo_i, current, current)
            # print("PDO requested!")
            pdo_requested = True
            sys.stdout.write(str(pdos))
            sys.stdout.write('\n')
        elif msg_name in ["Accept", "PS_RDY"]:
            print(get_adc_vbus(), "V")
        elif msg_name == "Vendor_Defined":
            parse_vdm(d)
            react_vdm(d)
        show_msg(d)
        for message in sent_messages:
            sys.stdout.write('> ')
            sys.stdout.write(myhex(message))
            sys.stdout.write('\n')
        sent_messages = []
    sleep(timeout) # so that ctrlc works
    if int_g() == 0:
        # needs sink detach processing here lmao
        i = interrupts()
        print(i)
        i_reg = i[2]
        if i_reg & 0x80: # I_VBUSOK
            print("I_VBUSOK")
            #pass # just a side effect of vbus being attached
        if i_reg & 0x40: # I_ACTIVITY
            print("I_ACTIVITY")
            pass # just a side effect of CC comms I think?
        if i_reg & 0x20: # I_COMP_CHNG
            print("I_COMP_CHNG")
        if i_reg & 0x10: # I_CRC_CHK
            pass # new CRC, just a side effect of CC comms
        if i_reg & 0x8: # I_ALERT
            print("I_ALERT")
        if i_reg & 0x4: # I_WAKE
            print("I_WAKE")
        if i_reg & 0x2: # I_COLLISION
            print("I_COLLISION")
        if i_reg & 0x1: # I_BC_LVL
            print("I_BC_LVL")
  except KeyboardInterrupt:
    print("CtrlC")
    return

########################
#
# Packet reception
# and parsing code
#
########################

control_message_types = [
    "Reserved",
    "GoodCRC",
    "GotoMin",
    "Accept",
    "Reject",
    "Ping",
    "PS_RDY",
    "Get_Source_Cap",
    "Get_Sink_Cap",
    "DR_Swap",
    "PR_Swap",
    "VCONN_Swap",
    "Wait",
    "Soft_Reset",
    "Data_Reset",
    "Data_Reset_Complete",
    "Not_Supported",
    "Get_Source_Cap_Extended",
    "Get_Status",
    "FR_Swap",
    "Get_PPS_Status",
    "Get_Country_Codes",
    "Get_Sink_Cap_Extended",
    "Get_Source_Info",
    "Get_Revision",
]

data_message_types = [
    "Reserved",
    "Source_Capabilities",
    "Request",
    "BIST",
    "Sink_Capabilities",
    "Battery_Status",
    "Alert",
    "Get_Country_Info",
    "Enter_USB",
    "EPR_Request",
    "EPR_Mode",
    "Source_Info",
    "Revision",
    "Reserved",
    "Reserved",
    "Vendor_Defined",
]

header_starts = [0xe0, 0xc0]

def get_message(get_rxb=get_rxb):
    header = 0
    d = {}
    # we might have to get through some message data!
    while header not in header_starts:
        header = get_rxb(1)[0]
        if header == 0:
            return
        if header not in header_starts:
            # this will be printed, eventually.
            # the aim is that it doesn't delay code in the way that print() seems to
            sys.stdout.write("disc {}\n".format(hex(header)))
    d["o"] = False # incoming message
    d["h"] = header
    b1, b0 = get_rxb(2)
    d["b0"] = b0
    d["b1"] = b1
    sop = 1 if header == 0xe0 else 0
    d["st"] = sop
    # parsing the packet header
    prole = b0 & 1
    d["pr"] = prole
    drole = b1 >> 5 & 1
    d["dr"] = drole
    msg_type = b1 & 0b11111
    pdo_count = (b0 >> 4) & 0b111
    d["dc"] = pdo_count
    d["t"] = msg_type
    d["c"] = pdo_count == 0 # control if True else data
    msg_index = int((b0 >> 1) & 0b111)
    d["i"] = msg_index
    if pdo_count:
        read_len = pdo_count*4
        pdos = get_rxb(read_len)
        d["d"] = pdos
    _ = get_rxb(4) # crc
    rev = b1 >> 6
    d["r"] = rev
    is_ext = b0 >> 7 # extended
    d["e"] = is_ext
    msg_types = control_message_types if pdo_count == 0 else data_message_types
    msg_name = msg_types[d["t"]]
    d["tn"] = msg_name
    if msg_name == "Vendor_Defined":
        parse_vdm(d)
    return d

def show_msg(d):
    ## d["h"] = header
    ## sop = 1 if header == 0xe0 else 0
    ## d["st"] = sop
    sop_str = "" if d["st"] else "'"
    # parsing the packet header
    ## d["pr"] = prole
    prole_str = "NC"[d["pr"]] if d["st"] else "R"
    drole_str = "UD"[d["dr"]] if d["st"] else "R"
    ## d["dc"] = pdo_count
    ## d["t"] = msg_type
    ## d["c"] = pdo_count == 0 # control if True else data
    message_types = control_message_types if d["c"]  else data_message_types
    ## d["i"] = msg_index
    msg_type_str = message_types[d["t"]] if d["t"] < len(message_types) else "Reserved"
    ## if pdo_count:
    ##    d["d"] = pdos
    ## d["r"] = rev
    rev_str = "123"[d["r"]]
    ## d["e"] = is_ext
    ext_str = ["std", "ext"][d["e"]]
    # msg direction
    dir_str = ">" if d["o"] else "<"
    if d["dc"]:
        # converting "41 80 00 FF A4 25 00 2C" to "FF008041 2C0025A4"
        pdo_strs = []
        pdo_data = myhex(d["d"]).split(' ')
        for i in range(len(pdo_data)//4):
           pdo_strs.append(''.join(reversed(pdo_data[(i*4):][:4])))
        pdo_str = " ".join(pdo_strs)
    else:
        pdo_str = ""
    sys.stdout.write("{} {}{}: {}; p{} d{} r{}, {}, p{}, {} {}\n".format(dir_str, d["i"], sop_str, msg_type_str, prole_str, drole_str, rev_str, ext_str, d["dc"], myhex((d["b0"], d["b1"])).replace(' ', ''), pdo_str))
    # extra parsing where possible
    if msg_type_str == "Vendor_Defined":
        print_vdm(d)
        #sys.stdout.write(str(d["d"]))
        #sys.stdout.write('\n')
    elif msg_type_str == "Source_Capabilities":
        sys.stdout.write(str(get_pdos(d)))
        sys.stdout.write('\n')
    return d

########################
#
# PDO parsing code
#
########################

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

def create_pdo(pdo_t, *args):
    print(pdo_t, *args)
    assert(pdo_t in pdo_types)
    pdo = [0 for i in range(4)]
    if pdo_t == 'fixed':
        voltage, current, peak_current, pdo3 = args
        current_v = current // 10
        current_h = (current_v >> 8) & 0b11
        current_l = current_v & 0xFF
        pdo[1] = current_h
        pdo[0] = current_l
        """
        current_h = pdo[1] & 0b11
        current_b = ( current_h << 8 ) | pdo[0]
        current = current_b * 10
        """
        voltage_v = voltage // 50
        pdo[2] = (voltage_v >> 6) & 0b1111
        pdo[1] |= (voltage_v & 0b111111) << 2
        """
        voltage_h = pdo[2] & 0b1111
        voltage_b = ( voltage_h << 6 ) | (pdo[1] >> 2)
        voltage = voltage_b * 50
        """
        pdo[2] |= (peak_current & 0b11) << 4
        peak_current = (pdo[2] >> 4) & 0b11
        pdo[3] = pdo3
        pdo[3] |= pdo_types.index(pdo_t) << 6
    elif pdo_t == 'batt':
        raise Exception("Batt PDO formation not implemented yet!")
    elif pdo_t == 'var':
        raise Exception("Variable PDO formation not implemented yet!")
    elif pdo_t == 'pps':
        """t = (pdo[3] >> 4) & 0b11
        limited = (pdo[3] >> 5) & 0b1
        max_voltage_h = pdo[3] & 0b1
        max_voltage_b = (max_voltage_h << 7) | pdo[2] >> 1
        max_voltage = max_voltage_b * 100
        min_voltage = pdo[1] * 100
        max_current_b = pdo[0] & 0b1111111
        max_current = max_current_b * 50
        return ('pps', pps_types[t], max_voltage, min_voltage, max_current, limited)"""
        raise Exception("PPS PDO formation not implemented yet!")
    print(parse_pdo(bytes(pdo)))
    return pdo

def get_pdos(d):
    pdo_list = []
    pdos = d["d"]
    for pdo_i in range(d["dc"]):
        pdo_bytes = pdos[(pdo_i*4):][:4]
        #print(myhex(pdo_bytes))
        parsed_pdo = parse_pdo(pdo_bytes)
        pdo_list.append(parsed_pdo)
    return pdo_list

########################
#
# Command sending code
# and simple commands
#
########################

def send_command(command, data, msg_id=None, rev=0b10, power_role=0, data_role=0):
    msg_id = increment_msg_id() if msg_id is None else msg_id
    sop_seq = [0x12, 0x12, 0x12, 0x13, 0x80]
    eop_seq = [0xff, 0x14, 0xfe, 0xa1]
    obj_count = len(data) // 4

    header = [0, 0] # hoot hoot !

    header[0] |= rev << 6 # PD revision
    header[0] |= (data_role & 0b1) << 5 # PD revision
    header[0] |= (command & 0b11111)

    header[1] = power_role & 0b1
    header[1] |= (msg_id & 0b111) << 1 # message ID
    header[1] |= obj_count << 4

    message = header+data

    sop_seq[4] |= len(message)

    i2c.writeto_mem(FUSB302_I2C_SLAVE_ADDR, TCPC_REG_FIFOS, bytes(sop_seq) )
    i2c.writeto_mem(FUSB302_I2C_SLAVE_ADDR, TCPC_REG_FIFOS, bytes(message) )
    i2c.writeto_mem(FUSB302_I2C_SLAVE_ADDR, TCPC_REG_FIFOS, bytes(eop_seq) )

    sent_messages.append(message)

def soft_reset():
    send_command(0b01101, [])
    reset_msg_id()

########################
#
# PSU request processing code
#
########################

def send_advertisement(psu_advertisement):
    #data = [bytes(a) for a in psu_advertisement]
    data = psu_advertisement
    send_command(0b1, data, power_role=1, data_role=1)

def process_psu_request(psu_advertisement, d):
    print(d)
    profile = ((d["d"][3] >> 4)&0b111)-1
    print("Selected profile", profile)
    if profile not in range(len(psu_advertisement)):
        set_power_rail('off')
    else:
        send_command(0b11, [], power_role=1, data_role=1) # Accept
        sleep(0.1)
        if profile == 0:
            set_power_rail('5V')
        elif profile == 1:
            set_power_rail('VIN')
        send_command(0b110, [], power_role=1, data_role=1) # PS_RDY

########################
#
# PDO request code
#
########################

def request_fixed_pdo(num, current, max_current):
    pdo = [0 for i in range(4)]

    max_current_b = max_current // 10
    max_current_l = max_current_b & 0xff
    max_current_h = max_current_b >> 8
    pdo[0] = max_current_l
    pdo[1] |= max_current_h

    current_b = current // 10
    current_l = current_b & 0x3f
    current_h = current_b >> 6
    pdo[1] |= current_l << 2
    pdo[2] |= current_h

    pdo[3] |= (num+1) << 4 # object position
    pdo[3] |= 0b1 # no suspend

    send_command(0b00010, pdo)

def request_pps_pdo(num, voltage, current):
    pdo = [0 for i in range(4)]

    current = current // 50
    pdo[0] = current & 0x7f

    voltage = voltage // 20
    voltage_l = (voltage & 0x7f)
    voltage_h = (voltage >> 7) & 0x1f
    pdo[1] |= voltage_l << 1
    pdo[2] = voltage_h

    pdo[3] |= (num+1) << 4 # object position
    pdo[3] |= 0b1 # no suspend

    send_command(0b00010, pdo)

########################
#
# VDM parsing and response code
#
########################

vdm_commands = [
    "Reserved",
    "Discover Identity",
    "Discover SVIDs",
    "Discover Modes",
    "Enter Mode",
    "Exit Mode",
    "Attention"]

svids = {
    0xff00: 'SID',
    0xff01: 'DisplayPort',
}

dp_commands = {
    0x10: "DP Status Update",
    0x11: "DP Configure"}

vdm_cmd_types = ["REQ", "ACK", "NAK", "BUSY"]

# reply-with-hardcoded code

def react_vdm(d):
    if d["vdm_s"]:
        # version: major and minor
        cmd_type = d["vdm_ct"]
        command_name = d["vdm_cn"]
        if command_name == "Discover Identity":
            data = list(b'A\xA0\x00\xff\xa4%\x00,\x00\x00\x00\x00\x01\x00\x00\x00\x0b\x00\x00\x11')
            send_command(d["t"], data)
            #sys.stdout.write("a")
        elif command_name == "Discover SVIDs":
            data = list(b'B\xA0\x00\xff\x00\x00\x01\xff')
            send_command(d["t"], data)
            #sys.stdout.write("b")
        elif command_name == "Discover Modes":
            data = list(b'C\xA0\x01\xff\x05\x0c\x00\x00')
            send_command(d["t"], data)
            #sys.stdout.write("c")
        elif command_name == "Enter Mode":
            data = list(b'D\xA1\x01\xff')
            send_command(d["t"], data)
            #sys.stdout.write("d")
        elif command_name == "DP Status Update":
            data = list(b'P\xA1\x01\xff\x1a\x00\x00\x00')
            send_command(d["t"], data)
            #sys.stdout.write("e")
        elif command_name == "DP Configure":
            data = list(b'Q\xA1\x01\xff')
            send_command(d["t"], data)
            #sys.stdout.write("f")
    # idk what to do if the vdm is unstructured, for now

def parse_vdm(d):
    data = d['d']
    is_structured = data[1] >> 7
    d["vdm_s"] = is_structured
    svid = (data[3] << 8) + data[2]
    d["vdm_sv"] = svid
    svid_name = svids.get(svid, "Unknown ({})".format(hex(svid)))
    d["vdm_svn"] = svid_name
    if is_structured:
        # version: major and minor
        version_bin = (data[1] >> 3) & 0xf
        d["vdm_v"] = version_bin
        obj_pos = data[1] & 0b111
        d["vdm_o"] = obj_pos
        cmd_type = data[0]>>6
        d["vdm_ct"] = cmd_type
        command = data[0] & 0b11111
        d["vdm_c"] = command
        if command > 15:
            command_name = "SVID specific {}".format(bin(command))
            if svid_name == "DisplayPort":
                command_name = dp_commands.get(command, command_name)
        else:
            command_name = vdm_commands[command] if command < 7 else "Reserved"
        d["vdm_cn"] = command_name
        #if svid_name == "DisplayPort":
        #    parse_dp_command(version_str())
    else:
        vdmd = [data[1] & 0x7f, data[0]]
        d["vdm_d"] = vdmd

def print_vdm(d):
    if d["vdm_s"]:
        svid_name = d["vdm_svn"]
        version_str = mybin([d["vdm_v"]])[4:]
        objpos_str = mybin([d["vdm_o"]])[5:]
        cmd_type_name = vdm_cmd_types[d["vdm_ct"]]
        cmd_name = d["vdm_cn"]
        sys.stdout.write("VDM: str, m{} v{} o{}, ct{}: {}\n".format(svid_name, version_str, objpos_str, cmd_type_name, cmd_name))
    else:
        sys.stdout.write("VDM: unstr, m{}, d{}".format(svid_name, myhex(d["vdm_d"])))

########################
#
# Power profile selection example code
#
########################

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

expected_voltage = 20

def select_pdo_for_voltage(pdos, voltage=None, current=None):
    if voltage is None: voltage = expected_voltage
    for i, pdo in enumerate(pdos):
        if pdo[0] != 'fixed': # skipping variable PDOs
            continue
        t, pdo_voltage, max_current, oc, flags = pdo
        if pdo_voltage//1000 == voltage:
            current = current if current else max_current
            return i, current

# example function used by default
select_pdo = select_pdo_for_resistance

########################
#
# Packet capture code
#
########################

packets = []
packets1 = [[192, 143, 16, 1, 160, 0, 255, 164, 69, 2, 114, 192, 143, 16, 1, 160, 0, 255, 164, 69, 2, 114, 192, 143, 16, 1, 160, 0, 255, 164, 69, 2, 114, 224, 161, 17, 44, 145, 1, 39, 177, 155, 38, 148, 224, 161, 17, 44, 145, 1, 39, 177, 155, 38, 148, 224, 161, 17, 44, 145, 1, 39, 177, 155, 38, 148, 192, 143, 18, 1, 160, 0, 255, 196, 22, 194, 8, 192, 143, 18, 1, 160, 0, 255, 196, 22, 194, 8, 192, 143, 18, 1, 160, 0, 255, 196, 22, 194, 8], [224, 161, 17, 44, 145, 1, 39, 177, 155, 38, 148, 224, 161, 17, 44, 145, 1, 39, 177, 155, 38, 148, 224, 161, 17, 44, 145, 1, 39, 177, 155, 38, 148, 192, 143, 20, 1, 160, 0, 255, 100, 227, 130, 135, 192, 143, 20, 1, 160, 0, 255, 100, 227, 130, 135, 192, 143, 20, 1, 160, 0, 255, 100, 227, 130, 135], [224, 161, 17, 44, 145, 1, 39, 177, 155, 38, 148, 224, 65, 0, 187, 108, 187, 168, 224, 66, 16, 44, 177, 4, 18, 171, 173, 31, 42, 224, 97, 1, 143, 120, 56, 74, 224, 99, 3, 33, 123, 0, 150, 224, 65, 2, 151, 13, 181, 70], [224, 102, 5, 81, 42, 20, 2, 224, 65, 4, 162, 168, 214, 175], [192, 79, 22, 1, 128, 0, 255, 80, 232, 231, 212, 192, 79, 22, 1, 128, 0, 255, 80, 232, 231, 212, 192, 79, 22, 1, 128, 0, 255, 80, 232, 231, 212, 192, 79, 22, 1, 128, 0, 255, 80, 232, 231, 212], [192, 79, 24, 1, 128, 0, 255, 49, 86, 215, 107, 192, 79, 24, 1, 128, 0, 255, 49, 86, 215, 107, 192, 79, 24, 1, 128, 0, 255, 49, 86, 215, 107, 192, 79, 24, 1, 128, 0, 255, 49, 86, 215, 107], [192, 79, 26, 1, 128, 0, 255, 81, 5, 23, 17, 192, 79, 26, 1, 128, 0, 255, 81, 5, 23, 17, 192, 79, 26, 1, 128, 0, 255, 81, 5, 23, 17, 192, 79, 26, 1, 128, 0, 255, 81, 5, 23, 17], [192, 79, 28, 1, 128, 0, 255, 241, 240, 87, 158, 192, 79, 28, 1, 128, 0, 255, 241, 240, 87, 158, 192, 79, 28, 1, 128, 0, 255, 241, 240, 87, 158, 192, 79, 28, 1, 128, 0, 255, 241, 240, 87, 158], [192, 79, 30, 1, 128, 0, 255, 145, 163, 151, 228, 192, 79, 30, 1, 128, 0, 255, 145, 163, 151, 228, 192, 79, 30, 1, 128, 0, 255, 145, 163, 151, 228, 192, 79, 30, 1, 128, 0, 255, 145, 163, 151, 228], [192, 79, 16, 1, 128, 0, 255, 240, 29, 167, 91, 192, 79, 16, 1, 128, 0, 255, 240, 29, 167, 91, 192, 79, 16, 1, 128, 0, 255, 240, 29, 167, 91, 192, 79, 16, 1, 128, 0, 255, 240, 29, 167, 91], [192, 79, 18, 1, 128, 0, 255, 144, 78, 103, 33, 192, 79, 18, 1, 128, 0, 255, 144, 78, 103, 33, 192, 79, 18, 1, 128, 0, 255, 144, 78, 103, 33, 192, 79, 18, 1, 128, 0, 255, 144, 78, 103, 33], [192, 79, 20, 1, 128, 0, 255, 48, 187, 39, 174, 192, 79, 20, 1, 128, 0, 255, 48, 187, 39, 174, 192, 79, 20, 1, 128, 0, 255, 48, 187, 39, 174, 192, 79, 20, 1, 128, 0, 255, 48, 187, 39, 174], [192, 79, 22, 1, 128, 0, 255, 80, 232, 231, 212, 192, 79, 22, 1, 128, 0, 255, 80, 232, 231, 212, 192, 79, 22, 1, 128, 0, 255, 80, 232, 231, 212, 192, 79, 22, 1, 128, 0, 255, 80, 232, 231, 212], [192, 79, 24, 1, 128, 0, 255, 49, 86, 215, 107, 192, 79, 24, 1, 128, 0, 255, 49, 86, 215, 107, 192, 79, 24, 1, 128, 0, 255, 49, 86, 215, 107, 192, 79, 24, 1, 128, 0, 255, 49, 86, 215, 107], [192, 79, 26, 1, 128, 0, 255, 81, 5, 23, 17, 192, 79, 26, 1, 128, 0, 255, 81, 5, 23, 17, 192, 79, 26, 1, 128, 0, 255, 81, 5, 23, 17, 192, 79, 26, 1, 128, 0, 255, 81, 5, 23, 17], [192, 79, 28, 1, 128, 0, 255, 241, 240, 87, 158, 192, 79, 28, 1, 128, 0, 255, 241, 240, 87, 158, 192, 79, 28, 1, 128, 0, 255, 241, 240, 87, 158, 192, 79, 28, 1, 128, 0, 255, 241, 240, 87, 158], [192, 79, 30, 1, 128, 0, 255, 145, 163, 151, 228, 192, 79, 30, 1, 128, 0, 255, 145, 163, 151, 228, 192, 79, 30, 1, 128, 0, 255, 145, 163, 151, 228, 192, 79, 30, 1, 128, 0, 255, 145, 163, 151, 228], [192, 79, 16, 1, 128, 0, 255, 240, 29, 167, 91, 192, 79, 16, 1, 128, 0, 255, 240, 29, 167, 91, 192, 79, 16, 1, 128, 0, 255, 240, 29, 167, 91, 192, 79, 16, 1, 128, 0, 255, 240, 29, 167, 91], [192, 79, 18, 1, 128, 0, 255, 144, 78, 103, 33, 192, 79, 18, 1, 128, 0, 255, 144, 78, 103, 33, 192, 79, 18, 1, 128, 0, 255, 144, 78, 103, 33, 192, 79, 18, 1, 128, 0, 255, 144, 78, 103, 33], [192, 79, 20, 1, 128, 0, 255, 48, 187, 39, 174, 192, 79, 20, 1, 128, 0, 255, 48, 187, 39, 174, 192, 79, 20, 1, 128, 0, 255, 48, 187, 39, 174, 192, 79, 20, 1, 128, 0, 255, 48, 187, 39, 174], [192, 79, 22, 1, 128, 0, 255, 80, 232, 231, 212, 192, 79, 22, 1, 128, 0, 255, 80, 232, 231, 212, 192, 79, 22, 1, 128, 0, 255, 80, 232, 231, 212, 192, 79, 22, 1, 128, 0, 255, 80, 232, 231, 212], [224, 111, 23, 1, 128, 0, 255, 214, 196, 43, 238, 224, 65, 6, 142, 201, 216, 65, 224, 79, 82, 65, 128, 0, 255, 164, 37, 0, 44, 0, 0, 0, 0, 1, 0, 0, 0, 11, 0, 0, 17, 49, 174, 102, 75, 224, 97, 3, 163, 25, 54, 164, 224, 111, 25, 2, 128, 0, 255, 89, 213, 174, 67, 224, 65, 8, 137, 228, 96, 166, 224, 79, 52, 66, 128, 0, 255, 164, 37, 1, 255, 0, 0, 0, 0, 166, 70, 26, 81, 224, 97, 5, 150, 188, 85, 77, 224, 111, 27, 3, 128, 1, 255, 29, 208, 201, 152, 224, 65, 10, 165, 133, 110, 72, 224, 79, 38, 67, 128, 1, 255, 5, 12, 0, 0, 241, 253, 40, 109, 224, 97, 7, 186, 221, 91, 163, 224, 111, 29, 4, 129, 1, 255, 51, 119, 156, 139, 224, 65, 12, 144, 32, 13, 161, 224, 79, 24, 68, 129, 1, 255, 72, 165, 196, 223, 224, 97, 9, 189, 240, 227, 68, 224, 111, 47, 16, 129, 1, 255, 1, 0, 0, 0, 216, 217, 112, 117, 224, 65, 14, 188, 65, 3, 79, 224, 79, 42, 80, 129, 1, 255, 26, 0, 0, 0, 52, 141, 63, 222, 224, 97, 11, 145, 145, 237, 170, 224, 111, 33, 17, 129, 1, 255, 6, 8, 0, 0, 213, 107, 220, 226, 224, 65, 0, 187, 108, 187, 168], [224, 79, 28, 81, 129, 1, 255, 37, 164, 131, 77, 224, 97, 13, 164, 52, 142, 67]]
packets2 = [[224, 33, 1, 138, 55, 65, 186, 224, 163, 3, 111, 172, 250, 93, 224, 166, 5, 31, 253, 238, 201, 0, 224, 0, 33, 1, 1, 138, 55, 0, 65, 186]]
packets_pos = [ 0,0 ] # hoot-hoot,,, hewwo ;-P

def record_flow():
  while True:
    if rxb_state()[0] == 0:
        print(get_buffer_fast())
        #print(get_rxb(80))
        #print(get_message())
    sleep(0.001)

def get_buffer_fast():
    packet = []
    while rxb_state()[0] == 0:
        packet.append(get_rxb(1)[0])
    packets.append(packet)
    return packet

def gb():
    fun = postfactum_readout if listen else get_rxb
    return show_msg(get_message(fun))

def gba():
    # not quite working well atm, sowwy (also, mood)
    while True:
      try:
        gb(); print()
      except Exception as e:
        raise e
        break

def postfactum_readout(length=80):
    # A function that helps read data out of our own capture buffer instead of using the FUSB's internal buffer
    # so, it pretends to be the FUSB FIFO read function, for parsing packets that are recorded into `packets`
    err = 0
    response = []
    while len(response) < length:
        # ran out of data? this ends here
        if packets_pos[0] == len(packets)-1 and packets_pos[1] == len(packets[packets_pos[0]])-1:
            # buffer underflow, returning the unfinished buffer with zeroes in the end, just like the FUSB does
            response = [0]*(length-len(response))
            return bytes(response)
        # we still got data to add!
        # is the current buffer enough?
        remainder = length - len(response)
        current_packet = packets[packets_pos[0]]
        current_packet_end = current_packet[packets_pos[1]:]
        while remainder > 0:
            chunk_len = min(len(current_packet_end), remainder)
            response += current_packet_end[:chunk_len]
            remainder -= chunk_len
            packets_pos[1] += chunk_len
            # now, checking for overflow
            if packets_pos[1] >= len(current_packet)-1:
                # sanity check - this should not happen
                if packets_pos[1] > len(current_packet):
                    print("Alert, overcount!", packets_pos, len(current_packet_end), chunk_len)
                # do we need to go to the next packet?
                if len(packets)-1 <= packets_pos[0]:
                    # next packet doesn't exist lol
                    print("We ran out of packet")
                    err += 1 # malformed packets cause this function to glitch and loop infinitely, hence the error counter
                    if err == 4:
                        return bytes(response) # lol gave up here
                else:
                    err = 0
                    packets_pos[0] += 1
                    packets_pos[1] = 0
            current_packet = packets[packets_pos[0]]
            current_packet_end = current_packet[packets_pos[1]:]
        return bytes(response)

########################
#
# Helper functions
#
########################

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

########################
#
# Main loop and mode selection code
#
########################

listen = 0

# this construct allows you to switch from sink mode to listen mode
# it likely does not let you switch into other direction hehe ouch
# it might not be needed anymore either lol
# but hey
# TODO I guess
# TODO 2: elaborate on what I wrote here

def loop():
    reset()
    power()
    unmask_all()
    if is_source:
        set_controls_source()
    else:
        set_controls_sink()

    if listen:
        cc = 1
        flush_receive()
        disable_pulldowns()
        sleep(0.2)
        read_cc(cc)
        enable_sop()
        flush_transmit()
        flush_receive()
        reset_pd()
        record_flow()
    elif is_source:
        set_roles(power_role=1)
        set_power_rail('off')
        disable_pulldowns()
        set_wake(True)
        enable_pullups()
        set_mdac(0b111111)
        cc = find_cc(fn=measure_source, debug=True)
        while cc == 0:
            cc = find_cc(fn=measure_source)
        cc = find_cc(fn=measure_source, debug=True)
        set_power_rail('5V')
        source_flow()
    else: # sink
        set_roles()
        set_wake(True)
        set_mdac(0b111111)
        cc = 0
        cc = find_cc(fn=measure_sink, debug=True)
        while cc == 0:
            cc = find_cc(fn=measure_sink)
        cc = find_cc(fn=measure_sink, debug=True)
        sink_flow()

#listen = 1; packets = packets1; gba()

while True:
    try:
        loop()
    except KeyboardInterrupt:
        sleep(1)
