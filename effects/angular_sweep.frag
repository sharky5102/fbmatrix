// Palette: 2 fixed colors. Black renders as black.
void mainImage(out vec4 fragColor, in vec2 fragCoord)
{
    vec2 p = (fragCoord * 2.0 - iResolution.xy) / min(iResolution.x, iResolution.y);
    float d = length(p);
    float a = atan(p.y, p.x);

    float arm = abs(sin(a * 2.0 - iTime * 2.4));
    float narrow = smoothstep(0.075, 0.0, arm);
    float wide = smoothstep(0.28, 0.0, arm) * 0.22;
    float ripple = smoothstep(0.2, 1.0, sin(d * 32.0 - iTime * 7.0) * 0.5 + 0.5);
    float center = smoothstep(0.24, 0.0, d);
    float mask = smoothstep(1.35, 0.0, d);

    vec3 beam = mix(iColor1, iColor2, mod(floor((a - iTime * 1.2) / 1.5707963 + 0.5), 2.0));
    vec3 core = (iColor1 + iColor2) * 0.5;
    float level = max(narrow, wide) * mix(0.6, 1.15, ripple) + center * 0.35;

    fragColor = vec4(mix(beam, core, center) * level * mask, 1.0);
}
