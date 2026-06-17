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
(A static server is required — the page fetches `spaces.json`; opening the file
directly via `file://` is blocked by the browser.)

## What you get
- 94 spaces extruded to scale, colour-coded by category (classroom, specialist,
  hall, admin, prayer, store, service, other).
- Click any room → name, area, dimensions, level, finished-floor level.
- Search box, category toggles, label toggle, reset view.

## How it was made (`build_spaces.py` → `spaces.json`)
The PDF is a CAD export: dense vector linework + positioned text labels.
1. **Areas + centres** — each `"xx.xx sqm"` label sits at a room's centroid, giving
   every room its *true area* and *true position* directly from the drawing.
2. **Scale** — calibrated from the classroom grid pitch (stacked identical
   ~58.76 m² rooms are ~90.6 pt apart → **0.0846 m/pt**). Geometric, so it's robust
   to drawing noise.
3. **Footprints** — flood-fill from each centre (walls thickened to seal doorways)
   gives each room's *aspect ratio*; the rectangle is then sized to the exact
   printed area. Where the fill is unreliable, the room falls back to a square of
   the correct area.

Rebuild after changing the source or logic:
```bash
pip install PyMuPDF numpy opencv-python-headless   # one-time
python build_spaces.py
```

## Known limitations (POC)
- Footprints are **area-true rectangles**, not exact wall outlines (L-shapes,
  curves, corridors are approximated). Sizes and adjacencies are faithful.
- A few room **names** carry stray CAD tokens (e.g. trailing `/`); cosmetic.
- Single floor, single phase (Phase 1). Multi-floor needs the other plan sheets.

## Next steps toward a real product
- Stack multiple floors (one `spaces.json` per level) for a whole-building view.
- First-person "walk the corridors" camera mode.
- Exact footprints via the native `.dwg` (room polylines) instead of the PDF.
- Link each space to school data (timetable, capacity, condition) for the BIM "I".
