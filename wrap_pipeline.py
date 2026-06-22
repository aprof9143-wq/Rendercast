"""
Core pipeline for the Wrap Panel & Print-Prep tool.

Takes a flat (already correctly-shaped) piece of artwork for one vehicle
section (e.g. "Driver Side"), a target true-world size, and printer/roll
constraints, and produces print-ready EPS file(s): the artwork is embedded
as an actual JPEG (DCTDecode) inside hand-written PostScript -- this keeps
full photographic/gradient quality (vehicle wrap graphics are NOT flattened
to vector shapes in real production; only the page geometry, bleed lines,
and registration marks are vector).

Kept dependency-free beyond Pillow + numpy + stdlib so it stays easy to
install (see requirements.txt).
"""

import base64
import io
import math
from dataclasses import dataclass, field
from typing import List, Literal

from PIL import Image

# Vehicle wrap canvases are legitimately huge: e.g. a 220in x 64in side panel
# at 150 DPI is ~316 megapixels. PIL's default decompression-bomb guard
# (~179 megapixels) is meant to protect against malicious/corrupt uploads,
# not this kind of expected large, intentional print canvas, so we raise it.
# This module should only ever process artwork the operator explicitly
# uploaded/generated, not arbitrary untrusted files from the open internet.
Image.MAX_IMAGE_PIXELS = 600_000_000

PT_PER_IN = 72.0  # PostScript points per inch


# --------------------------------------------------------------------------
# 1. Panel math
# --------------------------------------------------------------------------
@dataclass
class Panel:
    index: int
    start_in: float      # start position along the paneled axis, in inches
    width_in: float       # this panel's full printed size along that axis (includes overlap)
    pitch_in: float        # the "new" advance this panel contributes (width_in - overlap, except panel 0)


def compute_panels(total_length_in: float, roll_width_in: float, overlap_in: float) -> List[Panel]:
    """
    Split `total_length_in` into panels no wider than `roll_width_in`, with
    `overlap_in` of shared/duplicated artwork between adjacent panels so
    installers can align and double-cut the seam.

    Panel sizes are kept EQUAL (rather than leaving an uneven sliver on the
    last panel), which is standard practice.
    """
    if roll_width_in <= overlap_in:
        raise ValueError("Roll width must be greater than the overlap/bleed amount.")
    if total_length_in <= 0:
        raise ValueError("Total length must be positive.")

    if total_length_in <= roll_width_in:
        return [Panel(index=0, start_in=0.0, width_in=total_length_in, pitch_in=total_length_in)]

    usable = roll_width_in - overlap_in
    n = math.ceil((total_length_in - overlap_in) / usable)
    pitch = (total_length_in - overlap_in) / n
    panel_width = pitch + overlap_in

    panels = []
    for i in range(n):
        start = i * pitch
        panels.append(Panel(index=i, start_in=start, width_in=panel_width, pitch_in=pitch))
    return panels


# --------------------------------------------------------------------------
# 2. Image fitting to a true-world-size canvas
# --------------------------------------------------------------------------
FitMode = Literal["stretch", "cover", "contain"]


def fit_image_to_canvas(img: Image.Image, target_w_px: int, target_h_px: int, mode: FitMode) -> Image.Image:
    """Resize `img` to exactly (target_w_px, target_h_px)."""
    img = img.convert("RGB")
    if mode == "stretch":
        return img.resize((target_w_px, target_h_px), Image.LANCZOS)

    src_w, src_h = img.size
    src_ratio = src_w / src_h
    dst_ratio = target_w_px / target_h_px

    if mode == "cover":
        # scale to cover the target box, then center-crop the excess
        if src_ratio > dst_ratio:
            new_h = target_h_px
            new_w = round(new_h * src_ratio)
        else:
            new_w = target_w_px
            new_h = round(new_w / src_ratio)
        resized = img.resize((new_w, new_h), Image.LANCZOS)
        left = (new_w - target_w_px) // 2
        top = (new_h - target_h_px) // 2
        return resized.crop((left, top, left + target_w_px, top + target_h_px))

    if mode == "contain":
        # scale to fit fully inside the target box, pad the rest with white
        if src_ratio > dst_ratio:
            new_w = target_w_px
            new_h = round(new_w / src_ratio)
        else:
            new_h = target_h_px
            new_w = round(new_h * src_ratio)
        resized = img.resize((new_w, new_h), Image.LANCZOS)
        canvas = Image.new("RGB", (target_w_px, target_h_px), (255, 255, 255))
        left = (target_w_px - new_w) // 2
        top = (target_h_px - new_h) // 2
        canvas.paste(resized, (left, top))
        return canvas

    raise ValueError(f"Unknown fit mode: {mode}")


def effective_source_dpi(img: Image.Image, target_w_in: float, target_h_in: float) -> float:
    """The lower of the two axis DPIs the SOURCE image actually provides at
    the requested true-world print size -- i.e. how much real detail exists,
    regardless of how much we end up upscaling it."""
    src_w, src_h = img.size
    return min(src_w / target_w_in, src_h / target_h_in)


# --------------------------------------------------------------------------
# 3. EPS building blocks
# --------------------------------------------------------------------------
def _jpeg_image_block(img: Image.Image, jpeg_quality: int, box_w_pt: float, box_h_pt: float, x_pt: float = 0.0, y_pt: float = 0.0) -> str:
    """Return PostScript that draws `img` filling a box of size
    (box_w_pt x box_h_pt) at offset (x_pt, y_pt), using an embedded
    DCTDecode (JPEG) image so photographic quality is preserved."""
    w_px, h_px = img.size
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=jpeg_quality)
    jpeg_bytes = buf.getvalue()
    a85 = base64.a85encode(jpeg_bytes, adobe=False).decode("ascii")
    wrapped = "\n".join(a85[i:i + 90] for i in range(0, len(a85), 90))

    return (
        "gsave\n"
        f"{x_pt:.3f} {y_pt:.3f} translate\n"
        f"{box_w_pt:.3f} {box_h_pt:.3f} scale\n"
        "/DeviceRGB setcolorspace\n"
        "<<\n"
        "  /ImageType 1\n"
        f"  /Width {w_px}\n"
        f"  /Height {h_px}\n"
        "  /BitsPerComponent 8\n"
        "  /Decode [0 1 0 1 0 1]\n"
        f"  /ImageMatrix [{w_px} 0 0 -{h_px} 0 {h_px}]\n"
        "  /DataSource currentfile /ASCII85Decode filter /DCTDecode filter\n"
        ">> image\n"
        f"{wrapped}~>\n"
        "grestore\n"
    )


def _crop_marks(w_pt: float, h_pt: float, mark_len_pt: float = 18, offset_pt: float = 6) -> str:
    """Small L-shaped crop marks just outside each corner."""
    lines = ["0 0 0 setrgbcolor", "0.5 setlinewidth"]
    corners = [(0, 0, 1, 1), (w_pt, 0, -1, 1), (0, h_pt, 1, -1), (w_pt, h_pt, -1, -1)]
    for cx, cy, sx, sy in corners:
        lines.append("newpath")
        lines.append(f"{cx + sx*offset_pt:.2f} {cy:.2f} moveto")
        lines.append(f"{cx + sx*(offset_pt+mark_len_pt):.2f} {cy:.2f} lineto")
        lines.append("stroke")
        lines.append("newpath")
        lines.append(f"{cx:.2f} {cy + sy*offset_pt:.2f} moveto")
        lines.append(f"{cx:.2f} {cy + sy*(offset_pt+mark_len_pt):.2f} lineto")
        lines.append("stroke")
    return "\n".join(lines) + "\n"


def _overlap_line(w_pt: float, h_pt: float, x_pt: float, dash: bool = True) -> str:
    """A vertical line marking where this panel's non-overlapped pitch ends
    (i.e. the actual seam / trim line for the install crew)."""
    dash_cmd = "[6 4] 0 setdash" if dash else "[] 0 setdash"
    return (
        "0.85 0.1 0.1 setrgbcolor\n"
        "1 setlinewidth\n"
        f"{dash_cmd}\n"
        "newpath\n"
        f"{x_pt:.2f} 0 moveto\n"
        f"{x_pt:.2f} {h_pt:.2f} lineto\n"
        "stroke\n"
        "[] 0 setdash\n"
    )


def _label_text(lines: List[str], x_pt: float, y_pt: float, font_size: float = 10) -> str:
    out = [
        "0 0 0 setrgbcolor",
        f"/Helvetica findfont {font_size} scalefont setfont",
    ]
    for i, line in enumerate(lines):
        safe = line.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        out.append(f"{x_pt:.2f} {y_pt - i*(font_size+2):.2f} moveto ({safe}) show")
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------
# 4. Full panel EPS + combined overview EPS
# --------------------------------------------------------------------------
@dataclass
class WrapJob:
    section_name: str
    axis: Literal["width", "height"]   # which physical dimension gets paneled
    target_w_in: float
    target_h_in: float
    roll_width_in: float
    overlap_in: float
    jpeg_quality: int = 90
    show_reg_marks: bool = True
    bleed_in: float = 0.0  # extra full-perimeter bleed beyond true size (optional, e.g. for edge wrap-around)


def build_panel_jobs(canvas_img: Image.Image, job: WrapJob, dpi: float):
    """
    canvas_img: already fit to (target size + perimeter bleed) at `dpi`.
    Returns list of dicts: {panel, crop_img, fixed_in, paneled_total_in}
    """
    w_px, h_px = canvas_img.size
    bleed_px = job.bleed_in * dpi

    if job.axis == "width":
        total_len_in = job.target_w_in + 2 * job.bleed_in
        fixed_in = job.target_h_in + 2 * job.bleed_in
    else:
        total_len_in = job.target_h_in + 2 * job.bleed_in
        fixed_in = job.target_w_in + 2 * job.bleed_in

    panels = compute_panels(total_len_in, job.roll_width_in, job.overlap_in)

    results = []
    for p in panels:
        start_px = round(p.start_in * dpi)
        size_px = round(p.width_in * dpi)
        if job.axis == "width":
            box = (start_px, 0, min(start_px + size_px, w_px), h_px)
        else:
            # height axis: panel 0 = top of artwork
            box = (0, start_px, w_px, min(start_px + size_px, h_px))
        crop = canvas_img.crop(box)
        results.append({"panel": p, "crop": crop, "fixed_in": fixed_in, "total_len_in": total_len_in})
    return results


def panel_to_eps(job: WrapJob, panel_info: dict, n_total: int) -> str:
    p: Panel = panel_info["panel"]
    crop = panel_info["crop"]
    fixed_in = panel_info["fixed_in"]

    if job.axis == "width":
        w_in, h_in = p.width_in, fixed_in
    else:
        w_in, h_in = fixed_in, p.width_in

    w_pt, h_pt = w_in * PT_PER_IN, h_in * PT_PER_IN

    body = []
    body.append(_jpeg_image_block(crop, job.jpeg_quality, w_pt, h_pt))

    if job.show_reg_marks:
        body.append(_crop_marks(w_pt, h_pt))
        # seam/trim line at the end of this panel's non-overlap pitch (skip on the last panel)
        if p.index < n_total - 1:
            if job.axis == "width":
                body.append(_overlap_line(w_pt, h_pt, p.pitch_in * PT_PER_IN))
            else:
                # rotate concept: draw horizontal seam line instead
                seam_y = h_pt - p.pitch_in * PT_PER_IN
                body.append(
                    "0.85 0.1 0.1 setrgbcolor\n1 setlinewidth\n[6 4] 0 setdash\n"
                    f"newpath 0 {seam_y:.2f} moveto {w_pt:.2f} {seam_y:.2f} lineto stroke\n"
                    "[] 0 setdash\n"
                )

    label_lines = [
        f"{job.section_name} - Panel {p.index + 1} of {n_total}",
        f"Print size: {w_in:.1f}in x {h_in:.1f}in   Overlap: {job.overlap_in:.1f}in",
    ]
    body.append(_label_text(label_lines, x_pt=6, y_pt=h_pt - 14))

    eps = (
        "%!PS-Adobe-3.0 EPSF-3.0\n"
        f"%%BoundingBox: 0 0 {w_pt:.0f} {h_pt:.0f}\n"
        f"%%HiResBoundingBox: 0 0 {w_pt:.3f} {h_pt:.3f}\n"
        "%%Creator: Wrap Panel Print-Prep Tool\n"
        f"%%Title: {job.section_name} panel {p.index + 1} of {n_total}\n"
        "%%Pages: 1\n"
        "%%EndComments\n"
        + "\n".join(body)
        + "%%EOF\n"
    )
    return eps


def build_combined_overview_eps(job: WrapJob, canvas_img: Image.Image, panel_jobs: list) -> str:
    """A single proof-sheet EPS showing the whole section with seam lines,
    for review before sending individual panel files to the printer."""
    w_px, h_px = canvas_img.size
    # Use a modest DPI-independent point size driven by true inches
    if job.axis == "width":
        w_in = panel_jobs[0]["total_len_in"]
        h_in = panel_jobs[0]["fixed_in"]
    else:
        h_in = panel_jobs[0]["total_len_in"]
        w_in = panel_jobs[0]["fixed_in"]

    w_pt, h_pt = w_in * PT_PER_IN, h_in * PT_PER_IN

    body = [_jpeg_image_block(canvas_img, job.jpeg_quality, w_pt, h_pt)]

    for info in panel_jobs:
        p: Panel = info["panel"]
        if job.axis == "width":
            x = p.start_in * PT_PER_IN
            body.append(
                "0.1 0.4 0.9 setrgbcolor\n0.75 setlinewidth\n[3 3] 0 setdash\n"
                f"newpath {x:.2f} 0 moveto {x:.2f} {h_pt:.2f} lineto stroke\n[] 0 setdash\n"
            )
        else:
            y = h_pt - p.start_in * PT_PER_IN
            body.append(
                "0.1 0.4 0.9 setrgbcolor\n0.75 setlinewidth\n[3 3] 0 setdash\n"
                f"newpath 0 {y:.2f} moveto {w_pt:.2f} {y:.2f} lineto stroke\n[] 0 setdash\n"
            )

    body.append(_label_text(
        [f"{job.section_name} - overview ({len(panel_jobs)} panels) - {w_in:.1f}in x {h_in:.1f}in"],
        x_pt=6, y_pt=h_pt - 14,
    ))

    eps = (
        "%!PS-Adobe-3.0 EPSF-3.0\n"
        f"%%BoundingBox: 0 0 {w_pt:.0f} {h_pt:.0f}\n"
        f"%%HiResBoundingBox: 0 0 {w_pt:.3f} {h_pt:.3f}\n"
        "%%Creator: Wrap Panel Print-Prep Tool\n"
        f"%%Title: {job.section_name} overview\n"
        "%%Pages: 1\n"
        "%%EndComments\n"
        + "\n".join(body)
        + "%%EOF\n"
    )
    return eps
