// Palette: 2 fixed colors. Black renders as black.
void mainImage(out vec4 fragColor, in vec2 fragCoord)
{
    vec2 p = (fragCoord * 2.0 - iResolution.xy) / min(iResolution.x, iResolution.y);
    float d = length(p);
    float angle = fract(atan(p.y, p.x) / 6.2831853 + 0.5 + iTime * 0.035);

    float segment = floor(angle * 24.0);
    float alternating = mod(segment, 2.0);
    float radialGate = step(0.5, fract(d * 7.0 - iTime * 0.55));
    float level = mix(0.08, 1.0, alternating) * mix(0.45, 1.0, radialGate);
    float mask = smoothstep(1.32, 0.02, d);

    vec3 color = mix(iColor1, iColor2, alternating) * level;

    fragColor = vec4(color * mask, 1.0);
}
