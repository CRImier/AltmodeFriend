from time import sleep
import sys

########################
#
# Specification data
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

########################
#
# USB-C stacc code
#
########################

class PDStacc():
    pdo_requested = False
    pdos = []

    sent_messages = []

    # set to -1 because it's incremented before each command is sent out
    msg_id = -1

    def __init__(self, fusb):
        self.fusb = fusb

    def init_fusb(self):
        self.fusb.reset()
        self.fusb.power()
        self.fusb.unmask_all()

    def setup_sink(self):
        #self.fusb.enable_pulldowns()
        self.fusb.set_controls_sink()
        self.fusb.set_roles()
        self.fusb.set_wake(True)
        self.fusb.set_mdac(0b100)
        cc = 0
        cc = self.fusb.find_cc(fn="measure_sink", debug=True)
        while cc == 0:
            cc = self.fusb.find_cc(fn="measure_sink")
        cc = self.fusb.find_cc(fn="measure_sink", debug=True)
        self.cc = cc

    def setup_listen(self, cc):
        self.fusb.flush_receive()
        self.fusb.disable_pulldowns()
        sleep(0.2)
        self.fusb.read_cc(cc)
        self.fusb.enable_sop()
        self.fusb.flush_transmit()
        self.fusb.flush_receive()
        self.fusb.reset_pd()

    def setup_source(self):
        self.fusb.set_controls_source()
        self.fusb.set_roles(power_role=1)
        self.fusb.disable_pulldowns()
        self.fusb.set_wake(True)
        self.fusb.enable_pullups()
        self.fusb.set_mdac(0b111111)
        cc = self.fusb.find_cc(fn="measure_source", debug=True)
        while cc == 0:
            cc = self.fusb.find_cc(fn="measure_source")
        cc = self.fusb.find_cc(fn="measure_source", debug=True)
        self.cc = cc
        self.set_5v_power_rail_cb()

    def increment_msg_id(self):
        self.msg_id += 1
        if self.msg_id == 8: msg_id = 0
        return self.msg_id

    def reset_msg_id(self):
        self.msg_id = -1

    packets = []

    def flow_source(self, psu_advertisement):
        counter = 0
        advertisement_counter = 1
        self.reset_msg_id()
        sleep(0.3)
        print("sending advertisement")
        self.send_advertisement(psu_advertisement)
        self.profile_selected = False
        try:
            timeout = 0.00001
            while True:
                if self.fusb.rxb_state()[0] == 0: # buffer non-empty
                    d = get_message()
                    self.packets.append(d)
                    msg_types = control_message_types if d["c"] else data_message_types
                    msg_name = msg_types[d["t"]]
                    # now we do things depending on the message type that we received
                    if msg_name == "GoodCRC": # example
                        print("GoodCRC")
                    elif msg_name == "Request":
                        self.profile_selected = True
                        self.process_psu_request(psu_advertisement, d)
                    self.show_msg(d)
                for message in self.sent_messages:
                    sys.stdout.write('> ')
                    sys.stdout.write(myhex(message))
                    sys.stdout.write('\n')
                self.sent_messages = []
                sleep(timeout) # so that ctrlc works
                counter += 1
                if counter == 10000:
                    counter = 0
                    if not self.profile_selected and advertisement_counter < 30:
                        print("sending advertisement")
                        self.send_advertisement(psu_advertisement)
                        advertisement_counter += 1
                if self.fusb.int_p.value() == 0:
                    i = self.fusb.interrupts()
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
                        cc = self.fusb.find_cc(fn="measure_source")
                        if cc == 0:
                            print("Disconnect detected!")
                            return # we exiting this
                    if i_reg & 0x10: # I_CRC_CHK
                        pass # new CRC, just a side effect of CC comms
                    if i_reg & 0x8: # I_ALERT
                        print("I_ALERT")
                        x = self.fusb.bus.readfrom_mem(0x22, 0x41, 1)[0] # TODO export
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

    def flow_sink(self):
        self.pdo_requested = False # not sure this needs to be here
        self.reset_msg_id()
        try:
            timeout = 0.00001
            while True:
                if self.fusb.rxb_state()[0] == 0: # buffer non-empty
                    d = self.get_message()
                    self.packets.append(d)
                    msg_types = control_message_types if d["c"] else data_message_types
                    msg_name = msg_types[d["t"]]
                    # now we do things depending on the message type that we received
                    if msg_name == "GoodCRC": # example
                        pass # print("GoodCRC")
                    elif msg_name == "Source_Capabilities":
                        # need to request a PDO!
                        self.pdos = self.get_pdos(d)
                        pdo_i, current = self.select_pdo(self.pdos)
                        # sending a message, need to increment message id
                        self.request_fixed_pdo(pdo_i, current, current)
                        # print("PDO requested!")
                        self.pdo_requested = True
                        sys.stdout.write(str(self.pdos))
                        sys.stdout.write('\n')
                    elif msg_name in ["Accept", "PS_RDY"]:
                        self.process_accept_cb(d)
                    elif msg_name == "Vendor_Defined":
                        self.parse_vdm(d)
                        self.react_vdm(d)
                    self.show_msg(d)
                    for message in self.sent_messages:
                        sys.stdout.write('> ')
                        sys.stdout.write(myhex(message))
                        sys.stdout.write('\n')
                    self.sent_messages = []
                sleep(timeout) # so that ctrlc works
                if self.fusb.int_p.value() == 0:
                    # needs sink detach processing here lmao
                    i = self.fusb.interrupts()
                    print(i)
                    i_reg = i[2]
                    if i_reg & 0x80: # I_VBUSOK
                        pass # just a side effect of vbus being attached
                    if i_reg & 0x40: # I_ACTIVITY
                        print("I_ACTIVITY")
                        pass # just a side effect of CC comms I think?
                    if i_reg & 0x20: # I_COMP_CHNG
                        print("I_COMP_CHNG")
                        cc = self.fusb.find_cc(fn="measure_sink")
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

    header_starts = [0xe0, 0xc0]

    def get_message(self, get_rxb="get_rxb"):
        if isinstance(get_rxb, str):
            get_rxb = getattr(self.fusb, get_rxb)
        header = 0
        d = {}
        # we might have to get through some message data!
        while header not in self.header_starts:
            header = get_rxb(1)[0]
            if header == 0:
                return
            if header not in self.header_starts:
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
            self.parse_vdm(d)
        return d

    def show_msg(self, d):
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
            self.print_vdm(d)
            #sys.stdout.write(str(d["d"]))
            #sys.stdout.write('\n')
        elif msg_type_str == "Source_Capabilities":
            sys.stdout.write(str(self.get_pdos(d)))
            sys.stdout.write('\n')
        return d

    ########################
    #
    # PDO parsing code
    #
    ########################

    pdo_types = ['fixed', 'batt', 'var', 'pps']
    pps_types = ['spr', 'epr', 'res', 'res']

    def parse_capability_pdo(self, pdo):
        pdo_t = self.pdo_types[pdo[3] >> 6]
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
            return ('pps', self.pps_types[t], max_voltage, min_voltage, max_current, limited)

    def create_pdo(self, pdo_t, *args):
        print(pdo_t, *args)
        assert(pdo_t in self.pdo_types)
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
            pdo[3] |= self.pdo_types.index(pdo_t) << 6
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
        print(self.parse_capability_pdo(bytes(pdo)))
        return pdo

    def get_pdos(self, d):
        pdo_list = []
        pdos = d["d"]
        for pdo_i in range(d["dc"]):
            pdo_bytes = pdos[(pdo_i*4):][:4]
            #print(myhex(pdo_bytes))
            parsed_pdo = self.parse_capability_pdo(pdo_bytes)
            pdo_list.append(parsed_pdo)
        return pdo_list

    ########################
    #
    # Command sending code
    # and simple commands
    #
    ########################

    def send_command(self, command, data, msg_id=None, rev=0b10, power_role=0, data_role=0):
        p = [command, data, msg_id, rev, power_role, data_role]
        self.packets.append(p)
        msg_id = self.increment_msg_id() if msg_id is None else msg_id
        obj_count = len(data) // 4

        header = [0, 0] # hoot hoot !

        header[0] |= rev << 6 # PD revision
        header[0] |= (data_role & 0b1) << 5 # PD revision
        header[0] |= (command & 0b11111)

        header[1] = power_role & 0b1
        header[1] |= (msg_id & 0b111) << 1 # message ID
        header[1] |= obj_count << 4

        message = header+data

        self.fusb.send(message)

        self.sent_messages.append(message)

    def soft_reset(self):
        self.send_command(0b01101, [])
        self.reset_msg_id()

    ########################
    #
    # PSU request processing code
    #
    ########################

    def send_advertisement(self, psu_advertisement):
        #data = [bytes(a) for a in psu_advertisement]
        data = psu_advertisement
        self.send_command(0b1, data, power_role=1, data_role=1)

    def process_psu_request(self, d):
        print(d)
        profile = ((d["d"][3] >> 4)&0b111)-1
        print("Selected profile", profile)
        if not self.validate_profile_cb(profile, d):
            print("Profile", profile, "not handled!")
            return False
            #TODO respose that profile request is not valid!!!
        self.send_command(0b11, [], power_role=1, data_role=1) # Accept
        # external callback
        self.switch_to_profile_cb(profile, d)
        sleep(0.1)
        self.send_command(0b110, [], power_role=1, data_role=1) # PS_RDY

    ########################
    #
    # PDO request code
    #
    ########################

    def request_fixed_pdo(self, num, current, max_current):
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

        self.send_command(0b00010, pdo)

    def request_pps_pdo(self, num, voltage, current):
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

        self.send_command(0b00010, pdo)

    def flow_record(self, packets):
        while True:
            if self.fusb.rxb_state()[0] == 0:
                print(self.get_buffer_fast(packets))
                #print(self.fusb.get_rxb(80))
                #print(get_message())
            sleep(0.0001)

    def get_buffer_fast(self, packets):
        packet = []
        while self.fusb.rxb_state()[0] == 0:
            packet.append(self.fusb.get_rxb(1)[0])
        packets.append(packet)
        return packet

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

    def react_vdm(self, d):
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
                r = self.create_vdm_data(rd, data[4:])
                print(r)
                print(data)
                self.send_command(d["t"], r)
                #sys.stdout.write("a") # debug stuff
            elif command_name == "Discover SVIDs":
                data = list(b'B\xA0\x00\xff\x00\x00\x01\xff')
                r = self.create_vdm_data(rd, data[4:])
                print(r)
                print(data)
                self.send_command(d["t"], r)
                #sys.stdout.write("b")
            elif command_name == "Discover Modes":
                #data = list(b'C\xA0\x01\xff\x45\x04\x00\x00')
                data = list(b'C\xA0\x01\xff\x05\x0c\x00\x00')
                r = self.create_vdm_data(rd, data[4:])
                print(r)
                print(data)
                self.send_command(d["t"], r)
                #sys.stdout.write("c")
            elif command_name == "Enter Mode":
                data = list(b'D\xA1\x01\xff')
                r = self.create_vdm_data(rd, [])
                print(r)
                print(data)
                self.send_command(d["t"], r)
                #sys.stdout.write("d")
            elif command_name == "DP Status Update":
                #data = list(b'P\xA1\x01\xff\x1a\x00\x00\x00')
                data = list(b'P\xA1\x01\xff\x9a\x00\x00\x00')
                r = self.create_vdm_data(rd, data[4:])
                print(r)
                print(data)
                self.send_command(d["t"], r)
                #sys.stdout.write("e")
            elif command_name == "DP Configure":
                data = list(b'Q\xA1\x01\xff')
                r = self.create_vdm_data(rd, [])
                print(r)
                print(data)
                self.send_command(d["t"], r)
                #sys.stdout.write("f")
        # no unstructured vdm processing at this time

    def create_vdm_data(self, d, data):
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

    def parse_vdm(self, d):
        data = d['d']
        is_structured = data[1] >> 7
        d["vdm_s"] = is_structured
        svid = (data[3] << 8) + data[2]
        d["vdm_sv"] = svid
        svid_name = self.svids.get(svid, "Unknown ({})".format(hex(svid)))
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
                    command_name = self.dp_commands.get(command, command_name)
            else:
                command_name = self.vdm_commands[command] if command < 7 else "Reserved"
            d["vdm_cn"] = command_name
            #if svid_name == "DisplayPort":
            #    parse_dp_command(version_str())
        else:
            vdmd = [data[1] & 0x7f, data[0]]
            d["vdm_d"] = vdmd
        #print(d)

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

    def print_vdm(self, d):
        if d["vdm_s"]:
            svid_name = d["vdm_svn"]
            version_str = mybin([d["vdm_v"]])[4:]
            objpos_str = mybin([d["vdm_o"]])[5:]
            cmd_type_name = self.vdm_cmd_types[d["vdm_ct"]]
            cmd_name = d["vdm_cn"]
            sys.stdout.write("VDM: str, m{} v{} o{}, ct{}: {}\n".format(svid_name, version_str, objpos_str, cmd_type_name, cmd_name))
            if svid_name == "DisplayPort":
                if cmd_name == "Discover Modes" and cmd_type_name == "ACK":
                    msg = d['d'][4:]
                    # port capability (bits 0:1)
                    port_cap = msg[0] & 0b11
                    vdm_dp_port_cap_s = self.vdm_dp_port_cap[port_cap]
                    # signaling (bits 5:2)
                    sgn = (msg[0] >> 2) & 0b1111
                    sgn_s = []
                    for p in self.vdm_dp_sgn.keys():
                        if sgn & p:
                            sgn_s.append(self.vdm_dp_sgn[p])
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
                    for p in self.vdm_dp_pin_assg.keys():
                        if dfp_assy_n & p:
                            dfp_assy_s += self.vdm_dp_pin_assg[p]
                    # dfp pin assignments (bits 23:16)
                    ufp_assy_n = msg[2]
                    ufp_assy_s = ""
                    for p in self.vdm_dp_pin_assg.keys():
                        if ufp_assy_n & p:
                            ufp_assy_s += self.vdm_dp_pin_assg[p]
                    #res_byte = msg[3] # (bites 31:24, has to be 0)
                    sys.stdout.write("\tModes: p_cap:{} sgn:{} ri:{} u2:{} d_ass:{} u_ass:{}\n".format(vdm_dp_port_cap_s, sgn_s, r_s, u2_s, dfp_assy_s, ufp_assy_s))
                elif cmd_name == "DP Status Update":
                    msg = d['d'][4:]
                    # dfp/ufp connected (bits 0:1)
                    conn = msg[0] & 0b11
                    conn_s = self.vdm_dp_port_conn[conn]
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
                    conf_s = self.vdm_dp_port_conf[conf]
                    # signaling (bits 5:2)
                    sgn = (msg[0] >> 2) & 0b1111
                    sgn_s = []
                    for p in self.vdm_dp_sgn.keys():
                        if sgn & p:
                            sgn_s.append(self.vdm_dp_sgn[p])
                    sgn_s = ",".join(sgn_s)
                    if not sgn_s:
                        sgn_s = "UNSP"
                    # reserved (bits 7:6)
                    # ufp pin assignments (bits 15:8)
                    ufp_assy_n = msg[1]
                    ufp_assy_s = ""
                    for p in self.vdm_dp_pin_assg.keys():
                        if ufp_assy_n & p:
                            ufp_assy_s += self.vdm_dp_pin_assg[p]
                    #res_bytes = msg[2:] # (bytes 31:24, has to be 0)
                    sys.stdout.write("\tConfigure: conf:{} sgn:{} p_ass:{}\n".format(conf_s, sgn_s, ufp_assy_s))
                #di = d
                #breakpoint()
        else:
            sys.stdout.write("VDM: unstr, m{}, d{}".format(svid_name, myhex(d["vdm_d"])))

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

