"""Build the OME-1551 fixtures: a bar chart PNG and a one-page PDF that names the chart.

The chart title carries a code (ZEBRA-7341) and the bar values 17 / 42 / 29; the PDF's
Figure 3 caption names the same code and the same values, so "Does the chart appear in the
report?" has one checkable answer: yes, as Figure 3 on page 1.
"""

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

out = Path(sys.argv[1])
font = ImageFont.load_default(size=22)
img = Image.new("RGB", (480, 320), "white")
d = ImageDraw.Draw(img)
d.text((20, 10), "Chart ZEBRA-7341: widgets per site", fill="black", font=font)
for i, (label, value, color) in enumerate(
    [("North", 17, "red"), ("East", 42, "blue"), ("West", 29, "green")]
):
    x = 60 + i * 130
    d.rectangle([x, 290 - value * 5, x + 80, 290], fill=color)
    d.text((x + 20, 290 - value * 5 - 28), str(value), fill="black", font=font)
    d.text((x + 10, 292), label, fill="black", font=ImageFont.load_default(size=18))
img.save(out / "chart.png", optimize=True)

c = canvas.Canvas(str(out / "report.pdf"), pagesize=A4)
c.setFont("Helvetica", 12)
y = 800
for line in [
    "Quarterly Site Report",
    "",
    "Figure 3 is the chart ZEBRA-7341, widgets per site.",
    "It shows North 17, East 42 and West 29 widgets.",
    "The verification phrase for this report is: amber falcon.",
]:
    c.drawString(72, y, line)
    y -= 20
c.showPage()
c.save()
