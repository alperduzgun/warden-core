import sys
from svgpathtools import svg2paths, wsvg, Path, CubicBezier, Line

paths, attributes = svg2paths("src/warden/assets/warden-logo.svg")
main_path = paths[0]
subpaths = main_path.continuous_subpaths()

# Find segments in subpath 0 where x is small (left side, i.e., the hand)
sp0 = subpaths[0]

hand_segments = []
for i, seg in enumerate(sp0):
    # get bounding box of segment
    xmin, xmax, ymin, ymax = seg.bbox()
    if xmax < 200 and ymax > 300:  # Hand area roughly
        hand_segments.append(seg)

print(f"Found {len(hand_segments)} segments in the hand area.")
wsvg(hand_segments, filename="examples/hand_segments.svg")
