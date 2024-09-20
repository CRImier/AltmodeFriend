from machine import Pin, I2C, ADC
from time import sleep, ticks_us, ticks_diff
import sys

from fusb302 import FUSB302

is_source = False

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

fusb = FUSB302(i2c, int_p=int_p)

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
    if fusb.rxb_state()[0] == 0: # buffer non-empty
        d = get_message()
        msg_types = control_message_types if d["c"] else data_message_types
        msg_name = msg_types[d["t"]]
        # now we do things depending on the message type that we received
        if msg_name == "GoodCRC": # example
            print("GoodCRC")
        elif msg_name == "Request":
            profile_selected = True
            process_psu_request(psu_advertisement, d)
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
        i = fusb.interrupts()
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
            cc = fusb.find_cc(fn="measure_source")
            if cc == 0:
                print("Disconnect detected!")
                return # we exiting this
        if i_reg & 0x10: # I_CRC_CHK
            pass # new CRC, just a side effect of CC comms
        if i_reg & 0x8: # I_ALERT
            print("I_ALERT")
            x = fusb.bus.readfrom_mem(fusb.addr, 0x41, 1)[0]
            print(bin(x))
        if i_reg & 0x4: # I_WAKE
            print("I_WAKE")
        if i_reg & 0x2: # I_COLLISION
            print("I_COLLISION")
        if i_reg & 0x1: # I_BC_LVL
            print("I_BC_LVL")
  except KeyboardInterrupt:
    print("CtrlC")
    sleep(1)
    raise

def sink_flow():
  global pdo_requested, pdos, sent_messages
  reset_msg_id()
  try:
   timeout = 0.00001
   while True:
    if fusb.rxb_state()[0] == 0: # buffer non-empty
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
        i = fusb.interrupts()
        print(i)
        i_reg = i[2]
        if i_reg & 0x80: # I_VBUSOK
            pass # just a side effect of vbus being attached
        if i_reg & 0x40: # I_ACTIVITY
            print("I_ACTIVITY")
            pass # just a side effect of CC comms I think?
        if i_reg & 0x20: # I_COMP_CHNG
            print("I_COMP_CHNG")
            cc = fusb.find_cc(fn="measure_sink")
            if cc == 0:
                print("Disconnect detected!")
                return # we exiting this
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
    sleep(1)
    raise

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

def get_message(get_rxb="get_rxb"):
    if isinstance(get_rxb, str):
        get_rxb = getattr(fusb, get_rxb)
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
    obj_count = len(data) // 4

    header = [0, 0] # hoot hoot !

    header[0] |= rev << 6 # PD revision
    header[0] |= (data_role & 0b1) << 5 # PD revision
    header[0] |= (command & 0b11111)

    header[1] = power_role & 0b1
    header[1] |= (msg_id & 0b111) << 1 # message ID
    header[1] |= obj_count << 4

    message = header+data

    fusb.send(message)

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
        cmd_type = d["vdm_ct"]
        command_name = d["vdm_cn"]
        # response vdm params
        rd = {}
        # all same params as the incoming message, save for the command type
        for key in ["vdm_s", "vdm_sv", "vdm_c", "vdm_v", "vdm_o"]:
            rd[key] = d[key]
        # command type is ACK and not REQ for all command replies
        rd["vdm_ct"] = 1 # ACK
        if command_name == "Discover Identity":
            # discover identity response with "we are an altmode adapter yesyes"
            data = list(b'A\xA0\x00\xff\xa4%\x00,\x00\x00\x00\x00\x01\x00\x00\x00\x0b\x00\x00\x11')
            r = create_vdm_data(rd, data[4:])
            print(r)
            print(data)
            send_command(d["t"], r)
            #sys.stdout.write("a") # debug stuff
        elif command_name == "Discover SVIDs":
            data = list(b'B\xA0\x00\xff\x00\x00\x01\xff')
            r = create_vdm_data(rd, data[4:])
            print(r)
            print(data)
            send_command(d["t"], r)
            #sys.stdout.write("b")
        elif command_name == "Discover Modes":
            #data = list(b'C\xA0\x01\xff\x45\x04\x00\x00')
            data = list(b'C\xA0\x01\xff\x05\x0c\x00\x00')
            r = create_vdm_data(rd, data[4:])
            print(r)
            print(data)
            send_command(d["t"], r)
            #sys.stdout.write("c")
        elif command_name == "Enter Mode":
            data = list(b'D\xA1\x01\xff')
            r = create_vdm_data(rd, [])
            print(r)
            print(data)
            send_command(d["t"], r)
            #sys.stdout.write("d")
        elif command_name == "DP Status Update":
            #data = list(b'P\xA1\x01\xff\x1a\x00\x00\x00')
            data = list(b'P\xA1\x01\xff\x9a\x00\x00\x00')
            r = create_vdm_data(rd, data[4:])
            print(r)
            print(data)
            send_command(d["t"], r)
            #sys.stdout.write("e")
        elif command_name == "DP Configure":
            data = list(b'Q\xA1\x01\xff')
            r = create_vdm_data(rd, [])
            print(r)
            print(data)
            send_command(d["t"], r)
            #sys.stdout.write("f")
    # no unstructured vdm processing at this time

def create_vdm_data(d, data):
    """
    Creates the VDM header (PDO) from a dict with pre-supplied data and an additional data list.
    """
    l = 4 + len(data)
    vdm = bytearray(l)
    for i in data:
        vdm[i+4] = i
    # most basic vdm flags
    vdm_s = d["vdm_s"]
    vdm[1] |= vdm_s << 7
    vdm_sv = d["vdm_sv"]
    vdm[2] = vdm_sv & 0xff
    vdm[3] = vdm_sv >> 8
    # can't build unstructured vdms yet
    if vdm_s:
        # building structured vdm
        # vdm command
        vdm_c = d["vdm_c"]
        vdm[0] |= (vdm_c & 0b11111)
        # vdm command type
        vdm_ct = d["vdm_ct"]
        vdm[0] |= (vdm_ct & 0b11) << 6
        # default version codes set to 0b01; 0b00
        vdm_v = d.get("vdm_v", 0b0100)
        vdm[1] |= (vdm_v & 0b1111) << 3
        # object position
        vdm_o = d.get("vdm_o", 0)
        vdm[1] |= vdm_o & 0b111
    else:
        raise NotImplementedError
    return bytes(vdm)

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

vdm_dp_pin_assg = {
 0b1:"A",
 0b10:"B",
 0b100:"C",
 0b1000:"D",
 0b10000:"E",
 0b100000:"F",
}

vdm_dp_port_cap = [
 "RES",
 "UFP",
 "DFP",
 "UFP&DFP"
]

vdm_dp_port_conn = [
 "NC",
 "UFP",
 "DFP",
 "UFP&DFP"
]

vdm_dp_port_conf = [
 "USB",
 "DFP",
 "DFP",
 "RES"
]

vdm_dp_sgn = {
 0b1:"DP",
 0b10:"USBg2",
 0b100:"RES1",
 0b1000:"RES2"
}

def print_vdm(d):
    if d["vdm_s"]:
        svid_name = d["vdm_svn"]
        version_str = mybin([d["vdm_v"]])[4:]
        objpos_str = mybin([d["vdm_o"]])[5:]
        cmd_type_name = vdm_cmd_types[d["vdm_ct"]]
        cmd_name = d["vdm_cn"]
        sys.stdout.write("VDM: str, m{} v{} o{}, ct{}: {}\n".format(svid_name, version_str, objpos_str, cmd_type_name, cmd_name))
        if svid_name == "DisplayPort":
            if cmd_name == "Discover Modes" and cmd_type_name == "ACK":
                msg = d['d'][4:]
                # port capability (bits 0:1)
                port_cap = msg[0] & 0b11
                vdm_dp_port_cap_s = vdm_dp_port_cap[port_cap]
                # signaling (bits 5:2)
                sgn = (msg[0] >> 2) & 0b1111
                sgn_s = []
                for p in vdm_dp_sgn.keys():
                    if sgn & p:
                        sgn_s.append(vdm_dp_sgn[p])
                sgn_s = ",".join(sgn_s)
                # receptacle indication (bit 6)
                r_i = (msg[0] >> 6) & 0b1
                r_s = "re" if r_i else "pl"
                # usb2 signaling (bit 7)
                u2_i = (msg[0] >> 7) & 0b1
                u2_s = "n" if u2_i else "y"
                # dfp pin assignments (bits 15:8)
                dfp_assy_n = msg[1]
                dfp_assy_s = ""
                for p in vdm_dp_pin_assg.keys():
                    if dfp_assy_n & p:
                        dfp_assy_s += vdm_dp_pin_assg[p]
                # dfp pin assignments (bits 23:16)
                ufp_assy_n = msg[2]
                ufp_assy_s = ""
                for p in vdm_dp_pin_assg.keys():
                    if ufp_assy_n & p:
                        ufp_assy_s += vdm_dp_pin_assg[p]
                #res_byte = msg[3] # (bites 31:24, has to be 0)
                sys.stdout.write("\tModes: p_cap:{} sgn:{} ri:{} u2:{} d_ass:{} u_ass:{}\n".format(vdm_dp_port_cap_s, sgn_s, r_s, u2_s, dfp_assy_s, ufp_assy_s))
            elif cmd_name == "DP Status Update":
                msg = d['d'][4:]
                # dfp/ufp connected (bits 0:1)
                conn = msg[0] & 0b11
                conn_s = vdm_dp_port_conn[conn]
                # power (bit 2)
                pwr = (msg[0] >> 2) & 0b1
                pwr_s = "d" if pwr else "n"
                # enabled (bit 3)
                en = (msg[0] >> 3) & 0b1
                en_s = "y" if en else "n"
                # multi-function (bit 4)
                mf = (msg[0] >> 4) & 0b1
                mf_s = "p" if mf else "n"
                # usb switch req (bit 5)
                usw = (msg[0] >> 5) & 0b1
                usw_s = "r" if usw else "n"
                # dp exit req (bit 6)
                dpe = (msg[0] >> 6) & 0b1
                dpe_s = "r" if dpe else "n"
                # HPD state (bit 7)
                hpd = (msg[0] >> 7) & 0b1
                hpd_s = "h" if hpd else "l"
                # IRQ state (bit 8)
                irq = msg[1] & 0b1
                irq_s = str(irq)
                sys.stdout.write("\tStatus: conn:{} pwr:{} en:{} mf:{} usw:{} dpe:{} hpd:{} irq:{}\n".format(conn_s, pwr_s, en_s, mf_s, usw_s, dpe_s, hpd_s, irq_s))
            if cmd_name == "DP Configure" and cmd_type_name == "REQ":
                msg = d['d'][4:]
                # select configuration (bits 0:1)
                conf = msg[0] & 0b11
                conf_s = vdm_dp_port_conf[conf]
                # signaling (bits 5:2)
                sgn = (msg[0] >> 2) & 0b1111
                sgn_s = []
                for p in vdm_dp_sgn.keys():
                    if sgn & p:
                        sgn_s.append(vdm_dp_sgn[p])
                sgn_s = ",".join(sgn_s)
                if not sgn_s:
                    sgn_s = "UNSP"
                # reserved (bits 7:6)
                # ufp pin assignments (bits 15:8)
                ufp_assy_n = msg[1]
                ufp_assy_s = ""
                for p in vdm_dp_pin_assg.keys():
                    if ufp_assy_n & p:
                        ufp_assy_s += vdm_dp_pin_assg[p]
                #res_bytes = msg[2:] # (bytes 31:24, has to be 0)
                sys.stdout.write("\tConfigure: conf:{} sgn:{} p_ass:{}\n".format(conf_s, sgn_s, ufp_assy_s))
            #di = d
            #breakpoint()
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
# my usb-c dock with usb3 and hdmi i think?
packets1 = [[192, 143, 16, 1, 160, 0, 255, 164, 69, 2, 114, 192, 143, 16, 1, 160, 0, 255, 164, 69, 2, 114, 192, 143, 16, 1, 160, 0, 255, 164, 69, 2, 114, 224, 161, 17, 44, 145, 1, 39, 177, 155, 38, 148, 224, 161, 17, 44, 145, 1, 39, 177, 155, 38, 148, 224, 161, 17, 44, 145, 1, 39, 177, 155, 38, 148, 192, 143, 18, 1, 160, 0, 255, 196, 22, 194, 8, 192, 143, 18, 1, 160, 0, 255, 196, 22, 194, 8, 192, 143, 18, 1, 160, 0, 255, 196, 22, 194, 8], [224, 161, 17, 44, 145, 1, 39, 177, 155, 38, 148, 224, 161, 17, 44, 145, 1, 39, 177, 155, 38, 148, 224, 161, 17, 44, 145, 1, 39, 177, 155, 38, 148, 192, 143, 20, 1, 160, 0, 255, 100, 227, 130, 135, 192, 143, 20, 1, 160, 0, 255, 100, 227, 130, 135, 192, 143, 20, 1, 160, 0, 255, 100, 227, 130, 135], [224, 161, 17, 44, 145, 1, 39, 177, 155, 38, 148, 224, 65, 0, 187, 108, 187, 168, 224, 66, 16, 44, 177, 4, 18, 171, 173, 31, 42, 224, 97, 1, 143, 120, 56, 74, 224, 99, 3, 33, 123, 0, 150, 224, 65, 2, 151, 13, 181, 70], [224, 102, 5, 81, 42, 20, 2, 224, 65, 4, 162, 168, 214, 175], [192, 79, 22, 1, 128, 0, 255, 80, 232, 231, 212, 192, 79, 22, 1, 128, 0, 255, 80, 232, 231, 212, 192, 79, 22, 1, 128, 0, 255, 80, 232, 231, 212, 192, 79, 22, 1, 128, 0, 255, 80, 232, 231, 212], [192, 79, 24, 1, 128, 0, 255, 49, 86, 215, 107, 192, 79, 24, 1, 128, 0, 255, 49, 86, 215, 107, 192, 79, 24, 1, 128, 0, 255, 49, 86, 215, 107, 192, 79, 24, 1, 128, 0, 255, 49, 86, 215, 107], [192, 79, 26, 1, 128, 0, 255, 81, 5, 23, 17, 192, 79, 26, 1, 128, 0, 255, 81, 5, 23, 17, 192, 79, 26, 1, 128, 0, 255, 81, 5, 23, 17, 192, 79, 26, 1, 128, 0, 255, 81, 5, 23, 17], [192, 79, 28, 1, 128, 0, 255, 241, 240, 87, 158, 192, 79, 28, 1, 128, 0, 255, 241, 240, 87, 158, 192, 79, 28, 1, 128, 0, 255, 241, 240, 87, 158, 192, 79, 28, 1, 128, 0, 255, 241, 240, 87, 158], [192, 79, 30, 1, 128, 0, 255, 145, 163, 151, 228, 192, 79, 30, 1, 128, 0, 255, 145, 163, 151, 228, 192, 79, 30, 1, 128, 0, 255, 145, 163, 151, 228, 192, 79, 30, 1, 128, 0, 255, 145, 163, 151, 228], [192, 79, 16, 1, 128, 0, 255, 240, 29, 167, 91, 192, 79, 16, 1, 128, 0, 255, 240, 29, 167, 91, 192, 79, 16, 1, 128, 0, 255, 240, 29, 167, 91, 192, 79, 16, 1, 128, 0, 255, 240, 29, 167, 91], [192, 79, 18, 1, 128, 0, 255, 144, 78, 103, 33, 192, 79, 18, 1, 128, 0, 255, 144, 78, 103, 33, 192, 79, 18, 1, 128, 0, 255, 144, 78, 103, 33, 192, 79, 18, 1, 128, 0, 255, 144, 78, 103, 33], [192, 79, 20, 1, 128, 0, 255, 48, 187, 39, 174, 192, 79, 20, 1, 128, 0, 255, 48, 187, 39, 174, 192, 79, 20, 1, 128, 0, 255, 48, 187, 39, 174, 192, 79, 20, 1, 128, 0, 255, 48, 187, 39, 174], [192, 79, 22, 1, 128, 0, 255, 80, 232, 231, 212, 192, 79, 22, 1, 128, 0, 255, 80, 232, 231, 212, 192, 79, 22, 1, 128, 0, 255, 80, 232, 231, 212, 192, 79, 22, 1, 128, 0, 255, 80, 232, 231, 212], [192, 79, 24, 1, 128, 0, 255, 49, 86, 215, 107, 192, 79, 24, 1, 128, 0, 255, 49, 86, 215, 107, 192, 79, 24, 1, 128, 0, 255, 49, 86, 215, 107, 192, 79, 24, 1, 128, 0, 255, 49, 86, 215, 107], [192, 79, 26, 1, 128, 0, 255, 81, 5, 23, 17, 192, 79, 26, 1, 128, 0, 255, 81, 5, 23, 17, 192, 79, 26, 1, 128, 0, 255, 81, 5, 23, 17, 192, 79, 26, 1, 128, 0, 255, 81, 5, 23, 17], [192, 79, 28, 1, 128, 0, 255, 241, 240, 87, 158, 192, 79, 28, 1, 128, 0, 255, 241, 240, 87, 158, 192, 79, 28, 1, 128, 0, 255, 241, 240, 87, 158, 192, 79, 28, 1, 128, 0, 255, 241, 240, 87, 158], [192, 79, 30, 1, 128, 0, 255, 145, 163, 151, 228, 192, 79, 30, 1, 128, 0, 255, 145, 163, 151, 228, 192, 79, 30, 1, 128, 0, 255, 145, 163, 151, 228, 192, 79, 30, 1, 128, 0, 255, 145, 163, 151, 228], [192, 79, 16, 1, 128, 0, 255, 240, 29, 167, 91, 192, 79, 16, 1, 128, 0, 255, 240, 29, 167, 91, 192, 79, 16, 1, 128, 0, 255, 240, 29, 167, 91, 192, 79, 16, 1, 128, 0, 255, 240, 29, 167, 91], [192, 79, 18, 1, 128, 0, 255, 144, 78, 103, 33, 192, 79, 18, 1, 128, 0, 255, 144, 78, 103, 33, 192, 79, 18, 1, 128, 0, 255, 144, 78, 103, 33, 192, 79, 18, 1, 128, 0, 255, 144, 78, 103, 33], [192, 79, 20, 1, 128, 0, 255, 48, 187, 39, 174, 192, 79, 20, 1, 128, 0, 255, 48, 187, 39, 174, 192, 79, 20, 1, 128, 0, 255, 48, 187, 39, 174, 192, 79, 20, 1, 128, 0, 255, 48, 187, 39, 174], [192, 79, 22, 1, 128, 0, 255, 80, 232, 231, 212, 192, 79, 22, 1, 128, 0, 255, 80, 232, 231, 212, 192, 79, 22, 1, 128, 0, 255, 80, 232, 231, 212, 192, 79, 22, 1, 128, 0, 255, 80, 232, 231, 212], [224, 111, 23, 1, 128, 0, 255, 214, 196, 43, 238, 224, 65, 6, 142, 201, 216, 65, 224, 79, 82, 65, 128, 0, 255, 164, 37, 0, 44, 0, 0, 0, 0, 1, 0, 0, 0, 11, 0, 0, 17, 49, 174, 102, 75, 224, 97, 3, 163, 25, 54, 164, 224, 111, 25, 2, 128, 0, 255, 89, 213, 174, 67, 224, 65, 8, 137, 228, 96, 166, 224, 79, 52, 66, 128, 0, 255, 164, 37, 1, 255, 0, 0, 0, 0, 166, 70, 26, 81, 224, 97, 5, 150, 188, 85, 77, 224, 111, 27, 3, 128, 1, 255, 29, 208, 201, 152, 224, 65, 10, 165, 133, 110, 72, 224, 79, 38, 67, 128, 1, 255, 5, 12, 0, 0, 241, 253, 40, 109, 224, 97, 7, 186, 221, 91, 163, 224, 111, 29, 4, 129, 1, 255, 51, 119, 156, 139, 224, 65, 12, 144, 32, 13, 161, 224, 79, 24, 68, 129, 1, 255, 72, 165, 196, 223, 224, 97, 9, 189, 240, 227, 68, 224, 111, 47, 16, 129, 1, 255, 1, 0, 0, 0, 216, 217, 112, 117, 224, 65, 14, 188, 65, 3, 79, 224, 79, 42, 80, 129, 1, 255, 26, 0, 0, 0, 52, 141, 63, 222, 224, 97, 11, 145, 145, 237, 170, 224, 111, 33, 17, 129, 1, 255, 6, 8, 0, 0, 213, 107, 220, 226, 224, 65, 0, 187, 108, 187, 168], [224, 79, 28, 81, 129, 1, 255, 37, 164, 131, 77, 224, 97, 13, 164, 52, 142, 67]]
packets2 = [[224, 33, 1, 138, 55, 65, 186, 224, 163, 3, 111, 172, 250, 93, 224, 166, 5, 31, 253, 238, 201, 0, 224, 0, 33, 1, 1, 138, 55, 0, 65, 186]]
# framework card
packets3 = [[192, 143, 16, 1, 160, 0, 255, 164, 69, 2, 114, 192, 143, 16, 1, 160, 0, 255, 164, 69, 2, 114, 192, 143, 16, 1, 160, 0, 255, 164, 69, 2, 114, 224, 161, 17, 44, 145, 1, 39, 177, 155, 38, 148, 224, 161, 17, 44, 145, 1, 39, 177, 155, 38, 148, 224, 161, 17, 44, 145, 1, 39, 177, 155, 38, 148, 192, 143, 18, 1, 160, 0, 255, 196, 22, 194, 8, 192, 143, 18, 1, 160, 0, 255, 196, 22, 194, 8, 192, 143, 18, 1, 160, 0, 255, 196, 22, 194, 8], [224, 161, 17, 44, 145, 1, 39, 177, 155, 38, 148, 224, 1, 0, 190, 35, 194, 88, 224, 130, 16, 41, 164, 128, 18, 249, 127, 43, 73, 224, 97, 1, 143, 120, 56, 74, 224, 163, 3, 111, 172, 250, 93, 224, 1, 2, 146, 66, 204, 182], [224, 166, 5, 31, 253, 238, 201, 224, 1, 4, 167, 231, 175, 95], [192, 143, 20, 1, 160, 0, 255, 100, 227, 130, 135, 192, 143, 20, 1, 160, 0, 255, 100, 227, 130, 135, 192, 143, 20, 1, 160, 0, 255, 100, 227, 130, 135], [192, 143, 22, 1, 160, 0, 255, 4, 176, 66, 253, 192, 143, 22, 1, 160, 0, 255, 4, 176, 66, 253, 192, 143, 22, 1, 160, 0, 255, 4, 176, 66, 253], [192, 143, 24, 1, 160, 0, 255, 101, 14, 114, 66, 192, 143, 24, 1, 160, 0, 255, 101, 14, 114, 66, 192, 143, 24, 1, 160, 0, 255, 101, 14, 114, 66], [192, 143, 26, 1, 160, 0, 255, 5, 93, 178, 56, 192, 143, 26, 1, 160, 0, 255, 5, 93, 178, 56, 192, 143, 26, 1, 160, 0, 255, 5, 93, 178, 56], [192, 143, 28, 1, 160, 0, 255, 165, 168, 242, 183, 192, 143, 28, 1, 160, 0, 255, 165, 168, 242, 183, 192, 143, 28, 1, 160, 0, 255, 165, 168, 242, 183], [192, 143, 30, 1, 160, 0, 255, 197, 251, 50, 205, 192, 143, 30, 1, 160, 0, 255, 197, 251, 50, 205, 192, 143, 30, 1, 160, 0, 255, 197, 251, 50, 205], [192, 143, 16, 1, 160, 0, 255, 164, 69, 2, 114, 192, 143, 16, 1, 160, 0, 255, 164, 69, 2, 114, 192, 143, 16, 1, 160, 0, 255, 164, 69, 2, 114], [192, 143, 18, 1, 160, 0, 255, 196, 22, 194, 8, 192, 143, 18, 1, 160, 0, 255, 196, 22, 194, 8, 192, 143, 18, 1, 160, 0, 255, 196, 22, 194, 8], [192, 143, 20, 1, 160, 0, 255, 100, 227, 130, 135, 192, 143, 20, 1, 160, 0, 255, 100, 227, 130, 135, 192, 143, 20, 1, 160, 0, 255, 100, 227, 130, 135], [192, 143, 22, 1, 160, 0, 255, 4, 176, 66, 253, 192, 143, 22, 1, 160, 0, 255, 4, 176, 66, 253, 192, 143, 22, 1, 160, 0, 255, 4, 176, 66, 253], [192, 143, 24, 1, 160, 0, 255, 101, 14, 114, 66, 192, 143, 24, 1, 160, 0, 255, 101, 14, 114, 66, 192, 143, 24, 1, 160, 0, 255, 101, 14, 114, 66], [192, 143, 26, 1, 160, 0, 255, 5, 93, 178, 56, 192, 143, 26, 1, 160, 0, 255, 5, 93, 178, 56, 192, 143, 26, 1, 160, 0, 255, 5, 93, 178, 56], [192, 143, 28, 1, 160, 0, 255, 165, 168, 242, 183, 192, 143, 28, 1, 160, 0, 255, 165, 168, 242, 183, 192, 143, 28, 1, 160, 0, 255, 165, 168, 242, 183], [192, 143, 30, 1, 160, 0, 255, 197, 251, 50, 205, 192, 143, 30, 1, 160, 0, 255, 197, 251, 50, 205, 192, 143, 30, 1, 160, 0, 255, 197, 251, 50, 205], [192, 143, 16, 1, 160, 0, 255, 164, 69, 2, 114, 192, 143, 16, 1, 160, 0, 255, 164, 69, 2, 114, 192, 143, 16, 1, 160, 0, 255, 164, 69, 2, 114], [192, 143, 18, 1, 160, 0, 255, 196, 22, 194, 8, 192, 143, 18, 1, 160, 0, 255, 196, 22, 194, 8, 192, 143, 18, 1, 160, 0, 255, 196, 22, 194, 8], [192, 143, 20, 1, 160, 0, 255, 100, 227, 130, 135, 192, 143, 20, 1, 160, 0, 255, 100, 227, 130, 135, 192, 143, 20, 1, 160, 0, 255, 100, 227, 130, 135], [192, 143, 22, 1, 160, 0, 255, 4, 176, 66, 253, 192, 143, 22, 1, 160, 0, 255, 4, 176, 66, 253, 192, 143, 22, 1, 160, 0, 255, 4, 176, 66, 253], [224, 175, 23, 1, 160, 0, 255, 130, 156, 142, 199, 224, 1, 6, 139, 134, 161, 177, 224, 143, 82, 65, 160, 0, 255, 172, 50, 0, 108, 0, 0, 0, 0, 0, 0, 3, 0, 24, 0, 0, 0, 47, 142, 158, 155, 224, 97, 3, 163, 25, 54, 164, 224, 175, 25, 2, 160, 0, 255, 13, 141, 11, 106, 224, 1, 8, 140, 171, 25, 86, 224, 143, 36, 66, 160, 0, 255, 0, 0, 1, 255, 235, 230, 247, 249, 224, 97, 5, 150, 188, 85, 77, 224, 175, 27, 3, 160, 1, 255, 73, 136, 108, 177, 224, 1, 10, 160, 202, 23, 184, 224, 143, 38, 67, 160, 1, 255, 5, 16, 0, 0, 216, 144, 22, 207, 224, 97, 7, 186, 221, 91, 163, 224, 175, 29, 4, 161, 1, 255, 103, 47, 57, 162, 224, 1, 12, 149, 111, 116, 81, 224, 143, 24, 68, 161, 1, 255, 28, 253, 97, 246, 224, 175, 47, 16, 161, 1, 255, 1, 0, 0, 0, 229, 238, 114, 194, 224, 1, 14, 185, 14, 122, 191]]
packets4 = [[192, 143, 16, 1, 160, 0, 255, 164, 69, 2, 114, 192, 143, 16, 1, 160, 0, 255, 164, 69, 2, 114, 192, 143, 16, 1, 160, 0, 255, 164, 69, 2, 114, 224, 161, 17, 44, 145, 1, 39, 177, 155, 38, 148, 224, 161, 17, 44, 145, 1, 39, 177, 155, 38, 148, 224, 161, 17, 44, 145, 1, 39, 177, 155, 38, 148, 192, 143, 18, 1, 160, 0, 255, 196, 22, 194, 8, 192, 143, 18, 1, 160, 0, 255, 196, 22, 194, 8, 192, 143, 18, 1, 160, 0, 255, 196, 22, 194, 8], [224, 161, 17, 44, 145, 1, 39, 177, 155, 38, 148, 224, 1, 0, 190, 35, 194, 88, 224, 130, 16, 41, 164, 128, 18, 249, 127, 43, 73, 224, 97, 1, 143, 120, 56, 74, 224, 163, 3, 111, 172, 250, 93, 224, 1, 2, 146, 66, 204, 182], [224, 166, 5, 31, 253, 238, 201, 224, 1, 4, 167, 231, 175, 95], [192, 143, 20, 1, 160, 0, 255, 100, 227, 130, 135, 192, 143, 20, 1, 160, 0, 255, 100, 227, 130, 135, 192, 143, 20, 1, 160, 0, 255, 100, 227, 130, 135], [192, 143, 22, 1, 160, 0, 255, 4, 176, 66, 253, 192, 143, 22, 1, 160, 0, 255, 4, 176, 66, 253, 192, 143, 22, 1, 160, 0, 255, 4, 176, 66, 253], [192, 143, 24, 1, 160, 0, 255, 101, 14, 114, 66, 192, 143, 24, 1, 160, 0, 255, 101, 14, 114, 66, 192, 143, 24, 1, 160, 0, 255, 101, 14, 114, 66], [192, 143, 26, 1, 160, 0, 255, 5, 93, 178, 56, 192, 143, 26, 1, 160, 0, 255, 5, 93, 178, 56, 192, 143, 26, 1, 160, 0, 255, 5, 93, 178, 56], [192, 143, 28, 1, 160, 0, 255, 165, 168, 242, 183, 192, 143, 28, 1, 160, 0, 255, 165, 168, 242, 183, 192, 143, 28, 1, 160, 0, 255, 165, 168, 242, 183], [192, 143, 30, 1, 160, 0, 255, 197, 251, 50, 205, 192, 143, 30, 1, 160, 0, 255, 197, 251, 50, 205, 192, 143, 30, 1, 160, 0, 255, 197, 251, 50, 205], [192, 143, 16, 1, 160, 0, 255, 164, 69, 2, 114, 192, 143, 16, 1, 160, 0, 255, 164, 69, 2, 114, 192, 143, 16, 1, 160, 0, 255, 164, 69, 2, 114], [192, 143, 18, 1, 160, 0, 255, 196, 22, 194, 8, 192, 143, 18, 1, 160, 0, 255, 196, 22, 194, 8, 192, 143, 18, 1, 160, 0, 255, 196, 22, 194, 8], [192, 143, 20, 1, 160, 0, 255, 100, 227, 130, 135, 192, 143, 20, 1, 160, 0, 255, 100, 227, 130, 135, 192, 143, 20, 1, 160, 0, 255, 100, 227, 130, 135], [192, 143, 22, 1, 160, 0, 255, 4, 176, 66, 253, 192, 143, 22, 1, 160, 0, 255, 4, 176, 66, 253, 192, 143, 22, 1, 160, 0, 255, 4, 176, 66, 253], [192, 143, 24, 1, 160, 0, 255, 101, 14, 114, 66, 192, 143, 24, 1, 160, 0, 255, 101, 14, 114, 66, 192, 143, 24, 1, 160, 0, 255, 101, 14, 114, 66], [192, 143, 26, 1, 160, 0, 255, 5, 93, 178, 56, 192, 143, 26, 1, 160, 0, 255, 5, 93, 178, 56, 192, 143, 26, 1, 160, 0, 255, 5, 93, 178, 56], [192, 143, 28, 1, 160, 0, 255, 165, 168, 242, 183, 192, 143, 28, 1, 160, 0, 255, 165, 168, 242, 183, 192, 143, 28, 1, 160, 0, 255, 165, 168, 242, 183], [192, 143, 30, 1, 160, 0, 255, 197, 251, 50, 205, 192, 143, 30, 1, 160, 0, 255, 197, 251, 50, 205, 192, 143, 30, 1, 160, 0, 255, 197, 251, 50, 205], [192, 143, 16, 1, 160, 0, 255, 164, 69, 2, 114, 192, 143, 16, 1, 160, 0, 255, 164, 69, 2, 114, 192, 143, 16, 1, 160, 0, 255, 164, 69, 2, 114], [192, 143, 18, 1, 160, 0, 255, 196, 22, 194, 8, 192, 143, 18, 1, 160, 0, 255, 196, 22, 194, 8, 192, 143, 18, 1, 160, 0, 255, 196, 22, 194, 8], [192, 143, 20, 1, 160, 0, 255, 100, 227, 130, 135, 192, 143, 20, 1, 160, 0, 255, 100, 227, 130, 135, 192, 143, 20, 1, 160, 0, 255, 100, 227, 130, 135], [192, 143, 22, 1, 160, 0, 255, 4, 176, 66, 253, 192, 143, 22, 1, 160, 0, 255, 4, 176, 66, 253, 192, 143, 22, 1, 160, 0, 255, 4, 176, 66, 253], [224, 175, 23, 1, 160, 0, 255, 130, 156, 142, 199, 224, 1, 6, 139, 134, 161, 177, 224, 143, 82, 65, 160, 0, 255, 172, 50, 0, 108, 0, 0, 0, 0, 0, 0, 3, 0, 24, 0, 0, 0, 47, 142, 158, 155, 224, 97, 3, 163, 25, 54, 164, 224, 175, 25, 2, 160, 0, 255, 13, 141, 11, 106, 224, 1, 8, 140, 171, 25, 86, 224, 143, 36, 66, 160, 0, 255, 0, 0, 1, 255, 235, 230, 247, 249], [224, 97, 5, 150, 188, 85, 77, 224, 175, 27, 3, 160, 1, 255, 73, 136, 108, 177, 224, 1, 10, 160, 202, 23, 184, 224, 143, 38, 67, 160, 1, 255, 5, 16, 0, 0, 216, 144, 22, 207, 224, 97, 7, 186, 221, 91, 163, 224, 175, 29, 4, 161, 1, 255, 103, 47, 57, 162, 224, 1, 12, 149, 111, 116, 81, 224, 143, 24, 68, 161, 1, 255, 28, 253, 97, 246, 224, 1, 14, 185, 14, 122, 191, 224, 97, 11, 145, 145, 237, 170], [192, 143, 16, 1, 160, 0, 255, 164, 69, 2, 114, 192, 143, 16, 1, 160, 0, 255, 164, 69, 2, 114, 192, 143, 16, 1, 160, 0, 255, 164, 69, 2, 114, 224, 161, 17, 44, 145, 1, 39, 177, 155, 38, 148, 224, 161, 17, 44, 145, 1, 39, 177, 155, 38, 148, 224, 161, 17, 44, 145, 1, 39, 177, 155, 38, 148, 192, 143, 18, 1, 160, 0, 255, 196, 22, 194, 8, 192, 143, 18, 1, 160, 0, 255, 196, 22, 194, 8, 192, 143, 18, 1, 160, 0, 255, 196, 22, 194, 8], [224, 161, 17, 44, 145, 1, 39, 177, 155, 38, 148, 224, 1, 0, 190, 35, 194, 88, 224, 130, 16, 41, 164, 128, 18, 249, 127, 43, 73, 224, 97, 1, 143, 120, 56, 74, 224, 163, 3, 111, 172, 250, 93, 224, 1, 2, 146, 66, 204, 182], [224, 166, 5, 31, 253, 238, 201, 224, 1, 4, 167, 231, 175, 95], [192, 143, 20, 1, 160, 0, 255, 100, 227, 130, 135, 192, 143, 20, 1, 160, 0, 255, 100, 227, 130, 135, 192, 143, 20, 1, 160, 0, 255, 100, 227, 130, 135], [192, 143, 22, 1, 160, 0, 255, 4, 176, 66, 253, 192, 143, 22, 1, 160, 0, 255, 4, 176, 66, 253, 192, 143, 22, 1, 160, 0, 255, 4, 176, 66, 253], [192, 143, 24, 1, 160, 0, 255, 101, 14, 114, 66, 192, 143, 24, 1, 160, 0, 255, 101, 14, 114, 66, 192, 143, 24, 1, 160, 0, 255, 101, 14, 114, 66], [192, 143, 26, 1, 160, 0, 255, 5, 93, 178, 56, 192, 143, 26, 1, 160, 0, 255, 5, 93, 178, 56, 192, 143, 26, 1, 160, 0, 255, 5, 93, 178, 56], [192, 143, 28, 1, 160, 0, 255, 165, 168, 242, 183, 192, 143, 28, 1, 160, 0, 255, 165, 168, 242, 183, 192, 143, 28, 1, 160, 0, 255, 165, 168, 242, 183], [192, 143, 30, 1, 160, 0, 255, 197, 251, 50, 205, 192, 143, 30, 1, 160, 0, 255, 197, 251, 50, 205, 192, 143, 30, 1, 160, 0, 255, 197, 251, 50, 205], [192, 143, 16, 1, 160, 0, 255, 164, 69, 2, 114, 192, 143, 16, 1, 160, 0, 255, 164, 69, 2, 114, 192, 143, 16, 1, 160, 0, 255, 164, 69, 2, 114], [192, 143, 18, 1, 160, 0, 255, 196, 22, 194, 8, 192, 143, 18, 1, 160, 0, 255, 196, 22, 194, 8, 192, 143, 18, 1, 160, 0, 255, 196, 22, 194, 8], [192, 143, 20, 1, 160, 0, 255, 100, 227, 130, 135, 192, 143, 20, 1, 160, 0, 255, 100, 227, 130, 135, 192, 143, 20, 1, 160, 0, 255, 100, 227, 130, 135], [192, 143, 22, 1, 160, 0, 255, 4, 176, 66, 253, 192, 143, 22, 1, 160, 0, 255, 4, 176, 66, 253, 192, 143, 22, 1, 160, 0, 255, 4, 176, 66, 253], [192, 143, 24, 1, 160, 0, 255, 101, 14, 114, 66, 192, 143, 24, 1, 160, 0, 255, 101, 14, 114, 66, 192, 143, 24, 1, 160, 0, 255, 101, 14, 114, 66], [192, 143, 26, 1, 160, 0, 255, 5, 93, 178, 56, 192, 143, 26, 1, 160, 0, 255, 5, 93, 178, 56, 192, 143, 26, 1, 160, 0, 255, 5, 93, 178, 56], [192, 143, 28, 1, 160, 0, 255, 165, 168, 242, 183, 192, 143, 28, 1, 160, 0, 255, 165, 168, 242, 183, 192, 143, 28, 1, 160, 0, 255, 165, 168, 242, 183], [192, 143, 30, 1, 160, 0, 255, 197, 251, 50, 205, 192, 143, 30, 1, 160, 0, 255, 197, 251, 50, 205, 192, 143, 30, 1, 160, 0, 255, 197, 251, 50, 205], [192, 143, 16, 1, 160, 0, 255, 164, 69, 2, 114, 192, 143, 16, 1, 160, 0, 255, 164, 69, 2, 114, 192, 143, 16, 1, 160, 0, 255, 164, 69, 2, 114], [192, 143, 18, 1, 160, 0, 255, 196, 22, 194, 8, 192, 143, 18, 1, 160, 0, 255, 196, 22, 194, 8, 192, 143, 18, 1, 160, 0, 255, 196, 22, 194, 8], [192, 143, 20, 1, 160, 0, 255, 100, 227, 130, 135, 192, 143, 20, 1, 160, 0, 255, 100, 227, 130, 135, 192, 143, 20, 1, 160, 0, 255, 100, 227, 130, 135], [192, 143, 22, 1, 160, 0, 255, 4, 176, 66, 253, 192, 143, 22, 1, 160, 0, 255, 4, 176, 66, 253, 192, 143, 22, 1, 160, 0, 255, 4, 176, 66, 253], [224, 175, 23, 1, 160, 0, 255, 130, 156, 142, 199, 224, 1, 6, 139, 134, 161, 177, 224, 143, 82, 65, 160, 0, 255, 172, 50, 0, 108, 0, 0, 0, 0, 0, 0, 3, 0, 24, 0, 0, 0, 47, 142, 158, 155, 224, 97, 3, 163, 25, 54, 164, 224, 175, 25, 2, 160, 0, 255, 13, 141, 11, 106, 224, 1, 8, 140, 171, 25, 86, 224, 143, 36, 66, 160, 0, 255, 0, 0, 1, 255, 235, 230, 247, 249, 224, 97, 5, 150, 188, 85, 77, 224, 175, 27, 3, 160, 1, 255, 73, 136, 108, 177, 224, 1, 10, 160, 202, 23, 184, 224, 143, 38, 67, 160, 1, 255, 5, 16, 0, 0, 216, 144, 22, 207, 224, 97, 7, 186, 221, 91, 163, 224, 175, 29, 4, 161, 1, 255, 103, 47, 57, 162, 224, 1, 12, 149, 111, 116, 81, 224, 143, 24, 68, 161, 1, 255, 28, 253, 97, 246, 224, 175, 47, 16, 161, 1, 255, 1, 0, 0, 0, 229, 238, 114, 194, 224, 1, 14, 185, 14, 122, 191]]
# larger usb hub connected through separate cable
packets5 = [[192, 143, 16, 1, 160, 0, 255, 164, 69, 2, 114, 192, 65, 1, 45, 92, 188, 223, 192, 143, 81, 65, 160, 0, 255, 34, 5, 96, 28, 67, 9, 0, 0, 144, 1, 23, 10, 67, 38, 10, 17, 144, 140, 83, 42, 192, 65, 0, 187, 108, 187, 168, 224, 161, 17, 44, 145, 1, 39, 177, 155, 38, 148, 224, 65, 0, 187, 108, 187, 168, 224, 130, 16, 44, 177, 4, 19, 137, 131, 240, 76, 224, 97, 1, 143, 120, 56, 74, 224, 163, 3, 111, 172, 250, 93, 224, 65, 2, 151, 13, 181, 70], [224, 166, 5, 31, 253, 238, 201, 224, 65, 4, 162, 168, 214, 175], [224, 175, 23, 1, 160, 0, 255, 130, 156, 142, 199, 224, 65, 6, 142, 201, 216, 65, 224, 143, 82, 65, 160, 0, 255, 92, 29, 128, 109, 70, 66, 15, 0, 1, 7, 2, 113, 217, 0, 0, 17, 78, 127, 126, 152, 224, 97, 3, 163, 25, 54, 164, 224, 175, 25, 2, 160, 0, 255, 13, 141, 11, 106, 224, 65, 8, 137, 228, 96, 166, 224, 143, 36, 66, 160, 0, 255, 0, 0, 1, 255, 235, 230, 247, 249, 224, 97, 5, 150, 188, 85, 77], [192, 143, 18, 2, 160, 0, 255, 42, 185, 119, 26, 192, 65, 3, 1, 61, 178, 49, 192, 143, 49, 66, 160, 0, 255, 135, 128, 180, 4, 0, 0, 0, 0, 135, 24, 234, 31, 192, 65, 0, 187, 108, 187, 168, 224, 175, 27, 3, 160, 1, 255, 73, 136, 108, 177, 224, 65, 10, 165, 133, 110, 72, 224, 143, 38, 67, 160, 1, 255, 69, 0, 12, 0, 153, 36, 145, 228, 224, 97, 7, 186, 221, 91, 163, 224, 175, 29, 4, 161, 1, 255, 103, 47, 57, 162, 224, 65, 12, 144, 32, 13, 161, 224, 143, 24, 68, 161, 1, 255, 28, 253, 97, 246, 224, 97, 9, 189, 240, 227, 68, 224, 175, 47, 16, 161, 1, 255, 1, 0, 0, 0, 229, 238, 114, 194, 224, 65, 14, 188, 65, 3, 79, 224, 143, 42, 80, 161, 1, 255, 26, 0, 0, 0, 9, 186, 61, 105, 224, 97, 11, 145, 145, 237, 170], [224, 175, 33, 17, 161, 1, 255, 6, 8, 0, 0, 232, 92, 222, 85, 224, 65, 0, 187, 108, 187, 168, 224, 143, 28, 81, 161, 1, 255, 113, 252, 38, 100, 224, 97, 13, 164, 52, 142, 67], [224, 143, 46, 6, 161, 1, 255, 154, 0, 0, 0, 127, 167, 193, 74, 224, 97, 15, 136, 85, 128, 173], [224, 139, 0, 127, 83, 174, 153, 224, 97, 1, 143, 120, 56, 74, 224, 163, 3, 111, 172, 250, 93, 224, 65, 2, 151, 13, 181, 70, 224, 134, 2, 30, 76, 14, 194, 224, 97, 3, 163, 25, 54, 164], [224, 138, 4, 39, 166, 216, 135, 224, 97, 5, 150, 188, 85, 77, 224, 163, 5, 90, 9, 153, 180, 224, 65, 4, 162, 168, 214, 175], [224, 166, 6, 165, 172, 231, 80, 224, 65, 6, 142, 201, 216, 65], [224, 134, 7, 145, 184, 100, 178, 224, 97, 6, 44, 237, 92, 212, 192, 141, 0, 249, 244, 244, 207, 192, 65, 1, 45, 92, 188, 223, 192, 131, 1, 225, 233, 112, 38, 192, 65, 0, 187, 108, 187, 168], [192, 143, 18, 1, 160, 0, 255, 196, 22, 194, 8, 192, 65, 3, 1, 61, 178, 49, 192, 143, 83, 65, 160, 0, 255, 34, 5, 96, 28, 67, 9, 0, 0, 144, 1, 23, 10, 67, 38, 10, 17, 237, 141, 151, 206, 192, 65, 2, 151, 13, 181, 70], [224, 129, 81, 44, 145, 1, 46, 44, 209, 2, 0, 44, 193, 3, 0, 44, 177, 4, 0, 244, 65, 6, 0, 42, 247, 108, 228, 224, 97, 0, 25, 72, 63, 61, 224, 162, 16, 244, 209, 135, 82, 103, 102, 30, 241, 224, 65, 1, 45, 92, 188, 223, 224, 131, 3, 205, 136, 126, 200, 224, 97, 2, 53, 41, 49, 211], [224, 134, 5, 189, 217, 106, 92, 224, 97, 4, 0, 140, 82, 58, 224, 168, 2, 50, 69, 9, 201, 224, 65, 3, 1, 61, 178, 49, 224, 132, 23, 44, 145, 1, 46, 48, 66, 219, 53, 224, 97, 6, 44, 237, 92, 212, 224, 171, 4, 196, 179, 71, 11, 224, 65, 5, 52, 152, 209, 216, 224, 131, 9, 211, 97, 171, 40, 224, 97, 8, 43, 192, 228, 51, 224, 166, 6, 165, 172, 231, 80, 224, 65, 7, 24, 249, 223, 54], [224, 143, 43, 6, 161, 1, 255, 154, 1, 0, 0, 7, 136, 148, 1, 224, 97, 10, 7, 161, 234, 221, 224, 143, 45, 6, 161, 1, 255, 154, 1, 0, 0, 141, 241, 142, 114, 224, 97, 12, 50, 4, 137, 52, 224, 143, 47, 6, 161, 1, 255, 154, 1, 0, 0, 11, 217, 120, 92, 224, 97, 14, 30, 101, 135, 218, 224, 143, 33, 6, 161, 1, 255, 154, 1, 0, 0, 153, 2, 186, 148, 224, 97, 0, 25, 72, 63, 61, 224, 143, 35, 6, 161, 1, 255, 154, 1, 0, 0, 31, 42, 76, 186, 224, 97, 2, 53, 41, 49, 211], [224, 143, 37, 6, 161, 1, 255, 154, 1, 0, 0, 149, 83, 86, 201, 224, 97, 4, 0, 140, 82, 58, 224, 143, 39, 6, 161, 1, 255, 154, 1, 0, 0, 19, 123, 160, 231, 224, 97, 6, 44, 237, 92, 212, 224, 143, 41, 6, 161, 1, 255, 154, 1, 0, 0, 129, 160, 98, 47, 224, 97, 8, 43, 192, 228, 51, 224, 143, 43, 6, 161, 1, 255, 154, 1, 0, 0, 7, 136, 148, 1, 224, 97, 10, 7, 161, 234, 221], [224, 143, 45, 6, 161, 1, 255, 154, 1, 0, 0, 141, 241, 142, 114, 224, 97, 12, 50, 4, 137, 52], [224, 143, 47, 6, 161, 1, 255, 154, 1, 0, 0, 11, 217, 120, 92, 224, 97, 14, 30, 101, 135, 218], [224, 143, 33, 6, 161, 1, 255, 154, 1, 0, 0, 153, 2, 186, 148, 224, 97, 0, 25, 72, 63, 61, 224, 143, 35, 6, 161, 1, 255, 154, 1, 0, 0, 31, 42, 76, 186, 224, 97, 2, 53, 41, 49, 211, 224, 143, 37, 6, 161, 1, 255, 154, 1, 0, 0, 149, 83, 86, 201, 224, 97, 4, 0, 140, 82, 58, 224, 143, 39, 6, 161, 1, 255, 154]]
# framework hdmi card
packets6 = [[192, 143, 16, 1, 160, 0, 255, 164, 69, 2, 114, 192, 143, 16, 1, 160, 0, 255, 164, 69, 2, 114, 192, 143, 16, 1, 160, 0, 255, 164, 69, 2, 114, 224, 161, 17, 44, 145, 1, 39, 177, 155, 38, 148, 224, 161, 17, 44, 145, 1, 39, 177, 155, 38, 148, 224, 161, 17, 44, 145, 1, 39, 177, 155, 38, 148, 192, 143, 18, 1, 160, 0, 255, 196, 22, 194, 8, 192, 143, 18, 1, 160, 0, 255, 196, 22, 194, 8, 192, 143, 18, 1, 160, 0, 255, 196, 22, 194, 8], [224, 161, 17, 44, 145, 1, 39, 177, 155, 38, 148, 224, 1, 0, 190, 35, 194, 88, 224, 130, 16, 68, 16, 129, 18, 170, 55, 43, 91, 224, 97, 1, 143, 120, 56, 74, 224, 163, 3, 111, 172, 250, 93, 224, 1, 2, 146, 66, 204, 182], [224, 166, 5, 31, 253, 238, 201, 224, 1, 4, 167, 231, 175, 95], [192, 143, 20, 1, 160, 0, 255, 100, 227, 130, 135, 192, 143, 20, 1, 160, 0, 255, 100, 227, 130, 135, 192, 143, 20, 1, 160, 0, 255, 100, 227, 130, 135], [192, 143, 22, 1, 160, 0, 255, 4, 176, 66, 253, 192, 143, 22, 1, 160, 0, 255, 4, 176, 66, 253, 192, 143, 22, 1, 160, 0, 255, 4, 176, 66, 253], [192, 143, 24, 1, 160, 0, 255, 101, 14, 114, 66, 192, 143, 24, 1, 160, 0, 255, 101, 14, 114, 66, 192, 143, 24, 1, 160, 0, 255, 101, 14, 114, 66], [192, 143, 26, 1, 160, 0, 255, 5, 93, 178, 56, 192, 143, 26, 1, 160, 0, 255, 5, 93, 178, 56, 192, 143, 26, 1, 160, 0, 255, 5, 93, 178, 56], [192, 143, 28, 1, 160, 0, 255, 165, 168, 242, 183, 192, 143, 28, 1, 160, 0, 255, 165, 168, 242, 183, 192, 143, 28, 1, 160, 0, 255, 165, 168, 242, 183], [192, 143, 30, 1, 160, 0, 255, 197, 251, 50, 205, 192, 143, 30, 1, 160, 0, 255, 197, 251, 50, 205, 192, 143, 30, 1, 160, 0, 255, 197, 251, 50, 205], [192, 143, 16, 1, 160, 0, 255, 164, 69, 2, 114, 192, 143, 16, 1, 160, 0, 255, 164, 69, 2, 114, 192, 143, 16, 1, 160, 0, 255, 164, 69, 2, 114], [192, 143, 18, 1, 160, 0, 255, 196, 22, 194, 8, 192, 143, 18, 1, 160, 0, 255, 196, 22, 194, 8, 192, 143, 18, 1, 160, 0, 255, 196, 22, 194, 8], [192, 143, 20, 1, 160, 0, 255, 100, 227, 130, 135, 192, 143, 20, 1, 160, 0, 255, 100, 227, 130, 135, 192, 143, 20, 1, 160, 0, 255, 100, 227, 130, 135], [192, 143, 22, 1, 160, 0, 255, 4, 176, 66, 253, 192, 143, 22, 1, 160, 0, 255, 4, 176, 66, 253, 192, 143, 22, 1, 160, 0, 255, 4, 176, 66, 253], [192, 143, 24, 1, 160, 0, 255, 101, 14, 114, 66, 192, 143, 24, 1, 160, 0, 255, 101, 14, 114, 66, 192, 143, 24, 1, 160, 0, 255, 101, 14, 114, 66], [192, 143, 26, 1, 160, 0, 255, 5, 93, 178, 56, 192, 143, 26, 1, 160, 0, 255, 5, 93, 178, 56, 192, 143, 26, 1, 160, 0, 255, 5, 93, 178, 56], [192, 143, 28, 1, 160, 0, 255, 165, 168, 242, 183, 192, 143, 28, 1, 160, 0, 255, 165, 168, 242, 183, 192, 143, 28, 1, 160, 0, 255, 165, 168, 242, 183], [192, 143, 30, 1, 160, 0, 255, 197, 251, 50, 205, 192, 143, 30, 1, 160, 0, 255, 197, 251, 50, 205, 192, 143, 30, 1, 160, 0, 255, 197, 251, 50, 205], [192, 143, 16, 1, 160, 0, 255, 164, 69, 2, 114, 192, 143, 16, 1, 160, 0, 255, 164, 69, 2, 114, 192, 143, 16, 1, 160, 0, 255, 164, 69, 2, 114], [192, 143, 18, 1, 160, 0, 255, 196, 22, 194, 8, 192, 143, 18, 1, 160, 0, 255, 196, 22, 194, 8, 192, 143, 18, 1, 160, 0, 255, 196, 22, 194, 8], [192, 143, 20, 1, 160, 0, 255, 100, 227, 130, 135, 192, 143, 20, 1, 160, 0, 255, 100, 227, 130, 135, 192, 143, 20, 1, 160, 0, 255, 100, 227, 130, 135], [192, 143, 22, 1, 160, 0, 255, 4, 176, 66, 253, 192, 143, 22, 1, 160, 0, 255, 4, 176, 66, 253, 192, 143, 22, 1, 160, 0, 255, 4, 176, 66, 253], [224, 175, 23, 1, 160, 0, 255, 130, 156, 142, 199, 224, 1, 6, 139, 134, 161, 177, 224, 143, 82, 65, 160, 0, 255, 172, 50, 0, 108, 0, 0, 0, 0, 0, 0, 2, 0, 24, 0, 0, 0, 138, 93, 194, 80, 224, 97, 3, 163, 25, 54, 164, 224, 175, 25, 2, 160, 0, 255, 13, 141, 11, 106, 224, 1, 8, 140, 171, 25, 86, 224, 143, 36, 66, 160, 0, 255, 0, 0, 1, 255, 235, 230, 247, 249, 224, 97, 5, 150, 188, 85, 77, 224, 175, 27, 3, 160, 1, 255, 73, 136, 108, 177, 224, 1, 10, 160, 202, 23, 184, 224, 143, 38, 67, 160, 1, 255, 5, 4, 0, 0, 116, 155, 57, 212, 224, 97, 7, 186, 221, 91, 163, 224, 175, 29, 4, 161, 1, 255, 103, 47, 57, 162, 224, 1, 12, 149, 111, 116, 81, 224, 143, 24, 68, 161, 1, 255, 28, 253, 97, 246, 224, 175, 47, 16, 161, 1, 255, 1, 0, 0, 0, 229, 238, 114, 194, 224, 1, 14, 185, 14, 122, 191, 224, 175, 33, 17, 161, 1, 255, 6, 4, 0, 0, 140, 165, 196, 92, 224, 1, 0, 190, 35, 194, 88, 224, 143, 28, 81, 161, 1, 255, 113, 252, 38, 100, 224, 97, 13, 164, 52, 142, 67]]

packets_pos = [ 0,0 ] # hoot-hoot,,, hewwo ;-P

def record_flow():
  while True:
    if fusb.rxb_state()[0] == 0:
        print(get_buffer_fast())
        #print(fusb.get_rxb(80))
        #print(get_message())
    sleep(0.0001)

def get_buffer_fast():
    packet = []
    while fusb.rxb_state()[0] == 0:
        packet.append(fusb.get_rxb(1)[0])
    packets.append(packet)
    return packet

def gb():
    fun = postfactum_readout if listen else fusb.get_rxb
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
    fusb.reset()
    fusb.power()
    fusb.unmask_all()
    if is_source:
        fusb.set_controls_source()
    else:
        fusb.set_controls_sink()

    if listen:
        cc = listen_cc
        fusb.flush_receive()
        fusb.disable_pulldowns()
        sleep(0.2)
        fusb.read_cc(cc)
        fusb.enable_sop()
        fusb.flush_transmit()
        fusb.flush_receive()
        fusb.reset_pd()
        record_flow()
    elif is_source:
        fusb.set_roles(power_role=1)
        fusb.set_power_rail('off')
        fusb.disable_pulldowns()
        fusb.set_wake(True)
        fusb.enable_pullups()
        fusb.set_mdac(0b111111)
        cc = fusb.find_cc(fn="measure_source", debug=True)
        while cc == 0:
            cc = fusb.find_cc(fn="measure_source")
        cc = fusb.find_cc(fn="measure_source", debug=True)
        set_power_rail('5V')
        source_flow()
    else: # sink
        fusb.set_roles()
        fusb.set_wake(True)
        fusb.set_mdac(0b100)
        cc = 0
        cc = fusb.find_cc(fn="measure_sink", debug=True)
        while cc == 0:
            cc = fusb.find_cc(fn="measure_sink")
        cc = fusb.find_cc(fn="measure_sink", debug=True)
        sink_flow()

#listen = 1; packets = packets1; gba()

while True:
    try:
        loop()
    except KeyboardInterrupt:
        sleep(1)
