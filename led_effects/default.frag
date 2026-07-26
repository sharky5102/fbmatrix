void mainLed(out vec4 ledColor, in vec3 ledPosition, in float ledIndex, in int sourceMode)
{
    ledColor = defaultSource(ledPosition, sourceMode);
}
