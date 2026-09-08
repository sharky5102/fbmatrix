void mainLed(out vec4 ledColor, in vec3 ledPosition, in float ledIndex,
             in float stringIndex, in float enabled, in float lineIndex,
             in float linePosition)
{
    ledColor = sampleSource(ledPosition);
}
