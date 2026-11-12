#!/usr/bin/env python3
"""OME-1894: the "From docs to agent" diagram of the agent skill page.

Usage: python3 agent-skill-diagrams.gen.py
Writes docs/diagrams/agent-skill-docs-to-agent-{light,dark}.svg. PNGs are rendered with render_png.sh.
Labels use the names of the prose and of the install commands.
"""

import html
import pathlib

OUT = pathlib.Path(__file__).parent
FONT = "IBM Plex Mono, Menlo, monospace"
CHAR_W = 0.62  # monospace glyph width as a fraction of the font size

THEMES = {
    "light": dict(bg="#ffffff", box="#f6f6f7", line="#d4d6db", text="#16181d", mid="#585d67",
                  muted="#8b909a", accent="#c9821f", bad="#b4452f", ok="#2f7d4f"),
    "dark": dict(bg="#0a0b0d", box="#131519", line="#2c303a", text="#e8eaed", mid="#9aa0aa",
                 muted="#686e78", accent="#e0a23c", bad="#e07a62", ok="#5fbf86"),
}


def esc(s):
    return html.escape(s, quote=True)


class Svg:
    def __init__(self, name, title, w, h, theme):
        self.name, self.w, self.h, self.t = name, w, h, THEMES[theme]
        t = self.t
        self.parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" '
            f'font-family="{FONT}">\n<title>{esc(title)}</title>\n<defs>'
            + "".join(
                f'<marker id="a-{k}" viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="7" markerHeight="7" '
                f'orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="{t[k]}"/></marker>'
                for k in ("mid", "bad", "ok", "accent")
            )
            + f'</defs>\n<rect width="{w}" height="{h}" fill="{t["bg"]}"/>'
        ]

    def text(self, x, y, s, size=11, color="text", anchor="middle", weight=None, spacing=None):
        extra = f' font-weight="{weight}"' if weight else ""
        extra += f' letter-spacing="{spacing}"' if spacing else ""
        self.parts.append(
            f'<text x="{x}" y="{y}" font-size="{size}" fill="{self.t[color]}" text-anchor="{anchor}"{extra}>{esc(s)}</text>'
        )

    def box(self, x, y, w, h, title, lines=(), accent=False, stroke="line", dashed=False):
        t = self.t
        dash = ' stroke-dasharray="5 4"' if dashed else ""
        self.parts.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{t["box"]}" stroke="{t[stroke]}" stroke-width="1"{dash}/>'
        )
        if accent:
            self.parts.append(f'<rect x="{x}" y="{y}" width="3" height="{h}" fill="{t["accent"]}"/>')
        cx = x + w / 2
        assert len(title) * 12 * (CHAR_W + 0.04) <= w - 12, (self.name, title)
        self.text(cx, y + 24, title, 12, "text", weight=600, spacing="0.04em")
        for i, ln in enumerate(lines):
            assert len(ln) * CHAR_W * 10.5 <= w - 12, (self.name, ln)
            self.text(cx, y + 46 + i * 17, ln, 10.5, "mid")

    def arrow(self, pts, color="mid", dashed=False):
        d = "M" + " L".join(f"{x} {y}" for x, y in pts)
        dash = ' stroke-dasharray="5 4"' if dashed else ""
        self.parts.append(
            f'<path d="{d}" fill="none" stroke="{self.t[color]}" stroke-width="1.3"{dash} marker-end="url(#a-{color})"/>'
        )

    def label(self, x, y, s, color="mid", anchor="middle", size=10.5):
        assert len(s) * CHAR_W * size <= self.w - 60, (self.name, s)
        self.text(x, y, s, size, color, anchor)

    def heading(self, title, sub):
        self.text(40, 42, title, 16, "text", "start", weight=600)
        self.text(40, 64, sub, 11, "muted", "start", spacing="0.04em")

    def write(self, theme):
        self.parts.append("</svg>\n")
        (OUT / f"{self.name}-{theme}.svg").write_text("\n".join(self.parts))




def docs_to_agent(theme):
    s = Svg("agent-skill-docs-to-agent", "From docs to agent", 1240, 400, theme)
    s.heading("From docs to agent", "ONE GENERATOR WRITES THE SKILL AND THE MARKDOWN ENDPOINTS FROM THE SAME PAGES")
    s.box(40, 150, 200, 96, "Docs pages", ["public-docs/src/pages"])
    s.box(290, 150, 230, 96, "Generator", ["npm run build:skill", "npm run build"], accent=True)
    s.box(580, 90, 250, 96, "agent-skill/", ["committed to the repository", "SKILL.md and one reference", "for each page"])
    s.box(580, 230, 250, 96, "dist/", ["served at docs.screamingface.ai", "<route>.md, llms.txt,", "llms-full.txt"])
    s.box(890, 50, 310, 80, "Claude Code", ["claude plugin install", "docs@screamingface"])
    s.box(890, 140, 310, 96, "Other agents", ["npx skills add", "ScreamingFace/screamingface", "--skill screamingface"])
    s.box(890, 243, 310, 70, "Any agent", ["reads <route>.md", "or llms.txt over HTTPS"])
    s.arrow([(240, 198), (290, 198)])
    s.arrow([(520, 180), (550, 180), (550, 138), (580, 138)])
    s.arrow([(520, 216), (550, 216), (550, 278), (580, 278)])
    s.arrow([(830, 120), (860, 120), (860, 90), (890, 90)])
    s.arrow([(830, 150), (860, 150), (860, 188), (890, 188)])
    s.arrow([(830, 278), (890, 278)])
    s.label(40, 372, "CI regenerates the skill on every change and fails when the committed copy differs.", "muted", "start", 10)
    s.write(theme)


for theme in THEMES:
    docs_to_agent(theme)
