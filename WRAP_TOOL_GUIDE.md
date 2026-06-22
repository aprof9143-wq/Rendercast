# Wrap Panel & Print-Prep Tool — Guide

## 1. What this tool actually solves

Your full workflow has two genuinely different problems in it. This tool
solves **only the second one**, on purpose:

| Step | Problem | Solved here? |
|---|---|---|
| 1 | Customer's 3D mockup PNG → flat, panel-accurate artwork | ❌ No — see §2 |
| 2 | Flat artwork → true-size, paneled, print-ready EPS with bleed/registration | ✅ Yes |

It was built this way deliberately: step 2 is mechanical and fully
automatable; step 1 is a production-art problem that can't be reliably
automated from a single rendered PNG alone (no clean way to recover true
flat geometry from a perspective render with baked-in lighting and
occluded surfaces). Trying to fake step 1 would produce files that *look*
done but are wrong in ways that only show up after print — the
expensive way to find out.

## 2. Handling step 1 (mockup → flat artwork) in practice

Until you have a vehicle template/3D pipeline in place, the realistic
options, roughly in order of preference:

1. **Ask the designer for the native flat layers** (AI/PSD) they used to
   build the 3D mockup, instead of the rendered PNG. Most designers create
   the art flat first, then render it onto a 3D van model for client
   approval — the flat source usually already exists.
2. **Build (once) a flat panel template per vehicle make/model/year**
   (hood, roof, doors, sides, rear), either by licensing one from an
   existing wrap-template vendor or measuring/photographing real panels.
   Once you have it, *any* design — mockup or not — gets placed onto the
   template rather than reverse-engineered from a render.
3. **Long-term:** move to a UV-mapped 3D design tool (e3 Design,
   WrapRageous, Adobe Substance) where designers paint directly on a 3D
   model and the flat panel layout comes out automatically — this
   eliminates the problem entirely rather than working around it.
4. **If you only ever get a flattened PNG with no template:** a production
   artist manually redraws/re-places the design elements onto a flat
   template using the mockup as visual reference only. A perspective-correct
   homography per visible panel can generate a rough starting underlay to
   speed this up, but a person still has to clean it up and fill in
   anything occluded in the render.

This tool's input (`Upload flat wrap artwork`) is meant to be the *output*
of whichever of the above you use — i.e. by the time it reaches this tool,
the artwork should already be flat and correctly proportioned for the
section it's going on.

## 3. What this tool automates, in detail

Given flat artwork + the true size you want it printed at:

1. **Fit to true size** — `cover` (scale + center-crop, no distortion),
   `stretch` (force exact dimensions), or `contain` (fit inside, pad).
2. **DPI/quality check** — computes the *effective source DPI* the
   uploaded image actually provides at the requested true size, and warns
   if it's below a reasonable print threshold (~100 DPI). This catches the
   common real failure mode: a client-approval mockup that looks fine on
   screen but was never meant to print at 18 feet long.
3. **Panel math** — splits the chosen axis into equal-sized panels, each
   ≤ your roll width, with your specified seam overlap shared between
   adjacent panels (so installers have material to align and double-cut).
4. **EPS export per panel** — each panel becomes its own EPS with:
   - the artwork embedded **as an actual JPEG** (via PostScript's
     `DCTDecode` image mechanism) — this preserves full photographic/
     gradient quality. Real wrap graphics are *not* flattened to vector
     shapes in production; only the page geometry, bleed lines, and
     registration marks are vector. (If you tried the earlier
     image-vectorization demo on a photographic wrap design, this is why
     that approach is the wrong tool here — it would have flattened
     gradients/photos into blocky solid-color shapes.)
   - corner registration/crop marks
   - a dashed seam/trim line marking where this panel's non-overlapped
     portion ends
   - a text label (section name, panel number, true print size, overlap)
5. **Combined overview EPS** — the whole section as one proof sheet with
   all seam lines marked, for review before sending individual panel files
   to the printer.
6. **Bundled download** — a ZIP with every panel EPS + the overview, plus
   individual download buttons per panel.

### Why hand-written EPS instead of an external library
Embedding a JPEG via `DCTDecode` + `ASCII85Decode` is a few dozen lines of
plain PostScript and needs zero system dependencies (no Ghostscript,
Inkscape, or potrace required to *generate* files — only `Pillow` for image
handling). This was verified by rendering every generated EPS back through
Ghostscript and checking image orientation, color, embedded text, and seam
line positions pixel-by-pixel during development.

## 4. Setup & running

```bash
pip install -r requirements.txt
streamlit run app.py
```

No system packages required to run it. (Ghostscript is only useful
*optionally*, if you want to spot-check a generated EPS yourself locally —
`gs -sDEVICE=png16m -r150 -sOutputFile=check.png panel_1.eps`.)

## 5. Known limitations / what to harden before relying on this in production

- **Single-axis paneling only.** If *both* the width and height of a
  section exceed your roll width (large box trucks, RVs), you need a 2D
  grid of panels — the tool currently warns about this but doesn't split
  the fixed axis automatically. Worth adding if you do these vehicles.
- **One section per run.** A whole van needs this run once per section
  (driver side, passenger side, hood, roof, rear, etc.). Straightforward to
  extend into a batch/multi-section UI — the underlying `wrap_pipeline.py`
  functions already operate per-section, so the UI loop is the main thing
  to add.
- **Color space is RGB, not CMYK.** Most modern large-format printers
  (HP Latex, Roland, Mimaki, Epson) run RGB workflows with RIP-side color
  management, so this matches common practice — but if your specific RIP
  expects embedded CMYK JPEGs, that needs Adobe-style APP14-marker handling
  on top of what's here, and should be validated against your specific
  printer/RIP before a full production run.
- **No vehicle template library yet.** This tool doesn't know vehicle
  shapes — it trusts the width/height you type in. Pairing it with a
  template library (see §2) is the natural next investment, and would also
  let you validate that uploaded artwork's aspect ratio roughly matches the
  real panel shape before it ever gets this far.
- **No automated render-back QA in the app itself.** During development,
  every output was checked by rendering it back to PNG with Ghostscript and
  comparing pixel positions. Worth wiring into an automated test suite
  (a small fixed set of test images + expected panel counts/positions) if
  this becomes a relied-upon production tool, so future changes can't
  silently break panel math or image embedding.
