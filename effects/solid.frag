// Palette: 1 fixed color. Black renders as black.
void mainImage(out vec4 fragColor, in vec2 fragCoord)
{
    // Keep the coordinate input live: Mesa can swizzle RGB across the quad
    // when this shader reduces to a uniform-only fragment color.
    vec3 color = fragCoord.x < 0.0 ? vec3(0.0) : iColor1;
    fragColor = vec4(color, 1.0);
}
