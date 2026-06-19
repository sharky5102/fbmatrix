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

float boxFrame(vec2 p, float size, float thickness)
{
    vec2 q = abs(p) - vec2(size);
    float outside = length(max(q, vec2(0.0)));
    float inside = min(max(q.x, q.y), 0.0);
    float sdf = outside + inside;
    return smoothstep(thickness, 0.0, abs(sdf));
}

void mainImage(out vec4 fragColor, in vec2 fragCoord)
{
    vec2 p = (fragCoord * 2.0 - iResolution.xy) / min(iResolution.x, iResolution.y);
    float d = length(p);

    vec3 color = vec3(0.0);
    float s0 = boxFrame(rotate2d(iTime * 0.65) * p, 0.86, 0.035);
    float s1 = boxFrame(rotate2d(-iTime * 0.52 + 0.55) * (p - vec2(0.16, -0.08)), 0.66, 0.032);
    float s2 = boxFrame(rotate2d(iTime * 0.88 + 1.05) * (p + vec2(0.12, 0.12)), 0.48, 0.03);
    float s3 = boxFrame(rotate2d(-iTime * 1.1 + 1.65) * p, 0.31, 0.028);

    color += hueColor(iHue + 0.00) * s0;
    color += hueColor(iHue + 0.18) * s1;
    color += hueColor(iHue + 0.36) * s2;
    color += hueColor(iHue + 0.58) * s3;
    color += vec3(1.0) * (s0 * s1 + s1 * s2 + s2 * s3) * 0.38;

    float mask = smoothstep(1.35, 0.05, d);
    fragColor = vec4(min(color * mask, vec3(1.0)), 1.0);
}
