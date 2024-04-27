"""
Classes to assist with testing. PinEvent is a simple container of old and new values. StateTrackable is a
base class that records a series of state changes described as PinEvents. Pin, PWM and ADC are mocks that
extend StateTrackable.
"""

from mock import Mock
import time
time.ticks_us = Mock()
time.ticks_diff = Mock()

class PinEvent:
    def __init__(self, old_value, new_value):
        self.event_id = None
        self.old_value = old_value
        self.new_value = new_value

    def set_id(self, event_id):
        self.event_id = event_id

    def __str__(self):
        return "Event {} with old value {}, new value {}".format(self.event_id, self.old_value, self.new_value)


class StateTrackable:
    def __init__(self):
        self.events = []
        self.event_id = 1

    def record_event(self, event: PinEvent):
        event.set_id(self.event_id)
        self.events.append(event)
        self.event_id += 1

    def get_event(self, event_id: int) -> PinEvent:
        for e in self.events:
            if e.event_id == event_id:
                return e

    def __str__(self):
        return "{}".format(self.events)


class Pin(StateTrackable):

    OPEN_DRAIN = 2
    IRQ_FALLING = 4
    IRQ_RISING = 8
    IN = 0
    OUT = 1
    PULL_UP = 1
    PULL_DOWN = 2

    def __init__(self, id, mode=IN, value=None):
        super().__init__()
        self.id = id
        self.mock_value = None
        self.mode = mode
        self.pull = None
        self.irq_falling_handler = None
        self.irq_rising_handler = None

    def init(self, mode=IN, pull=None):
        self.mock_value = None
        self.mode = mode
        self.pull = pull

    def value(self, value=None):
        if value is None:
            return self.mock_value
        event = PinEvent(self.mock_value, value)
        self.record_event(event)
        self.mock_value = event.new_value
        if self.irq_rising_handler is not None:
            if event.old_value is None or event.new_value > event.old_value:
                self.irq_rising_handler(self)
        if self.irq_falling_handler is not None:
            if event.new_value is not None and event.new_value < event.old_value:
                self.irq_falling_handler(self)

    def irq(self, handler, trigger: int = (IRQ_FALLING | IRQ_RISING | OPEN_DRAIN), priority: int = 1,
            wake: int = None, hard: bool = False):
        if trigger & self.IRQ_FALLING:
            self.irq_falling_handler = handler
        if trigger & self.IRQ_RISING:
            self.irq_rising_handler = handler

    def on(self):
        self.value(1)

    def off(self):
        self.value(0)

    def toggle(self):
        self.value(self.value() - 1) * -1

    def __str__(self):
        # Do not change the first 7 characters or it will break code to retrieve pin id
        return "Pin({}, mode=ALT, pull=PULL_DOWN, alt=31)".format(self.id)


class BusMessage:
    def __init__(self, payload):
        self.message_id = None
        self.payload = payload

    def set_message_id(self, message_id):
        self.message_id = message_id

    def __str__(self):
        return self.payload


class BusMessageGenerator:

    def __init__(self):
        self._messages = {}

    def add(self, message: bytes, addr: int = 0x00):
        if addr not in self._messages:
            self._messages[addr] = list()
        bus_message = BusMessage(payload=message)
        bus_message.set_message_id(len(self._messages[addr]) + 1)
        self._messages[addr].append(bus_message)

    def next(self, addr: int = 0x00) -> bytes:
        # in lieu of shift()...
        self._messages[addr].reverse()
        first = self._messages[addr].pop()
        self._messages[addr].reverse()
        return first

    def has_next(self, addr: int = 0x00) -> bool:
        return len(self._messages[addr]) > 0


class Bus:

    def __init__(self):
        self._generator = BusMessageGenerator()
        self._messages = {}

    @property
    def generator(self) -> BusMessageGenerator:
        return self._generator

    def get_current_message(self, addr: int = 0x00) -> BusMessage:
        if addr not in self._messages:
            raise Exception("No messages yet for {}", addr)
        max_id = len(self._messages[addr])
        return self.get_message(addr, max_id)

    def record_message(self, message, addr:int = 0x00) -> None:
        if addr not in self._messages:
            self._messages[addr] = list()
        max_id = len(self._messages[addr])
        bus_message = BusMessage(message)
        bus_message.set_message_id(max_id + 1)
        self._messages[addr].append(bus_message)

    def get_message(self, message_id: int, addr: int = 0x00):
        for message in self._messages[addr]:
            if message.message_id == message_id:
                return message


class SPI(Bus):

    CONTROLLER: int = None
    LSB: int = 0
    MSB: int = 1

    def __init__(self, id: int, baudrate: int = 1_000_000, *, polarity: int = 0, phase: int = 0, bits: int = 8,
                 firstbit: int = MSB, sck: Pin = None, mosi: Pin = None, miso: Pin = None):
        super().__init__()
        self._id = id
        self._baudrate = baudrate
        self._polarity = polarity
        self._phase = phase
        self._bits = bits
        self._firstbit = firstbit
        self._sck = sck
        self._mosi = mosi
        self._miso = miso

    def deinit(self) -> None:
        ...

    """Read a number of bytes specified by nbytes while continuously writing the single byte given by write. 
    Returns a bytes object with the data that was read."""
    def read(self, nbytes: int, write: int = 0x00) -> bytes:
        if nbytes is None or nbytes == 0:
            raise ValueError("Nbytes invalid {}").format(nbytes)
        if self._generator.has_next():
            return self._generator.next().payload[0:nbytes]
        else:
            return None

    """    Read into the buffer specified by buf while continuously writing the single byte given by write. Returns None.
    Note: on WiPy this function returns the number of bytes read."""
    def readinto(self, buf, write: int = 0x00):
        if buf is None or len(buf) == 0:
            raise ValueError("Buffer invalid {}").format(buf)
        reading = self.read(nbytes=len(buf))
        for i in range(len(buf)):
            buf[i] = reading[i]

    """    Write the bytes contained in buf. Returns None.
    Note: on WiPy this function returns the number of bytes written."""
    def write(self, buf: bytes):
        if buf is None or len(buf) == 0:
            raise ValueError("Nbytes invalid {}").format(buf)
        if buf.__class__ not in (bytearray, bytes, str):
            raise ValueError("Buf must be bytearray, bytes or string but is {}".format(buf.__class__))
        clone = bytearray(len(buf))
        clone[:] = buf[:]
        self.record_message(message=clone)

    """    Write the bytes from write_buf while reading into read_buf. The buffers can be the same or different, 
    but both buffers must have the same length. Returns None.
    Note: on WiPy this function returns the number of bytes written."""
    def write_readinto(self, write_buf, read_buf):
        ...


class I2C(Bus):

    def __init__(self, id, scl, sda, freq=400000):
        super().__init__()
        self.id = id
        self.scl = scl
        self.sda = sda
        self.freq = freq

    def scan(self):
        return []

    '''Read nbytes from the peripheral specified by addr. If stop is true then a STOP condition is generated at the end of the transfer.
       Returns a bytes object with the data read.'''
    def readfrom(self, addr, nbytes, stop=True) -> bytes:
        if nbytes is None or nbytes < 0:
            raise ValueError("Nbytes invalid {}").format(nbytes)
        if self._generator.has_next(addr=addr):
            return self._generator.next(addr=addr).payload[0:nbytes]
        else:
            return self.get_current_message(addr=addr).payload[0:nbytes]

    """Read into buf from the peripheral specified by addr. The number of bytes read will be the length of buf.
       If stop is true then a STOP condition is generated at the end of the transfer. The method returns None."""
    def readfrom_into(self, addr, buf, stop=True):
        reading = self.readfrom(addr, buf, stop)
        for i in range(len(buf)):
            buf[i] = reading[i]

    """Write the bytes from buf to the peripheral specified by addr. If a NACK is received following the write of a byte 
       from buf then the remaining bytes are not sent. If stop is true then a STOP condition is generated at the end of 
       the transfer, even if a NACK is received. The function returns the number of ACKs that were received."""
    def writeto(self, addr, buf, stop=True) -> int:
        if buf is None or len(buf) == 0:
            raise ValueError("Nbytes invalid {}").format(buf)
        if buf.__class__ not in (bytearray, bytes, str):
            raise ValueError("Buf must be bytearray, bytes or string")
        message = None
        ack_count = 0
        if buf.__class__ in (bytearray, bytes):
            message = bytearray(len(buf))
            for i in range(len(buf)):
                message[i] = buf[i]
                ack_count += 1
        if buf.__class__ is str:
            message = buf
            ack_count = 1
        self.record_message(addr=addr, message=message)
        return ack_count

    """Write the bytes contained in vector to the peripheral specified by addr. vector should be a tuple or list of 
    objects with the buffer protocol. The addr is sent once and then the bytes from each object in vector are written 
    out sequentially. The objects in vector may be zero bytes in length in which case they don’t contribute to the output.
    If a NACK is received following the write of a byte from one of the objects in vector then the remaining bytes, and 
    any remaining objects, are not sent. If stop is true then a STOP condition is generated at the end of the transfer, 
    even if a NACK is received. The function returns the number of ACKs that were received."""
    def writevto(self, addr, vector, stop=True):
        raise NotImplementedError('writevto')

    """Read nbytes from the peripheral specified by addr starting from the memory address specified by memaddr. 
    The argument addrsize specifies the address size in bits. Returns a bytes object with the data read."""
    def readfrom_mem(self, addr, memaddr, nbytes, *, addrsize=8):
        return bytearray(100)
        raise NotImplementedError('readfrom_mem')

    """Read into buf from the peripheral specified by addr starting from the memory address specified by memaddr. 
    The number of bytes read is the length of buf. The argument addrsize specifies the address size in bits 
    (on ESP8266 this argument is not recognised and the address size is always 8 bits).
    The method returns None."""
    def readfrom_mem_into(self, addr, memaddr, buf, *, addrsize=8):
        raise NotImplementedError('readfrom_mem_into')

    """Write buf to the peripheral specified by addr starting from the memory address specified by memaddr. 
    The argument addrsize specifies the address size in bits (on ESP8266 this argument is not recognised and the address size is always 8 bits).
    The method returns None."""
    def writeto_mem(self, addr, memaddr, buf, *, addrsize=8):
        return
        raise NotImplementedError('writeto_mem')


class Signal:

    def __init__(self, pin: Pin, invert: bool = False):
        self.pin = pin
        self.invert = invert

    def value(self, x: int = None):
        if self.invert:
            x = (x - 1) * -1
        self.pin.value(x)

    def on(self):
        self.pin.on()

    def off(self):
        self.pin.off()

    def __str__(self):
        return self.pin.__str__()


class ADC(StateTrackable):
    def __init__(self, pin: Pin):
        super().__init__()
        self.pin = pin
        self.u16_value = 0

    def write_u16(self, u16_value: int):
        event = PinEvent(old_value=self.u16_value, new_value=u16_value)
        self.record_event(event)
        self.u16_value = u16_value

    def read_u16(self) -> int:
        return self.u16_value


class PWM(StateTrackable):
    def __init__(self, pin: Pin):
        super().__init__()
        self.pin = pin
        self.duty_ns_value = None
        self.duty_u16_value = None
        self.freq_value = None

    def duty_ns(self, duty_ns_value=None):
        if duty_ns_value is None:
            return self.duty_ns_value
        else:
            event = PinEvent(old_value=self.duty_ns_value, new_value=duty_ns_value)
            self.record_event(event)
            self.duty_ns_value = duty_ns_value

    def duty_u16(self, duty_u16_value=None):
        if duty_u16_value is None:
            return self.duty_u16_value
        else:
            event = PinEvent(old_value=self.duty_u16_value, new_value=duty_u16_value)
            self.record_event(event)
            self.duty_u16_value = duty_u16_value

    def freq(self, freq_value):
        if freq_value is None:
            return self.freq_value
        else:
            self.freq_value = freq_value

