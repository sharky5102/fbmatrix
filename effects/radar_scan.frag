// Palette: 2 fixed colors. Black renders as black.
void mainImage(out vec4 fragColor, in vec2 fragCoord)
{
    vec2 p = (fragCoord * 2.0 - iResolution.xy) / min(iResolution.x, iResolution.y);
    float d = length(p);
    float a = atan(p.y, p.x);

    float sweep = iTime * 1.85;
    float diff = atan(sin(a - sweep), cos(a - sweep));
    float beam = smoothstep(0.14, 0.0, abs(diff));
    float tail = smoothstep(1.2, 0.0, mod(sweep - a, 6.2831853));

    float ringA = smoothstep(0.018, 0.0, abs(d - 0.35));
    float ringB = smoothstep(0.018, 0.0, abs(d - 0.68));
    float ringC = smoothstep(0.018, 0.0, abs(d - 1.02));
    float cross = smoothstep(0.012, 0.0, min(abs(p.x), abs(p.y))) * smoothstep(1.08, 0.0, d);
    float blip = smoothstep(0.05, 0.0, length(p - vec2(sin(iTime * 0.7) * 0.45, cos(iTime * 0.43) * 0.35)));

    vec3 radar = iColor1 * (beam * 0.95 + tail * 0.24 + blip * beam * 1.5);
    radar += iColor2 * ((ringA + ringB + ringC) * 0.24 + cross * 0.13);
    float mask = smoothstep(1.14, 0.98, d);

    fragColor = vec4(radar * mask, 1.0);
}
