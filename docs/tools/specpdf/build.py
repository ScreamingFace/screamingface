#!/usr/bin/env python3
"""Render the OME-1110 url4 topology document to its SFDS dark-register PDFs.

One markdown source, two PDFs. `split.toml` says which top-level sections land in which part
and what each part's title page says; `sfds-print.css` carries the print register.

    uv run build.py --part all

The 2026-09-08 build lived in a session scratchpad and was lost to the tmp reaper before this
document could be revised (ledger deviation 2). This is its replacement, in the repo.
"""

from __future__ import annotations

import argparse
import html
import os
import re
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent


def ensure_native_libs() -> None:
    """Put Homebrew's glib/pango on the loader path, once, by re-executing ourselves.

    WeasyPrint dlopens libgobject/libpango by bare name. On macOS those live under the Homebrew
    prefix, which the dynamic loader does not search, so the import dies with
    `cannot load library 'libgobject-2.0-0'`. DYLD_LIBRARY_PATH is only read at process start,
    hence the re-exec rather than an os.environ poke. The 2026-09-08 build worked around this by
    hand on every invocation (ledger deviation 2); it should not be something to remember.
    """
    if sys.platform != "darwin" or os.environ.get("_SPECPDF_BOOTSTRAPPED"):
        return
    prefix = Path(os.environ.get("HOMEBREW_PREFIX", "/opt/homebrew")) / "lib"
    if not (prefix / "libgobject-2.0.dylib").exists():
        return  # a system that resolves them already, or one where we cannot help
    env = dict(os.environ, _SPECPDF_BOOTSTRAPPED="1")
    existing = env.get("DYLD_LIBRARY_PATH", "")
    env["DYLD_LIBRARY_PATH"] = f"{prefix}:{existing}" if existing else str(prefix)
    os.execve(sys.executable, [sys.executable, *sys.argv], env)


def repo_root() -> Path:
    out = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=HERE,
        capture_output=True,
        text=True,
        check=True,
    )
    return Path(out.stdout.strip())


@dataclass
class Section:
    """One top-level (`# `) section of the source document."""

    heading: str
    body: str
    anchor: str

    @property
    def number(self) -> str:
        """`"7"` for `# 7. Telemetry`, `"A"` for `# Appendix A — …`, else `""`."""
        if m := re.match(r"(\d+)\.", self.heading):
            return m.group(1)
        if m := re.match(r"Appendix ([A-Z])", self.heading):
            return m.group(1)
        return ""


def parse_source(text: str) -> tuple[dict[str, str], list[Section]]:
    """Split the source into its YAML front matter and its top-level sections."""
    meta: dict[str, str] = {}
    if text.startswith("---\n"):
        raw, _, text = text[4:].partition("\n---\n")
        for line in raw.splitlines():
            key, sep, value = line.partition(":")
            if sep and not line.startswith(" "):
                meta[key.strip()] = value.strip().strip('"')

    sections: list[Section] = []
    for chunk in re.split(r"^# ", text, flags=re.M)[1:]:
        heading, _, body = chunk.partition("\n")
        heading = heading.strip()
        sections.append(Section(heading, body.strip(), anchor=slug(heading)))
    return meta, sections


def slug(heading: str) -> str:
    """A stable anchor id: `sec-7`, `app-a`, else a kebab fallback."""
    if m := re.match(r"(\d+)\.", heading):
        return f"sec-{m.group(1)}"
    if m := re.match(r"Appendix ([A-Z])", heading):
        return f"app-{m.group(1).lower()}"
    return "h-" + re.sub(r"[^a-z0-9]+", "-", heading.lower()).strip("-")


def unescaped_pipe_in_code(line: str) -> bool:
    """True if a `|` falls inside a code span, where GFM still reads it as a cell separator."""
    in_code = False
    i = 0
    while i < len(line):
        ch = line[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "`":
            in_code = not in_code
        elif ch == "|" and in_code:
            return True
        i += 1
    return False


def check_table_pipes(source: str) -> None:
    """Refuse a table row with an unescaped pipe inside a code span.

    GFM splits a row on `|` even inside backticks, so `` `a | b` `` silently becomes two cells and
    every column after it shifts — the row still renders, just wrong, which is how the "Non-HTTP
    credentials" row of §12 lost its resolution cell. Escaping it as `\\|` is the fix; this makes
    the mistake loud rather than invisible.
    """
    bad = [
        (n, line)
        for n, line in enumerate(source.splitlines(), 1)
        if line.lstrip().startswith("|") and unescaped_pipe_in_code(line)
    ]
    if bad:
        raise SystemExit(
            "\n".join(
                ["unescaped `|` inside a code span splits the table row — escape it as `\\|`:"]
                + [f"  line {n}: {line.strip()[:110]}" for n, line in bad]
            )
        )


def claim(sections: list[Section], parts: list[dict]) -> dict[str, list[Section]]:
    """Assign each section to exactly one part, or fail loudly.

    A heading that no part matches would silently vanish from both PDFs, and one that two parts
    match would silently duplicate. Both are the kind of error a reader finds before we do.
    """
    claimed: dict[str, list[Section]] = {p["id"]: [] for p in parts}
    owners: dict[str, list[str]] = {}
    for section in sections:
        hits = [p["id"] for p in parts if any(section.heading.startswith(m) for m in p["match"])]
        owners[section.heading] = hits
        for part_id in hits:
            claimed[part_id].append(section)

    orphans = [h for h, hits in owners.items() if not hits]
    dupes = {h: hits for h, hits in owners.items() if len(hits) > 1}
    if orphans or dupes:
        lines = ["split.toml does not partition the document:"]
        lines += [f"  claimed by no part: {h!r}" for h in orphans]
        lines += [f"  claimed by {hits}: {h!r}" for h, hits in dupes.items()]
        raise SystemExit("\n".join(lines))
    return claimed


def pandoc(markdown: str) -> str:
    if not shutil.which("pandoc"):
        raise SystemExit("pandoc not found on PATH — `brew install pandoc`")
    out = subprocess.run(
        ["pandoc", "--from=gfm", "--to=html5", "--no-highlight", "--wrap=none"],
        input=markdown,
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout


CODE_RE = re.compile(r"<(code|pre)\b.*?</\1>", re.S)
EMPTY_LEAD_TH = re.compile(r"<table>\s*<thead>\s*<tr>\s*<th[^>]*>\s*</th>")


def tag_matrix_tables(body: str) -> str:
    """Mark tables whose first header cell is empty.

    Such a table uses column 1 for row labels, and auto layout starves it — long labels then
    overlap the next column, which is how "Three candidate mechanisms" rendered as
    "Whereredentialslive". The stylesheet fixes the column once the table is tagged.
    """
    return EMPTY_LEAD_TH.sub(
        lambda m: m.group(0).replace("<table>", '<table class="matrix">', 1), body
    )


def linkify_sections(body: str, present: set[str]) -> str:
    """Turn in-part `§7` references into internal links.

    Only sections rendered in *this* PDF become links — a `§11` reference from the core document
    points into the companion, and a dead internal link is worse than plain text. Code spans are
    masked first so `§` inside a literal is left alone.
    """
    masked: list[str] = []

    def mask(m: re.Match[str]) -> str:
        masked.append(m.group(0))
        return f"\x00{len(masked) - 1}\x00"

    body = CODE_RE.sub(mask, body)

    def link(m: re.Match[str]) -> str:
        number = m.group(1)
        if number not in present:
            return m.group(0)
        return f'<a class="xref" href="#sec-{number}">§{number}</a>'

    body = re.sub(r"§(\d+)(?![\d.])", link, body)
    body = re.sub(r"\x00(\d+)\x00", lambda m: masked[int(m.group(1))], body)
    return body


def title_page(part: dict, meta: dict[str, str]) -> str:
    rows = [
        ("Status", meta.get("status", "")),
        ("Work item", meta.get("ticket", "")),
        ("Date", meta.get("created", "")),
        ("Owner", meta.get("owner", "")),
        ("Grammar owner", meta.get("grammar-owner", "")),
        ("Spec pointers", meta.get("spec-pointers", "")),
    ]
    cells = "\n".join(
        f"<tr><th>{html.escape(k)}</th><td>{html.escape(v)}</td></tr>" for k, v in rows if v
    )
    return f"""<section class="title-page">
  <p class="kicker">{html.escape(part["kicker"])}</p>
  <h1 class="doc-title">{html.escape(part["title"])}</h1>
  <p class="doc-subtitle">{html.escape(part["subtitle"])}</p>
  <table class="meta">{cells}</table>
  <p class="strapline">{html.escape(part["strapline"].strip())}</p>
</section>"""


def render_part(
    part: dict, doc: dict, meta: dict[str, str], sections: list[Section], root: Path
) -> str:
    present = {s.number for s in sections if s.number.isdigit()}
    pieces: list[str] = [title_page(part, meta)]

    if intro := part.get("intro"):
        heading = part.get("intro_heading", "About this part")
        pieces.append(
            f'<section class="intro"><h1 id="about">{html.escape(heading)}</h1>'
            f"{pandoc(intro.strip())}</section>"
        )

    diagrams = root / doc["diagram_dir"]
    for section in sections:
        body = section.body

        # The markdown embeds light diagrams so it reads on GitHub; the dark register swaps in
        # the -dark twin and absolutises the path so WeasyPrint can find it from any cwd.
        def swap(m: re.Match[str]) -> str:
            name = Path(m.group(2)).stem + doc["diagram_suffix"] + ".svg"
            target = diagrams / name
            if not target.exists():
                raise SystemExit(f"{section.heading}: missing dark diagram {target}")
            return f"![{m.group(1)}]({target.as_uri()})"

        body = re.sub(r"!\[([^\]]*)\]\(([^)]+\.svg)\)", swap, body)
        rendered = tag_matrix_tables(linkify_sections(pandoc(body), present))
        pieces.append(
            f'<section class="doc-section">'
            f'<h1 id="{section.anchor}">{html.escape(section.heading)}</h1>\n{rendered}</section>'
        )

    css = (HERE / doc["css"]).read_text()
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>{html.escape(part["title"])}</title>
<style>
@page {{
  @top-left {{ content: "{part["running_header_left"].upper()}"; }}
  @top-right {{ content: "{doc["running_header_right"]}"; }}
  @bottom-left {{ content: "{doc["footer_left"]}"; }}
}}
{css}
</style></head><body>{"".join(pieces)}</body></html>"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--part", default="all", help="core | open-work | all")
    ap.add_argument("--html", action="store_true", help="also write the intermediate HTML")
    args = ap.parse_args()

    root = repo_root()
    config = tomllib.loads((HERE / "split.toml").read_text())
    doc, parts = config["doc"], config["part"]

    source = (root / doc["source"]).read_text()
    check_table_pipes(source)
    meta, sections = parse_source(source)
    claimed = claim(sections, parts)

    wanted = [p for p in parts if args.part in ("all", p["id"])]
    if not wanted:
        raise SystemExit(
            f"--part {args.part!r}: expected one of {', '.join(p['id'] for p in parts)}, or 'all'"
        )

    ensure_native_libs()
    from weasyprint import HTML  # imported late: the errors above should not need WeasyPrint

    for part in wanted:
        page = render_part(part, doc, meta, claimed[part["id"]], root)
        out = root / doc["out_dir"] / part["out"]
        if args.html:
            out.with_suffix(".html").write_text(page)
        HTML(string=page, base_url=str(HERE)).write_pdf(out)
        print(
            f"{part['id']:>10} → {out.relative_to(root)} "
            f"({len(claimed[part['id']])} sections, {out.stat().st_size // 1024} KB)"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
