# Altmode Friend

Find example code and 3D STEP in this repo.

Code examples:

- `simplest_sink_example.py`: A sink example code, that just picks 5V by default. Currently not tested after refactoring. It also might summon DisplayPort out of a DP source, but that's just an accident.
- `sink_example.py`: A sink example code, with two different strategies for picking a PD profile. Currently not tested after refactoring. It also can summon DisplayPort out of a DP source - but the PoC is not fully tested yet.
- `source_example`: Firmware for a bespoke board that uses the stack to create a PD PSU. Currently not tested after refactoring.
- `sniffer.py`: PD sniffer code. Change `replay` to False to run it and adjust the CC pin. Live capture not currently tested after refactoring.

Required libraries:

- `fusb302.py`: FUSB302 low-level code
- `pdstacc.py`: PD stack code

[Find PCB sources here.](https://github.com/CRImier/MyKiCad/tree/master/Peripherals/altmode_friend)

`machine.py` file is a mock you can use to run and test parts of this code on your compooter - in particular, the replay mode of `sniffer.py`.
It is distributed under some other license, because it's been taken [from here](https://github.com/djantzen/pico_book/blob/master/machine.py)
