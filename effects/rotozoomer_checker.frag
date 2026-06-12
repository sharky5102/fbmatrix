vec3 hueColor(float hue)
{
    vec3 p = abs(fract(hue + vec3(0.0, 2.0 / 3.0, 1.0 / 3.0)) * 6.0 - 3.0);
    return clamp(p - 1.0, 0.0, 1.0);
}

mat2 rotate2d(float angle)
{
    float c = cos(angle);
    float s = sin(angle);
    return mat2(c, -s, s, c);
}

void mainImage(out vec4 fragColor, in vec2 fragCoord)
{
    vec2 p = (fragCoord * 2.0 - iResolution.xy) / min(iResolution.x, iResolution.y);
    float d = length(p);

    float zoom = 6.0 + sin(iTime * 0.7) * 2.0;
    vec2 q = rotate2d(iTime * 0.65) * p * zoom;
    q += vec2(iTime * 1.15, -iTime * 0.82);

    vec2 cell = floor(q);
    float checker = mod(cell.x + cell.y, 2.0);
    float grid = max(abs(fract(q.x) - 0.5), abs(fract(q.y) - 0.5));
    float edge = smoothstep(0.38, 0.48, grid);
    float mask = smoothstep(1.35, 0.05, d);

    vec3 a = hueColor(iHue + 0.02);
    vec3 b = hueColor(iHue + 0.48);
    vec3 color = mix(a, b, checker);
    color *= mix(0.28, 1.0, edge);

    fragColor = vec4(color * mask, 1.0);
}
