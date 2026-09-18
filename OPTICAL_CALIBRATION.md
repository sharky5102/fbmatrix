# Optical LED Calibration Signal

Select **Calibration** from the **Emitter shader** controls in `fbmserve.py`.
The effect reads the generated `codebook.csv` from the repository root and
assigns its rows to physical LEDs in wire order. IDs continue across output
strings, including disabled LEDs, so the layout is one continuous sequence.

Each active LED repeatedly emits its assigned 21-bit word, most-significant
bit first, at a 100 ms symbol period. Red represents `1` and blue represents
`0`; the complete word repeats every 2.1 seconds. All emitters use fbmatrix's
shared clock. The phone does not need a synchronized start time: its detector
recovers clock phase from the aggregate LED signal and matches observed
symbols against the codebook.

`codebook.csv` must contain the columns `led_id,hex,bits`, with sequential IDs
starting at zero and 21-bit words whose hexadecimal and binary forms agree.
The current generated file has 8,192 entries, so this calibration effect
supports layouts of up to 8,192 physical LEDs. Larger layouts are rejected
rather than silently reusing IDs. The renderer currently accepts at most 14
strings; that existing renderer limit is independent of the codebook format.

The Python reference in `calibration_protocol.py` validates the CSV and
provides deterministic symbol selection. The renderer uploads the 21-bit
words once as an `R32UI` texture. The shader reads each as an exact unsigned
integer, selects one bit by elapsed symbol time, and emits the
corresponding red or blue state.

Offline tests validate the codebook, symbol order and repetition, exact
32-bit integer representation, and agreement between the Python reference and GLSL
rendering. They do not require a physical LED installation.
