// Palette: 2 fixed colors. Black renders as black.
void mainImage(out vec4 fragColor, in vec2 fragCoord)
{
    vec2 uv = fragCoord / iResolution.xy;
    float center = fract(iTime * 0.22);
    float wrapped = abs(fract(uv.x - center + 0.5) - 0.5);
    float wipe = smoothstep(0.22, 0.0, wrapped);
    float edge = smoothstep(0.04, 0.0, abs(wrapped - 0.18));

    vec3 base = iColor1;
    vec3 edgeColor = iColor2;
    fragColor = vec4(base * wipe + edgeColor * edge, 1.0);
}
