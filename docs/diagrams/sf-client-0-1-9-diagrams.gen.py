#!/usr/bin/env python3
"""OME-426: SF Client 0.1.9 docs diagrams. Text source for five SVG diagrams, each in a light and a dark theme.

Usage: python3 sf-client-0-1-9-diagrams.gen.py
Writes docs/diagrams/sf-client-0-1-9-<name>-{light,dark}.svg. PNGs are rendered from the SVGs with a headless
browser (render_png.sh next to this file). Labels use the names and casing of the prose and the API.
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
        (OUT / f"sf-client-0-1-9-{self.name}-{theme}.svg").write_text("\n".join(self.parts))


def reducers_selection(theme):
    s = Svg("reducers-selection", "The input of the stage after Rank or Filter", 1060, 360, theme)
    s.heading("What the stage after Rank or Filter receives",
              "SELECTION IN A PIPELINE · THE NEXT STAGE IS A STAGE OF THE SAME PIPELINE")
    s.box(40, 100, 220, 96, "Case input", ["the question of one case,", "given to every member"])
    s.box(340, 100, 260, 96, "Members", ["each member answers", "the Case input"], accent=True)
    s.box(680, 100, 340, 96, "Rank(k) or Filter", ["Rank keeps the best k, best first", "Filter keeps by a test, author order"])
    s.arrow([(260, 148), (340, 148)])
    s.arrow([(600, 148), (680, 148)])
    s.label(640, 138, "answers", "muted")
    s.box(340, 250, 680, 82, "The next stage", ["receives one JSON object:",
          '{"input": <Case input>, "selected": [{"id": ..., "text": ...}]}'], accent=True)
    s.arrow([(850, 196), (850, 250)])
    s.label(860, 228, "kept members", "muted", "start")
    s.arrow([(150, 196), (150, 291), (340, 291)])
    s.label(160, 240, "input", "muted", "start")
    s.label(40, 352, "When nothing is kept, selected is []. A selection that ends a candidate, is a Fusion member or feeds a corrective loop raises ValueError.", "muted", "start", 10)
    s.write(theme)


def fusion_quorum(theme):
    s = Svg("fusion-quorum", "Fusion with quorum and optional members", 1060, 430, theme)
    s.heading("Which members reach the synthesizer",
              "FUSION(MEMBERS, SYNTHESIZER, QUORUM=...) · THE QUORUM IS CHECKED AFTER THE MEMBERS FINISH")
    s.box(40, 100, 230, 66, "Member A", ["required, succeeds"], stroke="ok")
    s.box(40, 190, 230, 66, "Member B", ["required, succeeds"], stroke="ok")
    s.box(40, 280, 230, 66, "Member C", ["optional=True, fails"], stroke="bad", dashed=True)
    s.box(400, 170, 270, 106, "Quorum check", ["succeeded members >= quorum", '"all": every member (default)', "an integer: that many members"], accent=True)
    s.arrow([(270, 133), (335, 133), (335, 200), (400, 200)], "ok")
    s.arrow([(270, 223), (400, 223)], "ok")
    s.arrow([(270, 313), (335, 313), (335, 250), (400, 250)], "bad", dashed=True)
    s.label(40, 372, "A failed optional member is a failed answer with reason missing,", "bad", "start")
    s.label(40, 389, "never a vote.", "bad", "start")
    s.box(780, 100, 240, 90, "Synthesizer", ["combines the answers", "that reached it"], stroke="ok")
    s.box(780, 250, 240, 90, "Candidate fails", ["quorum not met, or a", "required member failed"], stroke="bad")
    s.arrow([(670, 200), (725, 200), (725, 145), (780, 145)], "ok")
    s.arrow([(670, 250), (725, 250), (725, 295), (780, 295)], "bad")
    s.label(676, 192, "met", "ok", "start")
    s.label(676, 268, "not met", "bad", "start")
    s.label(40, 418, "A required member that fails fails the candidate, whatever the quorum. quorum=0 lets the synthesizer run with no successful member.", "muted", "start", 10)
    s.write(theme)


def media_fetch(theme):
    s = Svg("media-fetch", "Opening and fetching a Case's media", 1060, 520, theme)
    s.heading("Fetching a Case's media",
              "SEQUENCE · THE REPORT HOLDS A PLACEHOLDER, THE ENGINE HOLDS THE BYTES")
    xs = {"you": 150, "client": 530, "engine": 910}
    names = {"you": "Your code", "client": "ScreamingFace Client", "engine": "ScreamingFace Engine"}
    for k, x in xs.items():
        s.box(x - 120, 84, 240, 44, names[k], [])
        s.parts.append(f'<path d="M{x} 128 L{x} 504" stroke="{s.t["line"]}" stroke-width="1" stroke-dasharray="3 5"/>')
    s.arrow([(xs["you"], 170), (xs["client"], 170)])
    s.label(340, 162, "case.media[0]", "text")
    s.arrow([(xs["client"], 198), (xs["you"], 198)], "ok")
    s.label(340, 216, "CaseMedia: media_type, size, sha256", "ok")
    s.label(340, 232, "no network call", "muted")
    s.arrow([(xs["you"], 272), (xs["client"], 272)])
    s.label(340, 264, "sf.fetch_media(item)", "text")
    s.arrow([(xs["client"], 304), (xs["engine"], 304)])
    s.label(720, 296, "fetch the item's bytes", "text")
    s.parts.append(f'<rect x="40" y="326" width="980" height="1" fill="{s.t["line"]}"/>')
    s.label(40, 346, "The engine holds the item", "ok", "start")
    s.arrow([(xs["engine"], 372), (xs["client"], 372)], "ok")
    s.label(720, 364, "bytes", "ok")
    s.arrow([(xs["client"], 402), (xs["you"], 402)], "ok")
    s.label(340, 394, "FetchedMedia, only when size and sha256 match", "ok")
    s.parts.append(f'<rect x="40" y="420" width="980" height="1" fill="{s.t["line"]}"/>')
    s.label(40, 440, "The engine no longer holds the item, or never held it", "bad", "start")
    s.arrow([(xs["engine"], 466), (xs["client"], 466)], "bad")
    s.label(720, 458, "not held", "bad")
    s.arrow([(xs["client"], 494), (xs["you"], 494)], "bad")
    s.label(340, 486, "MediaUnavailableError, code media_not_kept", "bad")
    s.write(theme)


def pinned_cache(theme):
    s = Svg("pinned-cache-states", "Pinned cache states", 1060, 470, theme)
    s.heading("States of a pinned cache",
              "CAPTURE=TRUE · THE ENGINE OPENS THE COPY AT THE START OF THE RUN AND SEALS IT AT THE END")
    s.box(40, 100, 180, 70, "Opening", ["the run starts"], accent=True)
    s.box(280, 100, 180, 70, "Open", ["stores each answer", "and web-tool result"], accent=True)
    s.box(520, 100, 180, 70, "Sealing", ["the run ends"], accent=True)
    s.box(760, 100, 260, 70, "Sealed", ["the gateway confirmed it"], stroke="ok")
    s.arrow([(220, 135), (280, 135)])
    s.arrow([(460, 135), (520, 135)])
    s.arrow([(700, 135), (760, 135)], "ok")
    s.box(40, 270, 200, 70, "capture_status", ["'partial'"], stroke="bad")
    s.box(760, 270, 260, 70, "capture_status", ["'complete'"], stroke="ok")
    s.arrow([(890, 170), (890, 270)], "ok")
    s.label(880, 230, "every call and web-tool result", "ok", "end")
    s.label(880, 246, "stored, and the run did not", "ok", "end")
    s.label(880, 262, "use the local runtime", "ok", "end")
    s.arrow([(110, 170), (110, 270)], "bad")
    s.label(118, 196, "Open: the copy", "bad", "start")
    s.label(118, 212, "did not open", "bad", "start")
    s.arrow([(370, 170), (370, 220), (170, 220), (170, 270)], "bad")
    s.label(380, 196, "Failed, Refused, Missing,", "bad", "start")
    s.label(380, 212, "Error, Ambiguous", "bad", "start")
    s.arrow([(610, 170), (610, 250), (210, 250), (210, 270)], "bad")
    s.label(620, 196, "Seal: the seal was not confirmed.", "bad", "start")
    s.label(620, 212, "A cancelled run is never sealed.", "muted", "start")
    s.box(280, 380, 740, 66, "Local runtime", ["Local: a capture on the local runtime is always partial,", "capture_partial_reasons == ('local',)"], stroke="bad", dashed=True)
    s.arrow([(280, 413), (140, 413), (140, 340)], "bad")
    s.label(40, 366, "Capture is off by default.", "muted", "start")
    s.write(theme)


def classify_flow(theme):
    s = Svg("classify-flow", "The sf.classify call path", 1060, 300, theme)
    s.heading("The path of sf.classify",
              "ONE TEXT IN, ONE LIST OF LABEL SCORES OUT · THE MODEL ID NAMES YOUR ENDPOINT")
    s.box(40, 100, 230, 96, "ScreamingFace Client", ["sf.classify(model, input)", "byom_<id>/classifier_v1"])
    s.box(320, 100, 210, 96, "ScreamingFace Engine", ["POST /classify", "waits at most 30 s"], accent=True)
    s.box(580, 100, 210, 96, "AI Gateway", ["holds the key stored", "with sf.connect"], accent=True)
    s.box(840, 100, 180, 96, "Your endpoint", ["the byom_<id>", "origin"])
    s.arrow([(270, 148), (320, 148)])
    s.arrow([(530, 148), (580, 148)])
    s.arrow([(790, 148), (840, 148)])
    s.label(40, 232, 'The endpoint receives {"inputs": <input>} with the bearer key.', "mid", "start")
    s.label(40, 252, "It returns [{label, score}, ...] with scores from 0 to 1. The Client returns Classification(model, contract, scores).", "mid", "start", 10)
    s.label(40, 280, "The Client refuses before any call when the encoded request is over 8,192 bytes (uri_too_long).", "muted", "start")
    s.write(theme)


for theme in THEMES:
    for fn in (reducers_selection, fusion_quorum, media_fetch, pinned_cache, classify_flow):
        fn(theme)
