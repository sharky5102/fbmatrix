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

    float blades = sin(a * 6.0 + iTime * 3.0);
    float shimmer = sin(d * 16.0 - iTime * 5.0) * 0.18;
    float level = smoothstep(0.02, 0.82, blades * 0.5 + 0.5 + shimmer);
    float mask = smoothstep(1.2, 0.1, d);

    vec3 color = hueColor(iHue + a / 6.2831853 + 0.1);
    fragColor = vec4(color * level * mask, 1.0);
}
