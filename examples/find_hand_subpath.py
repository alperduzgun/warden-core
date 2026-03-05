import sys
from svgpathtools import svg2paths

paths, attributes = svg2paths("src/warden/assets/warden-logo.svg")
main_path = paths[0]
subpaths = main_path.continuous_subpaths()

for i, sp in enumerate(subpaths):
    xmin, xmax, ymin, ymax = sp.bbox()
    # Left hand should be on the far left, so low xmin
    print(f"Subpath {i}: x=({xmin:.2f}, {xmax:.2f}), y=({ymin:.2f}, {ymax:.2f})")
