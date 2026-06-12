vec3 hueColor(float hue)
{
    vec3 p = abs(fract(hue + vec3(0.0, 2.0 / 3.0, 1.0 / 3.0)) * 6.0 - 3.0);
    return clamp(p - 1.0, 0.0, 1.0);
}

float barField(vec2 p, float angle, float spacing, float speed, float phase)
{
    vec2 dir = vec2(cos(angle), sin(angle));
    float stripe = fract(dot(p, dir) * spacing + iTime * speed + phase);
    float core = smoothstep(0.11, 0.0, abs(stripe - 0.5));
    float glow = smoothstep(0.34, 0.0, abs(stripe - 0.5)) * 0.42;
    return core * 0.9 + glow + 0.045;
}

void mainImage(out vec4 fragColor, in vec2 fragCoord)
{
    vec2 p = (fragCoord * 2.0 - iResolution.xy) / min(iResolution.x, iResolution.y);
    float d = length(p);

    float a = barField(p, 0.18, 5.0, -0.42, 0.00);
    float b = barField(p, 1.31, 6.0, 0.36, 0.17);
    float c = barField(p, 2.42, 4.5, -0.28, 0.41);

    vec3 color = vec3(0.0);
    color += hueColor(iHue + 0.02) * a;
    color += hueColor(iHue + 0.27) * b;
    color += hueColor(iHue + 0.56) * c;

    float crossing = a * b + b * c + c * a;
    color += hueColor(iHue + 0.12) * crossing * 0.65;
    color *= smoothstep(1.42, 0.05, d);

    fragColor = vec4(min(color * 1.18, vec3(1.0)), 1.0);
}
