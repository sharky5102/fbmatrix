vec3 hueColor(float hue)
{
    vec3 p = abs(fract(hue + vec3(0.0, 2.0 / 3.0, 1.0 / 3.0)) * 6.0 - 3.0);
    return clamp(p - 1.0, 0.0, 1.0);
}

float softBars(vec2 p, float angle, float spacing, float speed)
{
    vec2 dir = vec2(cos(angle), sin(angle));
    float wave = sin(dot(p, dir) * spacing - iTime * speed);
    float bright = smoothstep(0.62, 1.0, wave);
    float halo = smoothstep(0.05, 1.0, wave) * 0.22;
    return bright + halo;
}

void mainImage(out vec4 fragColor, in vec2 fragCoord)
{
    vec2 p = (fragCoord * 2.0 - iResolution.xy) / min(iResolution.x, iResolution.y);
    float d = length(p);

    float a = softBars(p, 0.0, 18.0, 2.2);
    float b = softBars(p, 0.78, 16.0, -1.7);
    float c = softBars(p, 1.57, 20.0, 1.35);
    float e = softBars(p, 2.36, 14.0, -2.0);

    vec3 color = vec3(0.0);
    color += hueColor(iHue + 0.00) * a;
    color += hueColor(iHue + 0.17) * b;
    color += hueColor(iHue + 0.34) * c;
    color += hueColor(iHue + 0.52) * e;

    float hotspot = a * b + b * c + c * e + e * a;
    color += vec3(1.0) * hotspot * 0.5;
    color *= smoothstep(1.35, 0.0, d);

    fragColor = vec4(min(color, vec3(1.0)), 1.0);
}
