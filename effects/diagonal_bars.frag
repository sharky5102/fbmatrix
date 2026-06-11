vec3 hueColor(float hue)
{
    vec3 p = abs(fract(hue + vec3(0.0, 2.0 / 3.0, 1.0 / 3.0)) * 6.0 - 3.0);
    return clamp(p - 1.0, 0.0, 1.0);
}

void mainImage(out vec4 fragColor, in vec2 fragCoord)
{
    vec2 uv = fragCoord / iResolution.xy;
    float stripe = fract((uv.x + uv.y) * 5.0 - iTime * 0.75);
    float bar = smoothstep(0.0, 0.08, stripe) * smoothstep(0.36, 0.24, stripe);
    float glow = smoothstep(0.65, 0.0, abs(stripe - 0.18));

    vec3 color = hueColor(iHue + uv.x * 0.12 + uv.y * 0.12);
    fragColor = vec4(color * (bar + glow * 0.25), 1.0);
}
