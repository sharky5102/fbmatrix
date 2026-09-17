// Palette: 2 fixed colors. Black renders as black.
void mainImage(out vec4 fragColor, in vec2 fragCoord)
{
    vec2 uv = fragCoord / iResolution.xy;
    float phase = (uv.x + uv.y) * 5.0 - iTime * 0.75;
    float stripe = fract(phase);
    float bar = smoothstep(0.0, 0.08, stripe) * smoothstep(0.36, 0.24, stripe);
    float glow = smoothstep(0.65, 0.0, abs(stripe - 0.18));

    vec3 color = mix(iColor1, iColor2, mod(floor(phase), 2.0));
    fragColor = vec4(color * (bar + glow * 0.25), 1.0);
}
