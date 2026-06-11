vec3 hueColor(float hue)
{
    vec3 p = abs(fract(hue + vec3(0.0, 2.0 / 3.0, 1.0 / 3.0)) * 6.0 - 3.0);
    return clamp(p - 1.0, 0.0, 1.0);
}

void mainImage(out vec4 fragColor, in vec2 fragCoord)
{
    vec2 p = (fragCoord * 2.0 - iResolution.xy) / min(iResolution.x, iResolution.y);
    float d = length(p);

    float rings = sin(d * 34.0 - iTime * 7.0);
    float pulse = smoothstep(0.55, 1.0, rings * 0.5 + 0.5);
    float falloff = smoothstep(1.25, 0.0, d);

    vec3 color = hueColor(iHue + d * 0.45 - iTime * 0.04);
    fragColor = vec4(color * pulse * falloff, 1.0);
}
