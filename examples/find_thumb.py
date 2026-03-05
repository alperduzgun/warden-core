import sys
from svgpathtools import svg2paths, Path, CubicBezier, Line

paths, attributes = svg2paths("src/warden/assets/warden-logo.svg")
main_path = paths[0]
subpaths = main_path.continuous_subpaths()
sp0 = subpaths[0]

# Generate an HTML file that renders sp0 but highlights the hand segments with IDs!
# x < 200, y > 300

html = ['<html><body><svg viewBox="0 0 648 725" width="1200" height="1343">']

# Draw all segments lightly
html.append('<path d="{}" fill="none" stroke="lightgray" stroke-width="1"/>'.format(sp0.d()))

# Draw highlighted segments
import random

text_labels = []
for i, seg in enumerate(sp0):
    xmin, xmax, ymin, ymax = seg.bbox()
    if xmax < 200 and ymax > 300:
        color = f"hsl({i * 50 % 360}, 100%, 50%)"
        html.append(f'<path d="{Path(seg).d()}" fill="none" stroke="{color}" stroke-width="3"/>')

        # Add a text label at the midpoint
        mid = seg.point(0.5)
        text_labels.append(f'<text x="{mid.real}" y="{mid.imag}" font-size="10" fill="{color}">{i}</text>')

html.extend(text_labels)
html.append("</svg></body></html>")

with open("examples/hand_segments.html", "w") as f:
    f.write("\n".join(html))

print("Saved examples/hand_segments.html")
