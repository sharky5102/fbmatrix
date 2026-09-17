void mainLed(out vec4 ledColor, in vec3 ledPosition, in float ledIndex,
             in float stringIndex, in float enabled, in float lineIndex,
             in float linePosition)
{
    float channel = mod(floor(lineIndex + 0.5), 3.0);
    ledColor = vec4(
        channel < 0.5 ? 1.0 : 0.0,
        channel >= 0.5 && channel < 1.5 ? 1.0 : 0.0,
        channel >= 1.5 ? 1.0 : 0.0,
        1.0);
}
