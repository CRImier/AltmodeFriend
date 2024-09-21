from time import sleep

########################
#
# FUSB-specific code
#
########################

class FUSB302():
    #FUSB302_I2C_SLAVE_ADDR = 0x22
    REG_DEVICE_ID = 0x01
    REG_SWITCHES0 = 0x02
    REG_SWITCHES1 = 0x03
    REG_MEASURE = 0x04
    REG_CONTROL0 = 0x06
    REG_CONTROL1 = 0x07
    REG_CONTROL2 = 0x08
    REG_CONTROL3 = 0x09
    REG_MASK = 0x0A
    REG_POWER = 0x0B
    REG_RESET = 0x0C
    REG_MASKA = 0x0E
    REG_MASKB = 0x0F
    REG_STATUS0A = 0x3C
    REG_STATUS1A = 0x3D
    REG_INTERRUPTA = 0x3E
    REG_INTERRUPTB = 0x3F
    REG_STATUS0 = 0x40
    REG_STATUS1 = 0x41
    REG_INTERRUPT = 0x42
    REG_FIFOS = 0x43

    def __init__(self, bus, addr=0x22, int_p=None):
        self.bus = bus
        self.addr = addr
        self.int_p = int_p

    def reset(self):
        # reset the entire FUSB
        self.bus.writeto_mem(self.addr, self.REG_RESET, bytes([0b1]))

    def reset_pd(self):
        # resets the FUSB PD logic
        self.bus.writeto_mem(self.addr, self.REG_RESET, bytes([0b10]))

    def unmask_all(self):
        # unmasks all interrupts
        self.bus.writeto_mem(self.addr, self.REG_MASK, bytes([0b0]))
        self.bus.writeto_mem(self.addr, self.REG_MASKA, bytes([0b0]))
        self.bus.writeto_mem(self.addr, self.REG_MASKB, bytes([0b0]))

    def cc_current(self):
        # show measured CC level interpreted as USB-C current levels
        return self.bus.readfrom_mem(self.addr, self.REG_STATUS0, 1)[0] & 0b11

    def read_cc(self, cc):
        # enable a CC pin for reading
        assert(cc in [0, 1, 2])
        x = self.bus.readfrom_mem(self.addr, self.REG_SWITCHES0, 1)[0]
        x1 = x
        clear_mask = ~0b1100 & 0xFF
        x &= clear_mask
        mask = [0b0, 0b100, 0b1000][cc]
        x |= mask
        #print('self.REG_SWITCHES0: ', bin(x1), bin(x), cc)
        self.bus.writeto_mem(self.addr, self.REG_SWITCHES0, bytes((x,)) )

    def enable_pullups(self):
        # enable host pullups on CC pins, disable pulldowns
        x = self.bus.readfrom_mem(0x22, 0x02, 1)[0]
        x |= 0b11000000
        self.bus.writeto_mem(0x22, 0x02, bytes((x,)) )

    def set_mdac(self, value):
        x = self.bus.readfrom_mem(0x22, 0x04, 1)[0]
        x &= 0b11000000
        x |= value
        self.bus.writeto_mem(0x22, 0x04, bytes((x,)) )

    def enable_sop(self):
        # enable reception of SOP'/SOP" messages
        x = self.bus.readfrom_mem(self.addr, self.REG_CONTROL1, 1)[0]
        mask = 0b1100011
        x |= mask
        self.bus.writeto_mem(self.addr, self.REG_CONTROL1, bytes((x,)) )

    def disable_pulldowns(self):
        x = self.bus.readfrom_mem(self.addr, self.REG_SWITCHES0, 1)[0]
        clear_mask = ~0b11 & 0xFF
        x &= clear_mask
        self.bus.writeto_mem(self.addr, self.REG_SWITCHES0, bytes((x,)) )

    def enable_pulldowns(self):
        x = self.bus.readfrom_mem(self.addr, self.REG_SWITCHES0, 1)[0]
        x |= 0b11
        self.bus.writeto_mem(self.addr, self.REG_SWITCHES0, bytes((x,)) )

    def measure_sink(self, debug=False):
        # read CC pins and see which one senses the pullup
        self.read_cc(1)
        sleep(0.001)
        cc1_c = self.cc_current()
        self.read_cc(2)
        sleep(0.001)
        cc2_c = self.cc_current()
        # picking the CC pin depending on which pin can detect a pullup
        cc = [1, 2][cc1_c < cc2_c]
        if debug: print('m', bin(cc1_c), bin(cc2_c), cc)
        if cc1_c == cc2_c:
            return 0
        return cc

    def measure_source(self, debug=False):
        # read CC pins and see which one senses the correct host current
        self.read_cc(1)
        sleep(0.001)
        cc1_c = self.cc_current()
        self.read_cc(2)
        sleep(0.001)
        cc2_c = self.cc_current()
        if cc1_c == self.host_current:
            cc = 1
        elif cc2_c == self.host_current:
            cc = 2
        else:
            cc = 0
        if debug: print('m', bin(cc1_c), bin(cc2_c), cc)
        return cc

    def set_controls_sink(self):
        # boot: 0b00100100
        ctrl0 = 0b00000000 # unmask all interrupts; don't autostart TX.. disable pullup current
        self.bus.writeto_mem(self.addr, self.REG_CONTROL0, bytes((ctrl0,)) )
        # boot: 0b00000110
        ctrl3 = 0b00000111 # enable automatic packet retries
        self.bus.writeto_mem(self.addr, self.REG_CONTROL3, bytes((ctrl3,)) )

    host_current=0b10

    def set_controls_source(self):
        # boot: 0b00100100
        ctrl0 = 0b00000000 # unmask all interrupts; don't autostart TX
        ctrl0 |= self.host_current << 2 # set host current advertisement pullups
        self.bus.writeto_mem(self.addr, self.REG_CONTROL0, bytes((ctrl0,)) )
        self.bus.writeto_mem(0x22, 0x06, bytes((ctrl0,)) )
        # boot: 0b00000110
        ctrl3 = 0b00000110 # no automatic packet retries
        self.bus.writeto_mem(self.addr, self.REG_CONTROL3, bytes((ctrl3,)) )
        # boot: 0b00000010
        #ctrl2 = 0b00000000 # disable DRP toggle. setting it to Do Not Use o_o ???
        #self.bus.writeto_mem(self.addr, self.REG_CONTROL2, bytes((ctrl2,)) )

    def set_wake(self, state):
        # boot: 0b00000010
        ctrl2 = self.bus.readfrom_mem(0x22, 0x08, 1)[0]
        clear_mask = ~(1 << 3) & 0xFF
        ctrl2 &= clear_mask
        if state:
            ctrl2 | (1 << 3)
        self.bus.writeto_mem(0x22, 0x08, bytes((ctrl2,)) )

    def flush_receive(self):
        x = self.bus.readfrom_mem(self.addr, self.REG_CONTROL1, 1)[0]
        mask = 0b100 # flush receive
        x |= mask
        self.bus.writeto_mem(self.addr, self.REG_CONTROL1, bytes((x,)) )

    def flush_transmit(self):
        x = self.bus.readfrom_mem(self.addr, self.REG_CONTROL0, 1)[0]
        mask = 0b01000000 # flush transmit
        x |= mask
        self.bus.writeto_mem(self.addr, self.REG_CONTROL0, bytes((x,)) )

    def enable_tx(self, cc):
        # enables switch on either CC1 or CC2
        x = self.bus.readfrom_mem(self.addr, self.REG_SWITCHES1, 1)[0]
        x1 = x
        mask = 0b10 if cc == 2 else 0b1
        x &= 0b10011100 # clearing both TX bits and revision bits
        x |= mask
        x |= 0b100
        x |= 0b10 << 5 # revision 3.0
        #print('et', bin(x1), bin(x), cc)
        self.bus.writeto_mem(self.addr, self.REG_SWITCHES1, bytes((x,)) )

    def set_roles(self, power_role = 0, data_role = 0):
        x = self.bus.readfrom_mem(0x22, 0x03, 1)[0]
        x &= 0b01101111 # clearing both role bits
        x |= power_role << 7
        x |= data_role << 7
        self.bus.writeto_mem(0x22, 0x03, bytes((x,)) )

    def power(self):
        # enables all power circuits
        x = self.bus.readfrom_mem(self.addr, self.REG_POWER, 1)[0]
        mask = 0b1111
        x |= mask
        self.bus.writeto_mem(self.addr, self.REG_POWER, bytes((x,)) )

    def polarity(self):
        # reads polarity and role bits from STATUS1A
        return (self.bus.readfrom_mem(self.addr, self.REG_STATUS1A, 1)[0] >> 3) & 0b111
        #'0b110001'

    def interrupts(self):
        # return all interrupt registers
        return self.bus.readfrom_mem(self.addr, self.REG_INTERRUPTA, 2)+self.bus.readfrom_mem(self.addr, self.REG_INTERRUPT, 1)

    # interrupts are cleared just by reading them, it seems
    #def clear_interrupts(self):
    #    # clear interrupt
    #    self.bus.writeto_mem(self.addr, self.REG_INTERRUPTA, bytes([0]))
    #    self.bus.writeto_mem(self.addr, self.REG_INTERRUPT, bytes([0]))

    # this is a way better way to do things than the following function -
    # the read loop should be ported to this function, and the next ome deleted
    def rxb_state(self):
        # get read buffer interrupt states - (rx buffer empty, rx buffer full)
        st = self.bus.readfrom_mem(self.addr, self.REG_STATUS1, 1)[0]
        return ((st & 0b100000) >> 5, (st & 0b10000) >> 4)

    # TODO: yeet
    def rxb_state(self):
        st = self.bus.readfrom_mem(self.addr, self.REG_STATUS1, 1)[0]
        return ((st & 0b110000) >> 4, (st & 0b11000000) >> 6)

    def get_rxb(self, l=80):
        # read from FIFO
        return self.bus.readfrom_mem(self.addr, self.REG_FIFOS, l)

    def hard_reset(self):
        self.bus.writeto_mem(self.addr, self.REG_CONTROL3, bytes([0b1000000]))
        return self.bus.readfrom_mem(self.addr, self.REG_CONTROL3, 1)

    def find_cc(self, fn="measure_sink", debug=False):
        if isinstance(fn, str):
            fn = getattr(self, fn)
        cc = fn(debug=debug)
        self.flush_receive()
        self.enable_tx(cc)
        self.read_cc(cc)
        self.flush_transmit()
        self.flush_receive()
        #import gc; gc.collect()
        self.reset_pd()
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

    def p_pol(self):
        return polarity_values[self.polarity()]

    def p_int(self, a=None):
        if a is None:
            a = self.interrupts()
        return [bin(x) for x in a]

    def p_cur(self):
        return current_values[self.cc_current()]

    def send(self, message):
        sop_seq = [0x12, 0x12, 0x12, 0x13, 0x80]
        eop_seq = [0xff, 0x14, 0xfe, 0xa1]

        sop_seq[4] |= len(message)

        self.bus.writeto_mem(self.addr, self.REG_FIFOS, bytes(sop_seq) )
        self.bus.writeto_mem(self.addr, self.REG_FIFOS, bytes(message) )
        self.bus.writeto_mem(self.addr, self.REG_FIFOS, bytes(eop_seq) )
