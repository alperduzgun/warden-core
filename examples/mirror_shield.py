import sys
from svgpathtools import svg2paths, Path, CubicBezier, Line, wsvg, Arc
import numpy as np

paths, attributes = svg2paths("src/warden/assets/warden-logo.svg")
main_path = paths[0]
subpaths = main_path.continuous_subpaths()
sp0 = subpaths[0]

# we need to find the shield center. The top point of the shield is roughly the midpoint.
# Let's find the max X and min X of the shield.
sp0_xmin, sp0_xmax, sp0_ymin, sp0_ymax = sp0.bbox()
center_x = (sp0_xmin + sp0_xmax) / 2
print(f"Center X is approx: {center_x}")

# Find indices where the arm sticks out (x < 140)
out_indices = []
for i, seg in enumerate(sp0):
    xmin, xmax, ymin, ymax = seg.bbox()
    if xmin < 140:
        out_indices.append(i)

start_idx = out_indices[0]
end_idx = out_indices[-1]

print(f"Arm is from segment {start_idx} to {end_idx}")

# The right side of the shield that corresponds to this Y range
start_y = sp0[start_idx - 1].end.imag
end_y = sp0[end_idx + 1].start.imag

print(f"Arm Y range is roughly {start_y} to {end_y}")

# Now we find segments on the right side (x > center_x) in this Y range.
# Note: The SVG path is drawn in a certain direction, so we need to collect them in the right order.
# Actually, the right boundary is a continuous set of segments.
right_segments = []
for i, seg in enumerate(sp0):
    xmin, xmax, ymin, ymax = seg.bbox()
    if xmin > center_x and (ymin > 63 or ymax < 665):
        # let's just collect all right side segments, then filter by Y later
        right_segments.append(seg)

# Just to make this easier: let's sample the right side of the shield at various Ys,
# mirror the X coordinate (x_left = center_x - (x_right - center_x)),
# and create a path for the left side.


# Sample the right side boundary Y -> X
def get_right_x(y):
    # Find segment that intersects this Y
    # And has X > center_x
    for seg in sp0:
        xmin, xmax, ymin, ymax = seg.bbox()
        if xmin < center_x:
            continue
        if ymin <= y <= ymax or ymax <= y <= ymin:
            # find intersection
            try:
                ts = seg.ilength(1)  # something like this is hard with Beziers
            except:
                pass
    return None


# Alternatively, instead of mathematical perfect reflection which is hard with Beziers,
# we can use the actual Bezier segments from the right, reverse them, and reflect them!
# Find the exact segment that corresponds to `start_y` and `end_y` on the right side.

y_min, y_max = min(start_y, end_y), max(start_y, end_y)
right_side_subpath = []
for seg in sp0:
    xmin, xmax, ymin, ymax = seg.bbox()
    if xmin < center_x:
        continue
    if ymax < y_min - 10 or ymin > y_max + 10:
        continue
    right_side_subpath.append(seg)

print(f"Found {len(right_side_subpath)} segments for the right side mirror.")


# We need to mirror these segments.
# Given a point P = x + y*j, the mirrored point is:
# new_x = center_x - (x - center_x) = 2*center_x - x
# P_mirror = (2*center_x - P.real) + P.imag * j
def mirror_point(p, cx):
    return (2 * cx - p.real) + p.imag * 1j


def mirror_segment(seg, cx):
    if isinstance(seg, Line):
        return Line(mirror_point(seg.start, cx), mirror_point(seg.end, cx))
    elif isinstance(seg, CubicBezier):
        return CubicBezier(
            mirror_point(seg.start, cx),
            mirror_point(seg.control1, cx),
            mirror_point(seg.control2, cx),
            mirror_point(seg.end, cx),
        )
    return seg


mirrored_segments = []
for seg in right_side_subpath:
    mirrored_segments.append(mirror_segment(seg, center_x))

# The right side path might be going top-to-bottom or bottom-to-top.
# Sp0 is a closed loop, so it goes around.
# If right side goes top-to-bottom, mirroring it makes it go top-to-bottom on the left,
# but the left side path needs to go in the correct direction (bottom-to-top or top-to-bottom).
# Sp0 path on left goes from start_point (which is at Y ~ 82) to end_point (which is at Y ~ 621).
# Wait, start_point Y=82, end_point Y=621. So the left side goes TOP to BOTTOM.
# Let's check right_segments direction.
if mirrored_segments:
    print(f"Mirrored start: {mirrored_segments[0].start}, end: {mirrored_segments[-1].end}")

    # We must match start_point and end_point!
    # If the direction is wrong, reverse the sequence and each segment
    if abs(mirrored_segments[0].start.imag - start_y) > abs(mirrored_segments[-1].end.imag - start_y):
        print("Reversing mirrored segments")
        # Reverse the list and flip each segment
        rev = []
        for s in reversed(mirrored_segments):
            rev.append(s.reversed())
        mirrored_segments = rev

    # Now graft them!
    # We need to connect start_point -> mirrored_segments[0].start
    # and mirrored_segments[-1].end -> end_point
    start_point = sp0[start_idx - 1].end if start_idx > 0 else sp0[0].start
    end_point = sp0[end_idx + 1].start if end_idx < len(sp0) - 1 else sp0[-1].end

    patch = (
        [Line(start_point, mirrored_segments[0].start)]
        + mirrored_segments
        + [Line(mirrored_segments[-1].end, end_point)]
    )

    new_sp0 = Path(*sp0[:start_idx], *patch, *sp0[end_idx + 1 :])

    new_subpaths = [new_sp0]
    for sp in subpaths[1:]:
        xmin, xmax, ymin, ymax = sp.bbox()
        if xmax < 285 and ymax > 300 and ymin > 300:
            continue  # ignore internal hand lines
        new_subpaths.append(sp)

    wsvg(new_subpaths, filename="examples/symmetric_shield.svg")
    print("Saved examples/symmetric_shield.svg")
else:
    print("Could not find right side segments to mirror.")
