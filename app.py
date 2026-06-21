"""
Image -> EPS Vector Converter (Demo)
=====================================
A Streamlit app that takes a PNG/JPG raster image and produces a simplified
EPS vector approximation using color-region segmentation + contour tracing.

This is a DEMO pipeline built entirely from pip-installable, pure-Python /
precompiled-wheel dependencies (no system binaries like potrace, Inkscape,
or Ghostscript required). It approximates shapes with straight-line polygons
(not smooth Bezier curves). See IMPLEMENTATION_GUIDE.md for how to evolve
this into a production-grade vectorizer.
"""

import numpy as np
import streamlit as st
from PIL import Image

from eps_pipeline import quantize_and_trace, render_preview, shapes_to_eps

st.set_page_config(page_title="Image to EPS Vectorizer", layout="wide")
st.title("Image → EPS Vector Converter (Demo)")
st.caption(
    "Upload a PNG or JPG and get back a simplified vector EPS file. "
    "This demo uses color quantization + contour tracing (polygon paths)."
)

# ----------------------------- Sidebar controls -----------------------------
with st.sidebar:
    st.header("Settings")
    max_dim = st.slider(
        "Max working dimension (px)", 100, 1200, 400, step=50,
        help="Image is downscaled to this size before processing. "
             "Larger = more detail but slower processing and a bigger EPS file.",
    )
    num_colors = st.slider(
        "Palette size (number of colors)", 2, 24, 8,
        help="Number of flat color regions to extract (k-means clusters).",
    )
    blur_amount = st.slider(
        "Pre-blur (noise smoothing)", 0, 10, 2,
        help="Smooths the image before quantization to reduce speckle noise.",
    )
    simplify_amt = st.slider(
        "Path simplification", 0.5, 10.0, 2.0, step=0.5,
        help="Higher values produce fewer path points / simpler shapes.",
    )
    min_area = st.slider(
        "Minimum region size (px²) to keep", 0, 500, 20,
        help="Discards tiny speckle regions smaller than this area.",
    )

uploaded = st.file_uploader("Upload an image", type=["png", "jpg", "jpeg"])


# --------------------------------- App flow ---------------------------------
if uploaded:
    pil_img = Image.open(uploaded).convert("RGB")
    w0, h0 = pil_img.size
    scale = max_dim / max(w0, h0)
    if scale < 1:
        pil_img = pil_img.resize(
            (max(1, int(w0 * scale)), max(1, int(h0 * scale))), Image.LANCZOS
        )
    img = np.array(pil_img)
    height, width = img.shape[:2]

    with st.spinner("Tracing vector shapes..."):
        shapes = quantize_and_trace(
            img, num_colors, blur_amount, simplify_amt, min_area
        )
        preview_buf = render_preview(shapes, width, height)
        eps_str = shapes_to_eps(shapes, width, height)

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Original")
        st.image(pil_img, use_container_width=True)
    with col2:
        st.subheader("Vector Preview")
        st.image(preview_buf, use_container_width=True)

    n_paths = sum(len(s["polys"]) for s in shapes)
    st.write(
        f"**{len(shapes)}** color regions · **{n_paths}** vector paths · "
        f"output size **{width}×{height} px** · EPS file size "
        f"**{len(eps_str) / 1024:.1f} KB**"
    )

    st.download_button(
        "⬇️ Download EPS",
        data=eps_str,
        file_name="vectorized.eps",
        mime="application/postscript",
    )

    with st.expander("Preview raw EPS source"):
        preview_text = eps_str[:3000]
        st.code(
            preview_text + ("\n... (truncated)" if len(eps_str) > 3000 else ""),
            language="postscript",
        )
else:
    st.info("Upload a PNG or JPG image to get started.")
