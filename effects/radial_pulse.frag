// Palette: 2 fixed colors. Black renders as black.
void mainImage(out vec4 fragColor, in vec2 fragCoord)
{
    vec2 p = (fragCoord * 2.0 - iResolution.xy) / min(iResolution.x, iResolution.y);
    float d = length(p);

    float rings = sin(d * 34.0 - iTime * 7.0);
    float pulse = smoothstep(0.55, 1.0, rings * 0.5 + 0.5);
    float falloff = smoothstep(1.25, 0.0, d);

    vec3 color = mix(iColor1, iColor2, mod(floor((d * 34.0 - iTime * 7.0) / 6.2831853), 2.0));
    fragColor = vec4(color * pulse * falloff, 1.0);
}
