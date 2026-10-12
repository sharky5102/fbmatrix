"""Shaders reserved for physical emitter setup and diagnostics."""

import os

SETUP_EFFECTS = (
    {'id': 'calibration', 'name': 'Capture'},
    {'id': 'layout_colors', 'name': 'Layout Colors'},
)


def discover_effects(effects_dir):
    """Return the fixed setup choices; source files are loaded on selection."""
    return [dict(effect) for effect in SETUP_EFFECTS]


def load_effect_source(effects_dir, effect_id):
    if effect_id not in {item['id'] for item in SETUP_EFFECTS}:
        raise ValueError('Unknown setup shader')
    with open(os.path.join(effects_dir, effect_id + '.frag'), 'rt',
              encoding='utf-8') as source_file:
        return source_file.read()
