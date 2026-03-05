import sys
from svgpathtools import svg2paths, Path, CubicBezier, Line, wsvg

paths, attributes = svg2paths("src/warden/assets/warden-logo.svg")
main_path = paths[0]
subpaths = main_path.continuous_subpaths()
sp0 = subpaths[0]

# Find indices where the arm sticks out (x < 140)
out_indices = []
for i, seg in enumerate(sp0):
    xmin, xmax, ymin, ymax = seg.bbox()
    if xmin < 140:
        out_indices.append(i)

if not out_indices:
    print("No arm found?")
    sys.exit(1)

start_idx = out_indices[0]
end_idx = out_indices[-1]

print(f"Arm starts at segment {start_idx} and ends at {end_idx}")

# The arm starts at sp0[start_idx].start and ends at sp0[end_idx].end
# Let's replace all segments from start_idx to end_idx with a single line!
start_point = sp0[start_idx - 1].end if start_idx > 0 else sp0[0].start
end_point = sp0[end_idx + 1].start if end_idx < len(sp0) - 1 else sp0[-1].end

print(f"Start point: {start_point}")
print(f"End point: {end_point}")

new_sp0 = Path(*sp0[:start_idx], Line(start_point, end_point), *sp0[end_idx + 1 :])

# There are also interior hand details (subpaths 9, 12, 14 from our previous output)
# We should filter out any subpath that is entirely in the hand area (xmax < 285)
# Wait, some inner parts of the hand are x=(21, 284), y=(320, 612).
# Let's see:
new_subpaths = [new_sp0]
for sp in subpaths[1:]:
    xmin, xmax, ymin, ymax = sp.bbox()
    if xmax < 285 and ymax > 300 and ymin > 300:
        print(f"Ignoring subpath bounding box {sp.bbox()} as it looks like hand interior.")
        continue
    new_subpaths.append(sp)

# Save to test
wsvg(new_subpaths, filename="examples/no_hand_test.svg")
print("Saved examples/no_hand_test.svg")
