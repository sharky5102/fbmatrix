float hash11(float p)
{
    p = fract(p * 0.1031);
    p *= p + 33.33;
    p *= p + p;
    return fract(p);
}

float hash31(vec3 p)
{
    p = fract(p * 0.1031);
    p += dot(p, p.yzx + 33.33);
    return fract((p.x + p.y) * p.z);
}

void mainLed(out vec4 ledColor, in vec3 ledPosition, in float ledIndex, in int sourceMode)
{
    vec4 source = defaultSource(ledPosition, sourceMode);
    float seed = hash11(ledIndex + hash31(ledPosition + 17.0) * 4096.0);

    float rate = mix(0.8, 2.4, hash11(seed + 2.0));
    float phase = floor(iTime * rate + seed * 29.0);
    float selected = step(0.62, hash11(ledIndex * 3.17 + phase * 11.13));

    float age = fract(iTime * rate + seed * 29.0);
    float rise = smoothstep(0.0, 0.18, age);
    float fall = 1.0 - smoothstep(0.28, 1.0, age);
    float sparkle = clamp(rise * fall * 1.35, 0.0, 1.0);

    float gate = selected * sparkle;
    ledColor = vec4(clamp(source.rgb * gate, 0.0, 1.0), source.a);
}
