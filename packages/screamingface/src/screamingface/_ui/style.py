"""Shared visual foundation for ScreamingFace notebook surfaces."""

from __future__ import annotations

import re

_LIGHT = (
    "--sf-bg:#fcfdff;--sf-surface:#f4f6f9;--sf-surface-2:#eceef0;"
    "--sf-ink:#3b3c3e;--sf-ink-2:#616265;--sf-ink-3:#b4b6b8;"
    "--sf-line:#cdcfd2;--sf-line-2:#b4b6b8;--sf-gain:#ec9f3f;--sf-gain-bg:#faf5f0;"
    "--sf-blind:#6c1c17;--sf-blind-bg:#fff3f2;--sf-danger-solid:#ff0325;"
    "--sf-accent:#4b91f0;--sf-accent-hover:#4185de;--sf-accent-contrast:#ffffff;"
    "--sf-success:#004611;--sf-success-solid:#17aa46;--sf-success-bg:#f0f9f2;"
    "--sf-warning:#66270c;--sf-warning-solid:#f1622d;--sf-warning-bg:#fdf4f1"
)
_DARK = (
    "--sf-bg:#05070b;--sf-surface:#0c0f13;--sf-surface-2:#15181c;"
    "--sf-ink:#e0e5eb;--sf-ink-2:#c7ccd2;--sf-ink-3:#585c61;"
    "--sf-line:#35383d;--sf-line-2:#585c61;--sf-gain:#e2a35b;--sf-gain-bg:#110e0c;"
    "--sf-blind:#ffdcd7;--sf-blind-bg:#130d0d;--sf-danger-solid:#ed413f;"
    "--sf-accent:#6099e7;--sf-accent-hover:#6fa6f0;--sf-accent-contrast:#ffffff;"
    "--sf-success:#baf2bd;--sf-success-solid:#4aae5e;--sf-success-bg:#0c100d;"
    "--sf-warning:#ffddd0;--sf-warning-solid:#e36f48;--sf-warning-bg:#130e0c"
)

# The one sanctioned SFDS gradient (fusion-grad), as the brand repo renders it on a
# progress/score fill (product-demos/widgets-view/widgets.css .w-progfill). Held as a
# plain constant, NOT a custom property on .sf-ui: it stays opt-in per surface so it can
# only appear where the story earns it — a run in flight, or the leading candidate.
FUSION_GRADIENT = (
    "linear-gradient(100deg,#d8860e 0%,#d98b27 3%,#da9037 6%,#dc9544 10%,#dd9a50 13%,"
    "#de9f5b 16%,#dfa465 19%,#e0a970 23%,#e2b280 26%,#e5bb90 29%,#e7c3a0 32%,"
    "#e9ccaf 35%,#ebd4be 39%,#edddcd 42%,#f2e3df 45%,#eeebf3 48%,#e7edf5 52%,"
    "#dde6f4 55%,#d2dff2 58%,#c8d9f2 61%,#bfd4f2 65%,#b5cef2 68%,#abc8f2 71%,"
    "#a2c2f2 74%,#97bcf3 77%,#8db6f3 81%,#83b0f3 84%,#79aaf3 87%,#6fa4f3 90%,"
    "#649ef3 94%,#5a98f3 97%,#4f91f2 100%)"
)


def _flow(gradient: str) -> str:
    """Mirror a ramp into a seamless palindrome (gold→blue→gold).

    Tiled at 200% and scrolled by background-position it loops without a visible seam,
    which is how SFDS renders `--fusion-grad-flow`. Built from the base stops rather than
    pasted as a second literal so the two can never drift apart.
    """

    stops = re.findall(r"(#[0-9a-f]{6}) ([0-9.]+)%", gradient)
    forward = [(color, float(pct) / 2) for color, pct in stops]
    mirrored = [(color, 100 - float(pct) / 2) for color, pct in stops]
    combined = forward + list(reversed(mirrored))
    body = ",".join(f"{color} {pct:.4g}%" for color, pct in combined)
    return f"linear-gradient(90deg,{body})"


FUSION_GRADIENT_FLOW = _flow(FUSION_GRADIENT)

# The vertical run of the same ramp, for the score cell's left edge band
# (product-demos/widgets-view/widgets.css .w-rescell-score::before).
FUSION_GRADIENT_Y = FUSION_GRADIENT.replace("linear-gradient(100deg", "linear-gradient(180deg")

# INVARIANT: shared surfaces use solid gold; the Fusion gradient is card-scoped.
STYLE = f"""<style>
.sf-ui{{
  {_LIGHT};
  max-width:920px;color:var(--sf-ink);background:var(--sf-bg);
  font-family:"IBM Plex Sans",system-ui,-apple-system,"Segoe UI",sans-serif;
  font-size:13px;line-height:1.45;
}}
@media (prefers-color-scheme:dark){{.sf-ui{{{_DARK}}}}}
:where(html[theme="light"]) .sf-ui{{{_LIGHT}}}
:where(html[theme="dark"]) .sf-ui{{{_DARK}}}
.jp-mod-theme-dark .sf-ui,[data-jp-theme-light="false"] .sf-ui,
.vscode-dark .sf-ui,.vscode-high-contrast .sf-ui{{{_DARK}}}
.jp-mod-theme-light .sf-ui,[data-jp-theme-light="true"] .sf-ui,
.vscode-light .sf-ui{{{_LIGHT}}}
.sf-ui,.sf-ui *{{box-sizing:border-box}}
</style>"""

__all__: list[str] = []
