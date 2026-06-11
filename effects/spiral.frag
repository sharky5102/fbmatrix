vec3 hueColor(float hue)
{
    vec3 p = abs(fract(hue + vec3(0.0, 2.0 / 3.0, 1.0 / 3.0)) * 6.0 - 3.0);
    return clamp(p - 1.0, 0.0, 1.0);
}

void mainImage(out vec4 fragColor, in vec2 fragCoord)
{
    vec2 p = (fragCoord * 2.0 - iResolution.xy) / min(iResolution.x, iResolution.y);
    float d = length(p);
    float a = atan(p.y, p.x);

    float spiral = sin(a * 5.0 + d * 18.0 - iTime * 4.0);
    float core = smoothstep(1.15, 0.1, d);
    float bands = smoothstep(0.15, 0.85, spiral * 0.5 + 0.5);

    vec3 color = hueColor(iHue + a / 6.2831853 + d * 0.25 + iTime * 0.03);
    fragColor = vec4(color * bands * core, 1.0);
}
