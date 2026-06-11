vec3 hueColor(float hue)
{
    vec3 p = abs(fract(hue + vec3(0.0, 2.0 / 3.0, 1.0 / 3.0)) * 6.0 - 3.0);
    return clamp(p - 1.0, 0.0, 1.0);
}

void mainImage(out vec4 fragColor, in vec2 fragCoord)
{
    vec2 p = (fragCoord * 2.0 - iResolution.xy) / min(iResolution.x, iResolution.y);
    float a = atan(p.y, p.x);
    float d = length(p);

    float wave = sin(d * 24.0 - iTime * 5.0);
    float spokes = sin(a * 8.0 + iTime * 1.7);
    float mask = smoothstep(0.15, 0.95, 1.0 - d);
    float level = smoothstep(0.1, 0.9, wave * 0.5 + spokes * 0.18 + 0.5) * mask;

    vec3 color = hueColor(iHue + d * 0.28 + iTime * 0.03);
    fragColor = vec4(color * level, 1.0);
}
