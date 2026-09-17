// Optical ID pattern. Keep these values in sync with calibration_protocol.py.
const int PREAMBLE_LENGTH = 16;
const int PAYLOAD_LENGTH = 25;
const int PACKET_SLOTS = 66;
const float SLOT_SECONDS = 0.1;

int fieldBit(int value, int width, int bitIndex) {
    return (value >> (width - 1 - bitIndex)) & 1;
}

int headerBit(int index, int stringId, int pixelIndex) {
    if (index < 2) return fieldBit(1, 2, index); // protocol version 1
    if (index < 7) return fieldBit(stringId, 5, index - 2);
    return fieldBit(pixelIndex, 10, index - 7);
}

int pixelCrc(int stringId, int pixelIndex) {
    int crc = 0;
    for (int i = 0; i < 17; ++i) {
        int feedback = ((crc >> 7) & 1) ^ headerBit(i, stringId, pixelIndex);
        crc = (crc << 1) & 255;
        if (feedback != 0) crc ^= 7;
    }
    return crc;
}

int payloadBit(int index, int stringId, int pixelIndex) {
    if (index < 17) return headerBit(index, stringId, pixelIndex);
    return fieldBit(pixelCrc(stringId, pixelIndex), 8, index - 17);
}

int opticalBit(int slot, int stringId, int pixelIndex) {
    if (slot < PREAMBLE_LENGTH) {
        return slot < 8 ? 0 : 1;
    }
    int payloadSlot = slot - PREAMBLE_LENGTH;
    int bit = payloadBit(payloadSlot / 2, stringId, pixelIndex);
    return (payloadSlot & 1) == 0 ? bit : 1 - bit;
}

void mainLed(out vec4 ledColor, in vec3 ledPosition, in float ledIndex,
             in float stringIndex, in float enabled, in float lineIndex,
             in float linePosition)
{
    int stringId = int(floor(stringIndex + 0.5));
    int pixelIndex = int(floor(ledIndex + 0.5));
    if (stringId > 31 || pixelIndex > 999) {
        // Magenta marks a layout address outside the current protocol limits.
        ledColor = vec4(1.0, 0.0, 1.0, 1.0);
        return;
    }

    int slot = int(mod(floor(iTime / SLOT_SECONDS), float(PACKET_SLOTS)));
    int bit = opticalBit(slot, stringId, pixelIndex);
    ledColor = vec4(bit == 1 ? 1.0 : 0.0, 1.0,
                    bit == 0 ? 1.0 : 0.0, 1.0);
}
