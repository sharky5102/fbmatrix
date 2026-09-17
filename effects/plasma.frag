// Palette: 2 fixed colors. Black renders as black.
void mainImage(out vec4 fragColor, in vec2 fragCoord)
{
    vec2 uv = fragCoord / iResolution.xy;
    vec2 p = (fragCoord * 2.0 - iResolution.xy) / min(iResolution.x, iResolution.y);

    float v = 0.0;
    v += sin((p.x + iTime * 0.55) * 4.0);
    v += sin((p.y + iTime * 0.37) * 5.0);
    v += sin((p.x + p.y + iTime * 0.21) * 4.5);
    v += sin(length(p + vec2(sin(iTime * 0.31), cos(iTime * 0.27))) * 8.0);
    v = v * 0.125 + 0.5;

    vec3 color = mix(iColor1, iColor2, clamp(v, 0.0, 1.0));
    fragColor = vec4(color * smoothstep(0.05, 1.0, v), 1.0);
}
