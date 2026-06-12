vec3 hueColor(float hue)
{
    vec3 p = abs(fract(hue + vec3(0.0, 2.0 / 3.0, 1.0 / 3.0)) * 6.0 - 3.0);
    return clamp(p - 1.0, 0.0, 1.0);
}

void mainImage(out vec4 fragColor, in vec2 fragCoord)
{
    vec2 p = (fragCoord * 2.0 - iResolution.xy) / min(iResolution.x, iResolution.y);
    float d = max(length(p), 0.025);
    float a = atan(p.y, p.x);

    float tunnel = 1.0 / d;
    float spin = a / 6.2831853 + iTime * 0.12;
    float bands = sin(tunnel * 5.0 + iTime * 5.0);
    float checks = sin((spin + tunnel * 0.08) * 75.398224);
    float level = step(0.0, bands * checks);
    float glow = smoothstep(0.45, 1.0, bands * 0.5 + 0.5);
    float vignette = smoothstep(1.35, 0.05, d);

    vec3 color = hueColor(iHue + tunnel * 0.045 + spin * 0.18);
    color *= mix(0.12, 1.0, level) + glow * 0.25;

    fragColor = vec4(color * vignette, 1.0);
}
