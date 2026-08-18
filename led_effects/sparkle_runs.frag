float hash11(float p)
{
    p = fract(p * 0.1031);
    p *= p + 33.33;
    p *= p + p;
    return fract(p);
}

void mainLed(out vec4 ledColor, in vec3 ledPosition, in float ledIndex,
             in int stringIndex, in int sourceMode)
{
    vec4 source = defaultSource(ledPosition, sourceMode);
    float stringSeed = float(stringIndex) * 4099.0;
    float group = floor(ledIndex / 3.0) + stringSeed;
    float lane = mod(ledIndex, 3.0);
    float tick = floor(iTime * 14.0 + hash11(group * 23.23) * 3.0);
    float selected = step(0.965,
        hash11(group * 19.19 + floor(tick / 3.0) * 5.37));
    float slot = mod(tick, 3.0);
    float head = selected * (1.0 - step(0.5, abs(lane - slot)));
    float trail = selected * max(0.0, 1.0 - abs(lane - slot) * 0.55);
    float lift = head * 2.2 + trail * 0.55;
    ledColor = vec4(clamp(source.rgb * (1.0 + lift), 0.0, 1.0), source.a);
}
