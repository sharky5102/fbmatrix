float hash11(float p)
{
    p = fract(p * 0.1031);
    p *= p + 33.33;
    p *= p + p;
    return fract(p);
}

void mainLed(out vec4 ledColor, in vec3 ledPosition, in float ledIndex, in int sourceMode)
{
    vec4 source = defaultSource(ledPosition, sourceMode);

    float tick = floor(iTime * 18.0);
    float seed = hash11(ledIndex * 17.17);
    float lit = step(0.91, hash11(ledIndex * 41.41 + tick * 7.13));
    float shimmer = mix(0.85, 1.6, hash11(seed + tick));
    float lift = lit * shimmer;

    ledColor = vec4(clamp(source.rgb * (1.0 + lift), 0.0, 1.0), source.a);
}
