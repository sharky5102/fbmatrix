import os
import re


DEFAULT_LED_EFFECT = """
void mainLed(out vec4 ledColor, in vec3 ledPosition, in float ledIndex, in int sourceMode)
{
    ledColor = defaultSource(ledPosition, sourceMode);
}
"""


def strip_version(source):
    return re.sub(r'^\s*#version\s+.+$', '', source, count=1, flags=re.MULTILINE)


def effect_name(effect_id):
    return effect_id.replace('_', ' ').replace('-', ' ').title()


def discover_effects(effects_dir):
    if not os.path.isdir(effects_dir):
        return [{
            'id': 'default',
            'name': 'Framebuffer',
        }]

    effects = []

    for filename in sorted(os.listdir(effects_dir)):
        if filename.endswith('.frag'):
            effect_id = os.path.splitext(filename)[0]
            effects.append({
                'id': effect_id,
                'name': 'Framebuffer' if effect_id == 'default' else effect_name(effect_id),
            })

    if not any(effect['id'] == 'default' for effect in effects):
        effects.insert(0, {
            'id': 'default',
            'name': 'Framebuffer',
        })

    return effects


def load_effect_source(effects_dir, effect_id):
    if not re.match(r'^[A-Za-z0-9_-]+$', effect_id):
        raise ValueError('Invalid LED effect id')

    filename = os.path.join(effects_dir, effect_id + '.frag')
    if effect_id == 'default' and not os.path.isfile(filename):
        return DEFAULT_LED_EFFECT

    with open(filename, 'rt', encoding='utf-8') as f:
        return f.read()
