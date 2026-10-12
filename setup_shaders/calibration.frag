// Each pixel displays one MSB-first symbol from its globally assigned
// 21-bit codebook word. The codebook is uploaded once as an R32UI texture.
const int CODEWORD_BITS = 21;
const int CODEBOOK_TEXTURE_WIDTH = 256;
const float SLOT_SECONDS = 0.1;

void mainLed(out vec4 ledColor, in vec3 ledPosition, in float ledIndex,
             in float stringIndex, in float enabled, in float lineIndex,
             in float linePosition, in float globalLedIndex)
{
    int ledId = int(floor(globalLedIndex + 0.5));
    ivec2 codebookPosition = ivec2(ledId % CODEBOOK_TEXTURE_WIDTH,
                                   ledId / CODEBOOK_TEXTURE_WIDTH);
    uint word = texelFetch(codebooktex, codebookPosition, 0).r;
    int slot = int(mod(floor(iTime / SLOT_SECONDS), float(CODEWORD_BITS)));
    int bit = int((word >> uint(CODEWORD_BITS - 1 - slot)) & 1u);
    ledColor = vec4(bit == 1 ? 1.0 : 0.0, 0.0,
                    bit == 0 ? 1.0 : 0.0, 1.0);
}
