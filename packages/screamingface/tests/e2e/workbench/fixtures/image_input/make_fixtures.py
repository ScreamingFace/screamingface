"""Generate the image input matrix's known-answer fixtures (spec §3.3). Dev-time only.

Run from this directory:

    uv run --with pillow==11.3.0 python make_fixtures.py

It writes ``token.{png,jpg,gif,webp}`` (the 4-digit token on a 320x120 canvas),
``codeword.pdf`` (a one-page text PDF holding the code word) and ``manifest.json``.

WHY the outputs are committed, not generated at test time: the notebook fetches them from a
commit-pinned ``raw.githubusercontent.com`` URL and checks each sha256 against the manifest, so
the bytes behind a pinned commit must never change. Regenerate only on purpose, then re-pin.

WHY Pillow is never a dependency: it is needed once, here, through ``uv run --with``; the tests
only read bytes. WHY the PDF is written by hand: it must carry TEXT (a font and a show-text
operator), not an embedded picture, so a PDF-capable model reads the word rather than OCRing an
image; the stdlib is enough for a one-page file.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Final

from PIL import Image, ImageDraw, ImageFont  # pyright: ignore[reportMissingImports]

HERE: Final = Path(__file__).resolve().parent
# The repo-relative directory: the tail of every fixture's raw.githubusercontent URL.
REPO_DIR: Final = "packages/screamingface/tests/e2e/workbench/fixtures/image_input"
TOKEN: Final = "7392"
CODE_WORD: Final = "HELIOTROPE"
SIZE: Final = (320, 120)

# (file name, media type, Pillow format, save options)
_PICTURES: Final = (
    ("token.png", "image/png", "PNG", {"optimize": True}),
    ("token.jpg", "image/jpeg", "JPEG", {"quality": 90}),
    # WHY a comment: Pillow writes GIF87a unless a GIF89a feature is present.
    ("token.gif", "image/gif", "GIF", {"comment": b"image input matrix fixture"}),
    ("token.webp", "image/webp", "WEBP", {"lossless": True}),
)


def _token_picture() -> Image.Image:
    """The token in large dark type, centred on a light canvas."""
    image = Image.new("RGB", SIZE, (250, 250, 245))
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=88)
    left, top, right, bottom = draw.textbbox((0, 0), TOKEN, font=font)
    x = (SIZE[0] - (right - left)) / 2 - left
    y = (SIZE[1] - (bottom - top)) / 2 - top
    draw.text((x, y), TOKEN, font=font, fill=(20, 20, 30))
    return image


def _text_pdf(word: str) -> bytes:
    """A minimal one-page PDF 1.4 that shows ``word`` in Helvetica, with a correct xref table."""
    content = f"BT /F1 48 Tf 40 70 Td ({word}) Tj ET".encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 420 180] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(content), content),
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    return bytes(out)


def _entry(name: str, media_type: str, expected: str) -> dict[str, object]:
    data = (HERE / name).read_bytes()
    return {
        "path": f"{REPO_DIR}/{name}",
        "media_type": media_type,
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "expected": expected,
    }


def main() -> None:
    picture = _token_picture()
    manifest: list[dict[str, object]] = []
    for name, media_type, fmt, options in _PICTURES:
        picture.save(HERE / name, format=fmt, **options)
        manifest.append(_entry(name, media_type, TOKEN))
    (HERE / "codeword.pdf").write_bytes(_text_pdf(CODE_WORD))
    manifest.append(_entry("codeword.pdf", "application/pdf", CODE_WORD))
    (HERE / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
