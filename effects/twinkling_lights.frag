vec3 hueColor(float hue)
{
    vec3 p = abs(fract(hue + vec3(0.0, 2.0 / 3.0, 1.0 / 3.0)) * 6.0 - 3.0);
    return clamp(p - 1.0, 0.0, 1.0);
}

float hash12(vec2 p)
{
    vec3 q = fract(vec3(p.xyx) * 0.1031);
    q += dot(q, q.yzx + 33.33);
    return fract((q.x + q.y) * q.z);
}

vec2 hash22(vec2 p)
{
    float a = hash12(p);
    float b = hash12(p + 19.19);
    return vec2(a, b);
}

void mainImage(out vec4 fragColor, in vec2 fragCoord)
{
    vec2 uv = fragCoord / iResolution.xy;
    vec2 p = (fragCoord * 2.0 - iResolution.xy) / min(iResolution.x, iResolution.y);
    vec2 grid = uv * 17.0;
    vec2 cell = floor(grid);
    vec2 local = fract(grid);

    vec3 color = vec3(0.0);

    for (int y = -1; y <= 1; y++) {
        for (int x = -1; x <= 1; x++) {
            vec2 offset = vec2(float(x), float(y));
            vec2 id = cell + offset;
            vec2 star = hash22(id);
            vec2 delta = local - offset - star;

            float seed = hash12(id + 7.7);
            float twinkle = sin(iTime * mix(2.5, 7.5, seed) + seed * 39.0) * 0.5 + 0.5;
            twinkle = pow(twinkle, mix(5.0, 18.0, seed));

            float core = smoothstep(0.15, 0.0, length(delta));
            float rays = smoothstep(0.04, 0.0, min(abs(delta.x), abs(delta.y))) * smoothstep(0.20, 0.0, length(delta));
            vec3 starColor = mix(vec3(1.0), hueColor(iHue + seed * 0.22), 0.35);
            color += starColor * (core + rays * 0.42) * twinkle;
        }
    }

    float vignette = smoothstep(1.35, 0.2, length(p));
    fragColor = vec4(min(color * vignette, vec3(1.0)), 1.0);
}
