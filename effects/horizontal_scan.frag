// Palette: 2 fixed colors. Black renders as black.
void mainImage(out vec4 fragColor, in vec2 fragCoord)
{
    vec2 uv = fragCoord / iResolution.xy;
    float phase = uv.y * 8.0 - iTime * 1.2;
    float stripe = fract(phase);
    float leading = smoothstep(0.0, 0.06, stripe) * smoothstep(0.22, 0.12, stripe);
    float tail = smoothstep(0.72, 0.0, stripe) * 0.35;

    vec3 color = mix(iColor1, iColor2, mod(floor(phase), 2.0));
    fragColor = vec4(color * (leading + tail), 1.0);
}
