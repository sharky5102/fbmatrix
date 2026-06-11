vec3 hueColor(float hue)
{
    vec3 p = abs(fract(hue + vec3(0.0, 2.0 / 3.0, 1.0 / 3.0)) * 6.0 - 3.0);
    return clamp(p - 1.0, 0.0, 1.0);
}

void mainImage(out vec4 fragColor, in vec2 fragCoord)
{
    vec2 uv = fragCoord / iResolution.xy;
    float center = fract(iTime * 0.22);
    float wrapped = abs(fract(uv.x - center + 0.5) - 0.5);
    float wipe = smoothstep(0.22, 0.0, wrapped);
    float edge = smoothstep(0.04, 0.0, abs(wrapped - 0.18));

    vec3 base = hueColor(iHue + uv.x * 0.2);
    vec3 edgeColor = hueColor(iHue + 0.18 + uv.y * 0.12);
    fragColor = vec4(base * wipe + edgeColor * edge, 1.0);
}
