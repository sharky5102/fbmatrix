void mainLed(out vec4 ledColor, in vec3 ledPosition, in float ledIndex,
             in int stringIndex, in int sourceMode)
{
    ledColor = defaultSource(ledPosition, sourceMode);
}
