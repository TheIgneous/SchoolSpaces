"""
Extract school spaces from the FP-202 floor-plan PDF into spaces.json.

Pipeline:
  1. Read positioned text -> area labels ("xx.xx sqm") give each room's TRUE area
     and TRUE centre (the label sits at the room centroid).
  2. Rasterise the sheet, flood-fill outward from each centre with walls slightly
     thickened to seal door gaps -> gives a footprint *bounding box* (aspect ratio).
  3. Self-calibrate scale (m per pixel) from the 35 identical ~58.76 sqm classrooms.
  4. Emit each room as an area-true rectangle: size from the printed area, aspect
     from the flood-fill when trustworthy (else square), centre from the label.

Sizes and relative positions are faithful; exact wall outlines are not modelled
(by design - this is a space massing POC, not a full BIM).
"""
import re, json
import fitz, numpy as np, cv2

PDF = r"C:/Users/7600k/Downloads/FP202- First Floor Plan-FP-202 5.pdf"
ZOOM = 2.0
SEAL = 2  # wall-thickening iterations to seal doorways

doc = fitz.open(PDF)
page = doc[0]
page.set_rotation(0)
words = page.get_text("words")  # (x0,y0,x1,y1, text, block,line,word)

def cx(w): return (w[0] + w[2]) / 2
def cy(w): return (w[1] + w[3]) / 2

# --- 1. area-label seeds: number sits directly above the "sqm" token ----------
num_re = re.compile(r'^\d{1,4}(?:\.\d+)?$')
seeds = []
for s in words:
    if 'sqm' not in s[4].lower():
        continue
    cands = [w for w in words if num_re.match(w[4])
             and abs(cx(w) - cx(s)) < 30 and -16 < (cy(w) - cy(s)) < 3
             and 3 <= float(w[4]) <= 3000]
    if not cands:
        continue
    val = min(cands, key=lambda w: abs(cx(w) - cx(s)) + abs(cy(w) - cy(s)))
    seeds.append({"area": float(val[4]), "x": cx(s), "y": cy(s)})

# dedupe near-identical points
uniq = []
for s in seeds:
    if any(abs(s["x"] - o["x"]) < 8 and abs(s["y"] - o["y"]) < 8 for o in uniq):
        continue
    uniq.append(s)
seeds = uniq

# --- 2. raster + flood fill ---------------------------------------------------
pm = page.get_pixmap(matrix=fitz.Matrix(ZOOM, ZOOM), colorspace=fitz.csGRAY)
img = np.frombuffer(pm.samples, dtype=np.uint8).reshape(pm.height, pm.width)
H, W = img.shape
barrier = (img <= 200).astype(np.uint8)
barrier = cv2.dilate(barrier, np.ones((3, 3), np.uint8), iterations=SEAL)
free = (1 - barrier).astype(np.uint8)

def nudge(px, py):
    if free[py, px]:
        return px, py
    for r in range(1, 12):
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                yy, xx = py + dy, px + dx
                if 0 <= yy < H and 0 <= xx < W and free[yy, xx]:
                    return xx, yy
    return px, py

def fill(px, py):
    m = np.zeros((H + 2, W + 2), np.uint8)
    cv2.floodFill(free.copy(), m, (px, py), 1, flags=8 | (1 << 8))
    mask = m[1:-1, 1:-1]
    pix = int(mask.sum())
    ys, xs = np.where(mask > 0)
    if pix == 0:
        return pix, 0, 0
    return pix, (xs.max() - xs.min() + 1), (ys.max() - ys.min() + 1)

for s in seeds:
    px, py = nudge(int(s["x"] * ZOOM), int(s["y"] * ZOOM))
    s["pix"], s["bw"], s["bh"] = fill(px, py)

# --- 3. calibrate scale from the classroom grid pitch ------------------------
# 35 identical ~58.76 sqm classrooms are stacked in vertical columns (blocks).
# Their label centres are spaced one room-depth apart; a 58.76 sqm room is
# ~square, so depth ~= sqrt(area). pitch(pt) <-> sqrt(area)(m) gives the scale.
# This geometric ruler is robust to flood-fill noise (used only for aspect below).
ref = [s for s in seeds if abs(s["area"] - 58.76) < 0.2]
cols = []
for s in sorted(ref, key=lambda s: s["x"]):
    for c in cols:
        if abs(c[0]["x"] - s["x"]) < 40:
            c.append(s); break
    else:
        cols.append([s])
pitches = []
for c in cols:
    ys = sorted(s["y"] for s in c)
    pitches += [b - a for a, b in zip(ys, ys[1:]) if 40 < b - a < 200]
pitches.sort()
pitch_pt = pitches[len(pitches) // 2]                 # median room pitch (pt)
M_PER_PT = (58.76 ** 0.5) / pitch_pt
M_PER_PX = M_PER_PT / ZOOM
m2_per_px = M_PER_PX ** 2
print(f"calibration: pitch={pitch_pt:.1f}pt across {len(cols)} columns "
      f"-> {M_PER_PT:.5f} m/pt ({M_PER_PX*1000:.1f} mm/px)")

# --- 4. name extraction -------------------------------------------------------
NOISE = set("AC IWB FHC MV SD-1 SD-2 SD-3 UP DN sqm sqm. SSL: FFL: GP-05 B".split())
def is_noise(t):
    if re.match(r'^\d+-\d+$', t) or re.match(r'^\d+[A-Z]$', t): return False  # "5-5","6A"
    if t in NOISE: return True
    if len(t) < 2: return True
    if re.match(r'^[\d\.\:\=\-/]+$', t): return True
    if re.match(r'^W\d+$', t): return True
    if re.match(r'^SD-\d', t): return True
    if re.match(r'^CW\d+$', t): return True
    if re.match(r'^\d+R$', t) or re.match(r'^[RT]=\d+$', t): return True
    if t in ("BLOCK", "R=150", "T=300", "SSL", "FFL", "FSFSLL::44.8.70500"): return True
    return False

def name_for(s):
    near = [w for w in words
            if 8 < (cx(w) - s["x"]) < 70 and -36 < (cy(w) - s["y"]) < 12
            and not is_noise(w[4])]
    near.sort(key=lambda w: (round(cy(w)), cx(w)))
    out = []
    for w in near:
        t = w[4].strip()
        if t and t not in out:
            out.append(t)
    return " ".join(out[:4])

def categorise(area, name):
    n = name.upper()
    if "YEAR" in n: return "classroom"
    if any(k in n for k in ("STORE", "KILN")): return "store"
    if any(k in n for k in ("ART", "SCIENCE", "LAB", "MUSIC", "LIBRARY")): return "specialist"
    if any(k in n for k in ("STAFF", "OFFICE", "LOUNGE", "ADMIN", "RECEPTION")): return "admin"
    if any(k in n for k in ("PRAYER", "ABLUTION")): return "prayer"
    if any(k in n for k in ("IDF", "ELECTRICAL", "JANITOR", "PUMP", "MV", "DATA", "RISER")): return "service"
    if "TOILET" in n or "WC" in n or area <= 8: return "service"
    if area >= 150: return "hall"
    if 54 <= area <= 65: return "classroom"
    return "other"

# --- 5. assemble area-true rectangles ----------------------------------------
spaces = []
for i, s in enumerate(seeds):
    aspect = 1.0
    if s["pix"] > 0:
        fill_m2 = s["pix"] * m2_per_px
        if 0.5 <= fill_m2 / s["area"] <= 1.7 and s["bh"] > 0:
            aspect = max(0.35, min(2.8, s["bw"] / s["bh"]))
    a = s["area"]
    width = (a * aspect) ** 0.5
    depth = (a / aspect) ** 0.5
    name = name_for(s) or "Room"
    spaces.append({
        "id": i,
        "name": name,
        "area": round(a, 2),
        "category": categorise(a, name),
        "cx": round(s["x"] * M_PER_PT, 2),    # metres, PDF x
        "cy": round(s["y"] * M_PER_PT, 2),    # metres, PDF y (down)
        "w": round(width, 2),
        "d": round(depth, 2),
    })

# normalise origin to plan min corner
minx = min(s["cx"] - s["w"] / 2 for s in spaces)
miny = min(s["cy"] - s["d"] / 2 for s in spaces)
for s in spaces:
    s["cx"] = round(s["cx"] - minx, 2)
    s["cy"] = round(s["cy"] - miny, 2)

extent_x = round(max(s["cx"] + s["w"] / 2 for s in spaces), 1)
extent_y = round(max(s["cy"] + s["d"] / 2 for s in spaces), 1)

out = {
    "source": "FP-202 First Floor Plan",
    "level": "First Floor",
    "ffl": 4.800,
    "floor_height": 3.5,
    "units": "metres",
    "scale_m_per_px": round(M_PER_PX, 5),
    "extent": [extent_x, extent_y],
    "count": len(spaces),
    "spaces": spaces,
}
json.dump(out, open("spaces.json", "w"), indent=1)
# also embed as a plain <script> so index.html works by double-click (no server)
with open("spaces-data.js", "w") as f:
    f.write("window.SPACES = " + json.dumps(out) + ";\n")
print(f"wrote spaces.json + spaces-data.js: {len(spaces)} spaces, extent {extent_x} x {extent_y} m")
from collections import Counter
print("categories:", dict(Counter(s["category"] for s in spaces)))
print("sample:")
for s in spaces[:8]:
    print(f"  {s['name'][:28]:28} {s['area']:7.2f}m2  {s['w']:.1f}x{s['d']:.1f}  @({s['cx']:.1f},{s['cy']:.1f})")
