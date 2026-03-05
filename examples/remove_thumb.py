import os
from svgpathtools import svg2paths, Path, CubicBezier, Line
from pathlib import Path as pathlibPath

asset_dir = pathlibPath("src/warden/assets")
svg_file = asset_dir / "warden-logo.svg"

with open(svg_file, "r") as f:
    content = f.read()

paths, attributes = svg2paths(str(svg_file))
main_path = paths[0]
subpaths = main_path.continuous_subpaths()
sp0 = subpaths[0]

# Replace segments 6 through 11 with a smooth CubicBezier from sp0[5].end to sp0[12].start
start_point = sp0[5].end
end_point = sp0[12].start

# Let's make the curve bulge slightly upwards over the fist
# start_point is roughly (383, 193) -> wait, the image coordinates. Let's look at start_point.
ctrl1 = complex(start_point.real - 10, start_point.imag + 5)
ctrl2 = complex(end_point.real + 10, end_point.imag - 5)
fist_top = CubicBezier(start_point, ctrl1, ctrl2, end_point)

new_sp0 = Path(*sp0[:6], fist_top, *sp0[12:])
new_main_path = Path(*([new_sp0] + subpaths[1:]))

# The full SVG path d string
new_d_str = new_main_path.d()

# We need to replace the original main path d string
original_d_str = paths[0].d()

# Unfortunately, svgpathtools might format the d string differently (e.g., spaces instead of relative commands)
# So if we just do a blind replace, we should replace the FIRST <path class="s0" d="..."> with our new_d_str
import re

new_svg_content = re.sub(r'<path class="s0" d="[^"]+"', f'<path class="s0" d="{new_d_str}"', content, count=1)

# Now, apply emotions!
# Eye and mouth are paths[6] and paths[7], but the SVG has them as the 7th and 8th <path> tags.
# Let's just find all <path class="s0" d="..."> strings
path_matches = re.findall(r'<path class="s0" d="[^"]+"', content)
if len(path_matches) >= 8:
    original_eye_tag = path_matches[6]
    original_mouth_tag = path_matches[7]

    # We will wrap these specific paths in <g> with transform
    # Wait, re.findall catches the whole string. We can replace the specific string.
    # We should append /> to the match to safely replace the whole tag.
    # Actually, original_eye_str is just `<path ... d="..."`
    # Let's cleanly replace the entire tag by matching from `<path` to `/>` or `z"/>`

    def apply_emotion(emotion_name, eye_scale, eye_trans, mouth_scale, mouth_trans):
        svg = new_svg_content  # Start with the fist-fixed SVG

        # We need the original path content for the eye and mouth exactly as it is in `svg`
        # Because we didn't touch paths 6 and 7 in our previous regex

        # Centers for transformations
        eye_cx, eye_cy = 379.6, 341.1
        mouth_cx, mouth_cy = 387.9, 378.3

        # SVG transform components
        eye_t = f"translate({eye_cx}, {eye_cy}) scale({eye_scale[0]}, {eye_scale[1]}) translate({-eye_cx}, {-eye_cy})"
        if eye_trans:
            eye_t = f"translate({eye_trans[0]}, {eye_trans[1]}) " + eye_t

        mouth_t = f"translate({mouth_cx}, {mouth_cy}) scale({mouth_scale[0]}, {mouth_scale[1]}) translate({-mouth_cx}, {-mouth_cy})"
        if mouth_trans:
            mouth_t = f"translate({mouth_trans[0]}, {mouth_trans[1]}) " + mouth_t

        # The eye tag is original_eye_tag + `/>` ? Let's look at warden-logo.svg.
        # It ends with `/>`.
        # Wait, the eye path ends with `z"/>`.

        # A safer way is to find exactly original_eye_tag and replace it with `<g transform="...">\n\t\t` + original_eye_tag
        # BUT we must also add `</g>` after it!
        # Since original_eye_tag is just `<path class="s0" d="..."`, we can replace it with `<g transform="..."><path class="s0" d="..."`
        # and then we need to insert `</g>` right before the next tag.

        # Better: we know the original file has:
        # \t\t<path class="s0" d="..."/>
        # Let's just use re.sub on the exact D strings to wrap them!

        # The D string for the eye is:
        eye_d = paths[6].d()  # this is the standard SVG format, but the file has it relative.
        # We know `path_matches[6]` HAS the exact string in the file.
        eye_d_file = path_matches[6].split('d="')[1].replace('"', "")
        mouth_d_file = path_matches[7].split('d="')[1].replace('"', "")

        eye_full_tag = f'<path class="s0" d="{eye_d_file}"/>'
        mouth_full_tag = f'<path class="s0" d="{mouth_d_file}"/>'

        # Replace in SVG
        wrapped_eye = f'<g transform="{eye_t}">\n\t\t\t{eye_full_tag}\n\t\t</g>'
        wrapped_mouth = f'<g transform="{mouth_t}">\n\t\t\t{mouth_full_tag}\n\t\t</g>'

        svg = svg.replace(eye_full_tag, wrapped_eye)
        svg = svg.replace(mouth_full_tag, wrapped_mouth)

        out_path = asset_dir / f"warden-logo-{emotion_name}.svg"
        with open(out_path, "w") as f:
            f.write(svg)
        print(f"Generated {out_path}")

    # Risk (Sad/Anxious)
    # Eye: scaled down Y, translated up. Mouth: scaled down Y, reflected Y?
    # Sad eye: drooping (scale down Y)
    # Sad mouth: frown (scale Y by -0.8 to flip it!)
    apply_emotion("risk", (1.0, 0.8), (0, -5), (1.0, -0.6), (0, 15))

    # Critical (Angry)
    # Eye: slanted (we can't easily slant, but we can scale down Y heavily)
    # Mouth: flip Y slightly, scale down X
    apply_emotion("critical", (1.1, 0.7), (0, 5), (0.9, -0.8), (0, 10))

else:
    print("Could not find enough paths in the SVG to apply emotions.")
