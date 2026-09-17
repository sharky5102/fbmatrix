// Palette: 2 fixed colors. Black renders as black.
void mainImage(out vec4 fragColor, in vec2 fragCoord)
{
    vec2 p = (fragCoord * 2.0 - iResolution.xy) / min(iResolution.x, iResolution.y);
    float d = length(p);
    float angle = fract(atan(p.y, p.x) / 6.2831853 + 0.5);

    float sweep = fract(angle * 8.0 - iTime * 0.7);
    float head = smoothstep(0.12, 0.0, sweep);
    float tail = smoothstep(0.62, 0.0, sweep) * 0.55;
    float rings = smoothstep(0.15, 0.95, sin(d * 26.0 - iTime * 4.0) * 0.5 + 0.5);
    float mask = smoothstep(1.28, 0.02, d);

    vec3 color = mix(iColor1, iColor2, mod(floor(angle * 8.0 - iTime * 0.7), 2.0));
    float level = (0.12 + max(head, tail)) * mix(0.72, 1.15, rings);

    fragColor = vec4(min(color * level * mask, vec3(1.0)), 1.0);
}
