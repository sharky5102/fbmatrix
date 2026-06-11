vec3 hueColor(float hue)
{
    vec3 p = abs(fract(hue + vec3(0.0, 2.0 / 3.0, 1.0 / 3.0)) * 6.0 - 3.0);
    return clamp(p - 1.0, 0.0, 1.0);
}

void mainImage(out vec4 fragColor, in vec2 fragCoord)
{
    vec2 uv = fragCoord / iResolution.xy;
    float stripe = fract(uv.y * 8.0 - iTime * 1.2);
    float leading = smoothstep(0.0, 0.06, stripe) * smoothstep(0.22, 0.12, stripe);
    float tail = smoothstep(0.72, 0.0, stripe) * 0.35;

    vec3 color = hueColor(iHue + uv.y * 0.25 + iTime * 0.025);
    fragColor = vec4(color * (leading + tail), 1.0);
}
