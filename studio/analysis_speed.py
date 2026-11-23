"""User-selectable engine budgets, always bounded by server administrator caps.

Seconds are per *board position* (half-move plus starting position), not per game.
Existing saved scans remain intact when changing a preset.
"""
PRESETS = {
    'turbo': (1, 1),       # fastest bulk review
    'fast': (3, 2),        # preferred starting point on a small VPS
    'balanced': (10, 2),
    'detailed': (30, 3),
    'deep': (120, 3),
}
DEFAULT_PRESET = 'fast'


def effective_budget(preset, cap_seconds, cap_multipv):
    if preset not in PRESETS:
        preset = DEFAULT_PRESET
    requested_seconds, requested_lines = PRESETS[preset]
    cap_seconds = max(1, min(120, int(cap_seconds)))
    cap_multipv = max(1, min(5, int(cap_multipv)))
    return {
        'preset': preset,
        'requested_seconds': requested_seconds,
        'requested_multipv': requested_lines,
        'seconds': min(requested_seconds, cap_seconds),
        'multipv': min(requested_lines, cap_multipv),
        'server_seconds_cap': cap_seconds,
        'server_multipv_cap': cap_multipv,
        'limited_by_admin': requested_seconds > cap_seconds or requested_lines > cap_multipv,
    }
