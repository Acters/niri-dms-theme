# SPDX-License-Identifier: MIT
"""Bootstrap the owned Qt palette before DMS's first Matugen generation."""
import re

_TOKEN = re.compile(r"\{\{colors\.([a-z_]+)\.default\.(red|green|blue)\}\}")
_FIELDS = {
    "background": "background", "surface": "surface", "on_surface": "surfaceText",
    "on_surface_variant": "surfaceVariantText", "outline": "outline",
    "primary": "primary", "primary_container": "primaryContainer", "on_primary": "primaryText",
    "secondary": "secondary", "surface_container": "surfaceContainer",
    "surface_container_low": "surfaceContainerLow",
}

def render_palette(theme: dict, template: str, mode: str = "dark") -> str:
    if mode not in ("light", "dark"):
        raise ValueError("palette mode must be light or dark")
    colors = theme[mode]
    values = {role: colors[field] for role, field in _FIELDS.items()}
    values["tertiary"] = colors.get("tertiary", colors["secondary"])
    values["error"] = colors.get("error", "#F2B8B5" if mode == "dark" else "#B3261E")
    def replace(match):
        role, channel = match.groups()
        if role not in values:
            raise ValueError(f"unsupported bootstrap color role: {role}")
        value = values[role]
        if not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
            raise ValueError(f"invalid RGB color for {role}: {value!r}")
        index = ("red", "green", "blue").index(channel)
        return str(int(value[1 + index * 2:3 + index * 2], 16))
    result = _TOKEN.sub(replace, template)
    if "{{" in result or "}}" in result:
        raise ValueError("unresolved bootstrap palette token")
    return result
