// Palette: 2 fixed colors. Black renders as black.
float burst(vec2 p, vec2 center, float phase, float scale)
{
    float age = fract(iTime * 0.32 + phase);
    float d = length(p - center);
    float radius = age * scale;
    float ring = smoothstep(0.045, 0.0, abs(d - radius));
    float glow = smoothstep(0.18, 0.0, abs(d - radius)) * 0.16;
    float fade = pow(1.0 - age, 1.65);
    return (ring + glow) * fade;
}

void mainImage(out vec4 fragColor, in vec2 fragCoord)
{
    vec2 p = (fragCoord * 2.0 - iResolution.xy) / min(iResolution.x, iResolution.y);

    float b0 = burst(p, vec2(-0.42, 0.24), 0.00, 1.15);
    float b1 = burst(p, vec2(0.42, -0.12), 0.31, 0.95);
    float b2 = burst(p, vec2(0.05, 0.42), 0.62, 0.82);
    float b3 = burst(p, vec2(-0.12, -0.46), 0.83, 1.05);

    vec3 color = vec3(0.0);
    color += iColor1 * b0;
    color += iColor2 * b1;
    color += iColor1 * b2;
    color += iColor2 * b3;

    float sparkle = smoothstep(0.96, 1.0, sin((p.x + p.y) * 40.0 + iTime * 9.0));
    color *= 1.0 + sparkle * 0.16;

    fragColor = vec4(min(color, vec3(1.0)), 1.0);
}
