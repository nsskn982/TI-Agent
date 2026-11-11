"""Formatting filters. Ratios in the data are fractions (0.151 = 15.1%)."""
from django import template

register = template.Library()


@register.filter
def pct(value, digits=1):
    try:
        return f"{float(value) * 100:+.{int(digits)}f}%"
    except (TypeError, ValueError):
        return "–"


@register.filter
def pct_plain(value, digits=1):
    try:
        return f"{float(value) * 100:.{int(digits)}f}%"
    except (TypeError, ValueError):
        return "–"


@register.filter
def money(value):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "–"
    for div, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M")):
        if abs(v) >= div:
            return f"${v / div:.1f}{suffix}"
    return f"${v:,.2f}"


@register.filter
def num(value, digits=2):
    try:
        return f"{float(value):.{int(digits)}f}"
    except (TypeError, ValueError):
        return "–"


@register.filter
def stance_mark(stance):
    return {"bullish": "▲", "bearish": "▼", "neutral": "■"}.get(stance, "")


@register.filter
def get(mapping, key):
    try:
        return mapping.get(key)
    except AttributeError:
        return None
