"""
Wrap Panel & Print-Prep Tool
============================
Takes a flat (already correctly-shaped) wrap design for ONE vehicle section
(e.g. "Driver Side", "Hood", "Rear Doors"), a true real-world size, and
roll/printer constraints, and produces print-ready EPS file(s): split into
panels no wider than the printer's roll, with seam overlap, registration
marks, and panel labels -- scaled to true vehicle dimensions.

IMPORTANT SCOPE NOTE (read this before relying on it for production):
This tool does NOT attempt to turn a 3D rendered mockup into flat,
panel-accurate artwork -- that step still requires either the designer's
native flat layers, a vehicle template, or manual production-art work (see
WRAP_TOOL_GUIDE.md). This tool automates the part that genuinely CAN be
automated: turning correctly-shaped flat artwork into a paneled,
true-to-size, print-ready file.
"""

import io
import zipfile

import streamlit as st
from PIL import Image

from wrap_pipeline import (
    WrapJob,
    fit_image_to_canvas,
    effective_source_dpi,
    build_panel_jobs,
    panel_to_eps,
    build_combined_overview_eps,
)

st.set_page_config(page_title="Wrap Panel & Print-Prep Tool", layout="wide")
st.title("🚐 Wrap Panel & Print-Prep Tool")
st.caption(
    "Turn correctly-shaped flat wrap artwork into print-ready, paneled EPS "
    "files at true vehicle size — with seam overlap, registration marks, "
    "and panel labels."
)

with st.expander("ℹ️ What this tool does and doesn't do (read first)", expanded=False):
    st.markdown(
        """
**This tool assumes the artwork you upload is already flat and correctly
shaped** for the vehicle section it's going on (i.e. it's print-ready art,
not a 3D rendered mockup with perspective/lighting baked in).

- ✅ Automates: scaling to true size, slicing into roll-width panels,
  seam overlap, registration/crop marks, panel labels, DPI/quality check,
  print-ready EPS export (artwork embedded as JPEG so photographic
  quality/gradients are preserved — wrap graphics aren't flattened to
  vector shapes, only the page geometry and marks are vector).
- ❌ Does NOT do: turning a 3D mockup render into flat panel-accurate
  artwork. That step needs the designer's native flat layers, a vehicle
  template, or manual production-art recreation. See
  `WRAP_TOOL_GUIDE.md` for how to handle that part of the workflow.
        """
    )

# ----------------------------- Sidebar controls -----------------------------
with st.sidebar:
    st.header("Section & vehicle sizing")
    section_name = st.text_input("Section name", value="Driver Side")
    target_w_in = st.number_input("Target width (in)", min_value=1.0, value=220.0, step=1.0)
    target_h_in = st.number_input("Target height (in)", min_value=1.0, value=64.0, step=1.0)
    fit_mode = st.selectbox(
        "Fit mode",
        options=["cover", "stretch", "contain"],
        format_func=lambda m: {
            "cover": "Cover (scale to fill, crop excess — no distortion)",
            "stretch": "Stretch (force exact size — may distort)",
            "contain": "Contain (fit fully inside, pad with white)",
        }[m],
    )

    st.header("Printer / roll settings")
    roll_width_in = st.number_input("Roll width (in)", min_value=10.0, value=52.0, step=1.0)
    overlap_in = st.number_input("Seam overlap / bleed (in)", min_value=0.0, value=2.0, step=0.5)
    axis = st.selectbox(
        "Panel along",
        options=["width", "height"],
        index=0 if target_w_in >= target_h_in else 1,
        format_func=lambda a: "Width (vertical seams, full height each panel)" if a == "width"
        else "Height (horizontal seams, full width each panel)",
        help="Pick the dimension that needs to be split because it exceeds the roll width. "
             "Usually this is the longer dimension (e.g. the length of a van side).",
    )

    st.header("Output quality")
    dpi = st.slider("Working resolution (DPI)", 50, 300, 100, step=10,
                     help="Pixel density at true size. Higher = sharper but much slower/larger files.")
    jpeg_quality = st.slider("JPEG quality", 50, 100, 90)
    show_reg_marks = st.checkbox("Show registration/crop marks + seam lines", value=True)

uploaded = st.file_uploader("Upload flat wrap artwork (PNG or JPG)", type=["png", "jpg", "jpeg"])


# --------------------------------- App flow ---------------------------------
if uploaded:
    src_img = Image.open(uploaded).convert("RGB")

    eff_dpi = effective_source_dpi(src_img, target_w_in, target_h_in)
    fixed_dim_in = target_h_in if axis == "width" else target_w_in
    if fixed_dim_in > roll_width_in:
        st.warning(
            f"Your **{'height' if axis=='width' else 'width'}** ({fixed_dim_in:.1f}in) is larger than "
            f"the roll width ({roll_width_in:.1f}in). This tool only panels along one axis at a time, "
            "so this dimension will print at full size in a single pass — make sure your printer/roll "
            "can actually handle that, or switch the 'Panel along' setting / use a wider roll."
        )

    if eff_dpi < 100:
        st.warning(
            f"⚠️ Effective source resolution is only **{eff_dpi:.0f} DPI** at true size. "
            "Vehicle wraps are typically printed around 100-150 DPI; below that, expect visible "
            "softness/pixelation up close. Ask for a higher-resolution source file if this needs "
            "to hold up to close viewing."
        )
    else:
        st.success(f"✅ Effective source resolution at true size: **{eff_dpi:.0f} DPI**")

    job = WrapJob(
        section_name=section_name,
        axis=axis,
        target_w_in=target_w_in,
        target_h_in=target_h_in,
        roll_width_in=roll_width_in,
        overlap_in=overlap_in,
        jpeg_quality=jpeg_quality,
        show_reg_marks=show_reg_marks,
        bleed_in=0.0,
    )

    with st.spinner("Fitting artwork to true size and building panels..."):
        target_w_px = max(1, round(target_w_in * dpi))
        target_h_px = max(1, round(target_h_in * dpi))
        canvas = fit_image_to_canvas(src_img, target_w_px, target_h_px, fit_mode)
        panel_jobs = build_panel_jobs(canvas, job, dpi)

        panel_eps_list = [
            panel_to_eps(job, info, len(panel_jobs)) for info in panel_jobs
        ]
        overview_eps = build_combined_overview_eps(job, canvas, panel_jobs)

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Original upload")
        st.image(src_img, use_container_width=True)
    with col2:
        st.subheader(f"Fitted to true size ({target_w_in:.0f}in × {target_h_in:.0f}in)")
        preview = canvas.copy()
        preview.thumbnail((900, 900))
        st.image(preview, use_container_width=True)

    st.write(
        f"**{len(panel_jobs)}** panel(s) · roll width **{roll_width_in:.0f}in** · "
        f"overlap **{overlap_in:.1f}in** · working canvas **{canvas.size[0]}×{canvas.size[1]} px** "
        f"at **{dpi} DPI**"
    )

    panel_table = []
    for info in panel_jobs:
        p = info["panel"]
        w_in, h_in = (p.width_in, info["fixed_in"]) if axis == "width" else (info["fixed_in"], p.width_in)
        panel_table.append(
            {
                "Panel": p.index + 1,
                "Print size (in)": f"{w_in:.1f} × {h_in:.1f}",
                "Starts at (in)": f"{p.start_in:.1f}",
                "Non-overlap advance (in)": f"{p.pitch_in:.1f}",
            }
        )
    st.table(panel_table)

    # Build a downloadable ZIP with all panel EPS files + overview
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        safe_section = "".join(c if c.isalnum() else "_" for c in section_name)
        for i, eps_str in enumerate(panel_eps_list):
            zf.writestr(f"{safe_section}_panel_{i+1}_of_{len(panel_eps_list)}.eps", eps_str)
        zf.writestr(f"{safe_section}_overview.eps", overview_eps)
    zip_buf.seek(0)

    st.download_button(
        "⬇️ Download all panels + overview (ZIP of EPS files)",
        data=zip_buf,
        file_name=f"{safe_section}_print_ready.zip",
        mime="application/zip",
    )

    with st.expander("Download individual panel EPS files"):
        for i, eps_str in enumerate(panel_eps_list):
            st.download_button(
                f"Panel {i+1} of {len(panel_eps_list)}",
                data=eps_str,
                file_name=f"{safe_section}_panel_{i+1}_of_{len(panel_eps_list)}.eps",
                mime="application/postscript",
                key=f"panel_dl_{i}",
            )
else:
    st.info("Upload a flat wrap design (PNG or JPG) for one vehicle section to get started.")
