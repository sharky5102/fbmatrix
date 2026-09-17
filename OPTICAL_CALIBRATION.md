# Optical LED Calibration Pattern

Select **Calibration** from the **Emitter shader** controls in `fbmserve.py`
while running a WS2811 layout. The effect identifies each active LED using its
zero-based output string index and zero-based position in that string's wire
order. Keep master brightness at 100% while testing.

Green stays on continuously. Blue plus green represents 0; red plus green
represents 1. The app can classify the red/blue difference while using green
to find and track each LED.

## Packet version 1

The controller repeats the packet continuously with a 100 ms slot period. No
phone/controller clock synchronization is needed: the phone observes the
repeating preamble and recovers packet timing from the camera stream.

| Field | Width | Range |
| --- | ---: | ---: |
| Preamble | 16 slots | `0000000011111111` |
| Protocol version | 2 bits | Version 1 (`01`) |
| Output string ID | 5 bits | 0-31 |
| Pixel index | 10 bits | 0-999 in the current installation |
| CRC | 8 bits | CRC-8/ATM |

The 25 payload bits after the preamble are Manchester encoded, with `0` mapped
to `01` and `1` mapped to `10`. CRC-8/ATM uses polynomial `0x07`, initial value
`0x00`, no reflection and final XOR `0x00`. It is calculated MSB-first over the
17 version/string/pixel bits. A packet is 66 slots, or 6.6 seconds, long.

Five string-ID bits provide capacity for 32 outputs, covering the current plan
of up to 24. The current fbmatrix WS2811 renderer itself still limits layouts
to 14 strings. Ten pixel-ID bits encode 0-1023; this implementation emits
indices 0-999 to match the stated maximum of 1,000 LEDs per string. Pixels
outside that range appear magenta as an unsupported-layout marker.

## Implementation and checks

`calibration_protocol.py` is the deterministic Python reference encoder.
`led_effects/calibration.frag` applies the same packet to each active emitter
using the shared fbmatrix clock and the real string/pixel indices. Offline
tests cover CRC, field bounds, packet length, Manchester encoding and packet
repetition. A shader render test compares the GLSL output against the Python
encoder. Neither test requires a physical LED installation.
