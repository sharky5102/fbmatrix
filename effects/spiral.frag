// Palette: 2 fixed colors. Black renders as black.
void mainImage(out vec4 fragColor, in vec2 fragCoord)
{
    vec2 p = (fragCoord * 2.0 - iResolution.xy) / min(iResolution.x, iResolution.y);
    float d = length(p);
    float a = atan(p.y, p.x);

    float spiral = sin(a * 6.0 + d * 18.0 - iTime * 4.0);
    float core = smoothstep(1.15, 0.1, d);
    float bands = smoothstep(0.15, 0.85, spiral * 0.5 + 0.5);

    vec3 color = mix(iColor1, iColor2, mod(floor((a * 6.0 + d * 18.0 - iTime * 4.0) / 6.2831853), 2.0));
    fragColor = vec4(color * bands * core, 1.0);
}
