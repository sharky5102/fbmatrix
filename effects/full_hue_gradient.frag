vec3 hueColor(float hue)
{
    vec3 p = abs(fract(hue + vec3(0.0, 2.0 / 3.0, 1.0 / 3.0)) * 6.0 - 3.0);
    return clamp(p - 1.0, 0.0, 1.0);
}

mat2 rotate2d(float angle)
{
    float c = cos(angle);
    float s = sin(angle);
    return mat2(c, -s, s, c);
}

void mainImage(out vec4 fragColor, in vec2 fragCoord)
{
    vec2 p = (fragCoord * 2.0 - iResolution.xy) / min(iResolution.x, iResolution.y);
    vec2 rotated = rotate2d(iTime * 0.22) * p;
    float hue = fract(
        iHue
        + iTime * 0.055
        + atan(rotated.y, rotated.x) / 6.2831853
        + length(rotated) * 0.5
    );

    fragColor = vec4(hueColor(hue), 1.0);
}
