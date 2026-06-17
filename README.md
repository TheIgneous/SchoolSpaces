# School Spaces — 3D BIM POC (FP-202 First Floor)

A lightweight, browser-navigable 3D **space model** built from a single floor-plan
PDF. Built to help schools talk about spaces with non-technical stakeholders:
orbit the model, click a room, read its real-world size.

This is a **space-massing** model (true sizes + relationships), not a full BIM —
no wall types, MEP, or IFC. That's the right altitude for the stakeholder use case.

## Run it

```bash
cd D:/Projects/Playground/BIM
python -m http.server 8777
# open http://127.0.0.1:8777/  in a browser
```
The model data is embedded in `spaces-data.js`, so you can also just **double-click
`index.html`** (no server needed). Internet is required either way — Three.js loads
from a CDN.

## What you get
- ~94 rooms + circulation, extruded as **real polygon footprints** at true scale and
  orientation, colour-coded by category.
- Click any room → name, plan area, footprint extent, level, finished-floor level.
- Search box, category toggles, label toggle, reset view.
- Rooms whose exact shape couldn't be auto-traced are **flagged** (amber outline +
  an "approximate footprint" note) — sized correctly, shape estimated.

## How it's made — pass 2 (`build_spaces_v2.py` → `spaces_v2.json` + `spaces-data.js`)
The PDF is a flattened CAD export: ~410k vector paths + positioned text labels, no
layers. The pipeline recovers real footprints instead of guessing boxes:

1. **Area labels** — each `"xx.xx sqm"` label sits at a room's centre, giving every
   room its *true area*, *position*, and *name* directly from the drawing.
2. **Scale** — calibrated from the classroom grid pitch (stacked identical
   ~58.76 m² rooms are ~90.6 pt apart → **0.0846 m/pt**). Geometric → robust.
3. **Walls** — isolated from furniture/text by **segment length** (walls are long
   lines; fixtures are short), on the thin black linework band (the grid is dropped
   by colour/weight).
4. **Footprints** — one seed per room label + auto-seeded corridor markers feed a
   **marker-based watershed**, which tiles the floor into **non-overlapping** basins
   that split at walls and door gaps. Each basin → contour → simplified polygon.
5. **QA + flagging** — every footprint is checked against its printed area; any room
   off by more than the tolerance is regrown from its seed *inside its own basin* to
   the true area (so it can never overlap a neighbour) and flagged.

Outputs `qa_overlay.png` (extracted polygons over the plan: green = exact,
red = regrown/flagged, blue = circulation) for at-a-glance QA.

Rebuild after changing the source or logic:
```bash
pip install PyMuPDF numpy opencv-python-headless   # one-time
python build_spaces_v2.py
```

## Accuracy (this POC)
- ~53/94 rooms are exact auto-traced footprints; the rest are area-true, in-basin
  approximations, flagged in the UI. Nothing is silently wrong.
- True sizes, positions, orientations, and adjacencies; **no overlaps** by construction.
- Single floor, single phase (Phase 1). Multi-floor needs the other plan sheets.

## Next steps toward a real product
- Stack multiple floors (one dataset per level) for a whole-building view.
- First-person "walk the corridors" camera mode.
- Exact footprints via the native `.dwg` (room polylines) instead of the PDF —
  removes the ~10% that need flagging.
- Link each space to school data (timetable, capacity, condition) for the BIM "I".

---
`build_spaces.py` is the original pass-1 extractor (area-box approximation), kept for
reference; `build_spaces_v2.py` is the current pipeline.
