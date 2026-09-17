// Palette: 1 fixed color. Black renders as black.
void mainImage(out vec4 fragColor, in vec2 fragCoord)
{
    vec3 color = iColor1;
    fragColor = vec4(color, 1.0);
}
