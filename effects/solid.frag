vec3 hueColor(float hue)
{
    vec3 p = abs(fract(hue + vec3(0.0, 2.0 / 3.0, 1.0 / 3.0)) * 6.0 - 3.0);
    return clamp(p - 1.0, 0.0, 1.0);
}

void mainImage(out vec4 fragColor, in vec2 fragCoord)
{
    vec2 uv = fragCoord / iResolution.xy;
    vec3 color = hueColor(iHue + uv.x * 0.08);
    fragColor = vec4(color, 1.0);
}
