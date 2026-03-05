import sys
from svgpathtools import svg2paths, Path, CubicBezier, Line, wsvg
import math

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

start_idx = out_indices[0]
end_idx = out_indices[-1]

# We need to bridge sp0[start_idx-1].end to sp0[end_idx+1].start
start_point = sp0[start_idx - 1].end if start_idx > 0 else sp0[0].start
end_point = sp0[end_idx + 1].start if end_idx < len(sp0) - 1 else sp0[-1].end

# The right side of the shield bulges outward (to larger X values)
# The left side should bulge outward (to smaller X values).
# Let's inspect the tangents of the curves we're connecting to!
# By making the new curve's control points tangent to the existing curves, it will be perfectly smooth.

# Incoming curve tangent vector at its end
in_seg = sp0[start_idx - 1]
# length 20 to control point
p1 = start_point
p2 = start_point + in_seg.derivative(1) * 0.1  # push it along the derivative

out_seg = sp0[end_idx + 1]
p4 = end_point
p3 = end_point - out_seg.derivative(0) * 0.1  # pull it back along derivative

# Let's manually set the control points to just bulge out mildly
# A straight line has X from 238 to 165. The midpoint is around 200.
# We want it to bulge to, say, x=140.
mid_y = (start_point.imag + end_point.imag) / 2
ctrl1 = complex(140, start_point.imag + (end_point.imag - start_point.imag) * 0.3)
ctrl2 = complex(130, start_point.imag + (end_point.imag - start_point.imag) * 0.7)

bridge = CubicBezier(start_point, ctrl1, ctrl2, end_point)

new_sp0 = Path(*sp0[:start_idx], bridge, *sp0[end_idx + 1 :])

new_subpaths = [new_sp0]
for sp in subpaths[1:]:
    xmin, xmax, ymin, ymax = sp.bbox()
    if xmax < 285 and ymax > 300 and ymin > 300:
        continue  # ignore internal hand lines
    new_subpaths.append(sp)

wsvg(new_subpaths, filename="examples/bezier_shield.svg")
print("Saved examples/bezier_shield.svg")
