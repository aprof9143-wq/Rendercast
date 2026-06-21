"""
Core image -> vector(EPS) pipeline, kept separate from app.py so it can be
unit-tested and reused outside of Streamlit.
"""

import io

import cv2
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from matplotlib.path import Path as MplPath


def quantize_and_trace(img_rgb, k, blur, simplify_eps, min_area_px):
    """
    img_rgb: HxWx3 uint8 RGB numpy array
    Returns: list of shape dicts: {"color": (r,g,b), "area": float,
                                    "polys": [(outer_pts, [hole_pts, ...]), ...]}
    """
    height, width = img_rgb.shape[:2]

    if blur > 0:
        k_size = blur * 2 + 1
        img_blur = cv2.GaussianBlur(img_rgb, (k_size, k_size), 0)
    else:
        img_blur = img_rgb

    data = img_blur.reshape((-1, 3)).astype(np.float32)
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0)
    _, labels, centers = cv2.kmeans(
        data, k, None, criteria, attempts=4, flags=cv2.KMEANS_PP_CENTERS
    )
    centers = np.clip(centers, 0, 255).astype(np.uint8)
    labels = labels.reshape((height, width))

    shapes = []
    for ci in range(k):
        mask = (labels == ci).astype(np.uint8) * 255
        if mask.sum() == 0:
            continue

        contours, hierarchy = cv2.findContours(
            mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE
        )
        if not contours:
            continue
        hierarchy = hierarchy[0]

        polys = []
        total_area = 0.0
        for idx, cnt in enumerate(contours):
            if hierarchy[idx][3] != -1:
                continue
            area = cv2.contourArea(cnt)
            if area < min_area_px:
                continue
            outer = cv2.approxPolyDP(cnt, simplify_eps, True).reshape(-1, 2)
            if len(outer) < 3:
                continue

            holes = []
            child = hierarchy[idx][2]
            while child != -1:
                hole_cnt = contours[child]
                hole_area = cv2.contourArea(hole_cnt)
                if hole_area >= min_area_px:
                    hole_pts = cv2.approxPolyDP(
                        hole_cnt, simplify_eps, True
                    ).reshape(-1, 2)
                    if len(hole_pts) >= 3:
                        holes.append(hole_pts)
                child = hierarchy[child][0]

            polys.append((outer, holes))
            total_area += area

        if polys:
            color = tuple(int(c) for c in centers[ci])
            shapes.append({"color": color, "area": total_area, "polys": polys})

    shapes.sort(key=lambda s: -s["area"])
    return shapes


def render_preview(shapes, width, height):
    fig, ax = plt.subplots(figsize=(width / 100, height / 100), dpi=100)
    ax.set_xlim(0, width)
    ax.set_ylim(0, height)
    ax.invert_yaxis()
    ax.axis("off")
    ax.set_facecolor("white")

    for shape in shapes:
        r, g, b = shape["color"]
        facecolor = (r / 255, g / 255, b / 255)
        for outer, holes in shape["polys"]:
            verts, codes = [], []
            for pts in [outer] + holes:
                pts = [tuple(p) for p in pts]
                verts.append(pts[0])
                codes.append(MplPath.MOVETO)
                for p in pts[1:]:
                    verts.append(p)
                    codes.append(MplPath.LINETO)
                verts.append(pts[0])
                codes.append(MplPath.CLOSEPOLY)
            mpath = MplPath(verts, codes)
            patch = patches.PathPatch(
                mpath, facecolor=facecolor, edgecolor=facecolor, linewidth=0.3
            )
            ax.add_patch(patch)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", pad_inches=0)
    plt.close(fig)
    buf.seek(0)
    return buf


def shapes_to_eps(shapes, width, height):
    lines = [
        "%!PS-Adobe-3.0 EPSF-3.0",
        f"%%BoundingBox: 0 0 {width} {height}",
        f"%%HiResBoundingBox: 0 0 {width} {height}",
        "%%Creator: Streamlit Image-to-EPS Demo",
        "%%Title: vectorized",
        "%%Pages: 1",
        "%%EndComments",
        "%%Page: 1 1",
    ]

    for shape in shapes:
        r, g, b = (c / 255 for c in shape["color"])
        lines.append(f"{r:.4f} {g:.4f} {b:.4f} setrgbcolor")
        lines.append("newpath")
        for outer, holes in shape["polys"]:
            for pts in [outer] + holes:
                if len(pts) < 2:
                    continue
                x0, y0 = pts[0]
                lines.append(f"{x0:.2f} {height - y0:.2f} moveto")
                for x, y in pts[1:]:
                    lines.append(f"{x:.2f} {height - y:.2f} lineto")
                lines.append("closepath")
        lines.append("eofill")

    lines.append("%%EOF")
    return "\n".join(lines)
