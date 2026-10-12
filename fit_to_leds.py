"""Shared shader mapping from an input aspect ratio to the LED canvas."""

GLSL = """
    uniform highp float fitSourceAspect;
    uniform highp float fitTargetAspect;
    uniform highp int fitMode;

    highp vec2 fitSourceUV(highp vec2 outputUV, out highp float insideSource) {
        highp vec2 sourceUV = outputUV;
        insideSource = 1.0;
        if (fitMode == 0) {
            // Fill: preserve aspect and crop the source to use every LED.
            if (fitSourceAspect > fitTargetAspect)
                sourceUV.x = 0.5 + (outputUV.x - 0.5) * fitTargetAspect / fitSourceAspect;
            else
                sourceUV.y = 0.5 + (outputUV.y - 0.5) * fitSourceAspect / fitTargetAspect;
        } else if (fitMode == 1) {
            // Fit: preserve the full source and leave bars black.
            if (fitSourceAspect > fitTargetAspect) {
                highp float occupied = fitTargetAspect / fitSourceAspect;
                highp float bottom = (1.0 - occupied) * 0.5;
                if (outputUV.y < bottom || outputUV.y > 1.0 - bottom)
                    insideSource = 0.0;
                sourceUV.y = (outputUV.y - bottom) / occupied;
            } else {
                highp float occupied = fitSourceAspect / fitTargetAspect;
                highp float left = (1.0 - occupied) * 0.5;
                if (outputUV.x < left || outputUV.x > 1.0 - left)
                    insideSource = 0.0;
                sourceUV.x = (outputUV.x - left) / occupied;
            }
        }
        // Stretch (mode 2) keeps outputUV unchanged.
        return sourceUV;
    }
"""


def mode_code(mode):
    return {'fill': 0, 'fit': 1, 'stretch': 2}[mode]
