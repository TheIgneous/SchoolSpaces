"""
Pass 2: extract real room FOOTPRINTS from FP-202 (replaces area-box guessing).

Method
  1. Read area labels -> each room's TRUE area + name + seed point (as pass 1).
  2. Isolate WALLS from furniture by segment LENGTH (walls are long lines;
     furniture/fixtures are short) on the thin black linework band.
  3. Seed circulation: large free regions far from any room label become their
     own "Corridor" markers, so rooms stop absorbing them.
  4. Marker-based WATERSHED -> a non-overlapping tiling of the floor. Overlaps
     are impossible by construction; shape + orientation are taken from the plan.
  5. Polygonise each basin (contour -> simplify), convert px->metres.
  6. QA against printed areas: flag any room off by >LEAK/SHRINK tolerance and
     fall back to an oriented area-true box so nothing is silently wrong.

Outputs: spaces_v2.json, qa_overlay.png, and a printed QA summary.
"""
import re, json
import fitz, numpy as np, cv2

PDF   = r"C:/Users/7600k/Downloads/FP202- First Floor Plan-FP-202 5.pdf"
ZOOM  = 2.0
LMIN  = 28          # min wall-segment length (px) — drops furniture
CLOSE = 3           # wall morphological close (seal hairline gaps)
M_PER_PT = 0.08462  # calibrated in pass 1 (classroom grid pitch)
M_PER_PX = M_PER_PT / ZOOM
HI, LO = 1.45, 0.65 # area-ratio tolerance band before a room is flagged

doc = fitz.open(PDF); page = doc[0]; page.set_rotation(0)
words = page.get_text("words"); dr = page.get_drawings()
def cx(w): return (w[0]+w[2])/2
def cy(w): return (w[1]+w[3])/2
def wclass(d): return round((d.get("width") or 0), 2)

# ---- 1. seeds: area + position + name --------------------------------------
num_re = re.compile(r'^\d{1,4}(?:\.\d+)?$')
seeds = []
for s in words:
    if 'sqm' not in s[4].lower(): continue
    cands = [w for w in words if num_re.match(w[4]) and abs(cx(w)-cx(s))<30
             and -16 < (cy(w)-cy(s)) < 3 and 3 <= float(w[4]) <= 3000]
    if not cands: continue
    v = min(cands, key=lambda w: abs(cx(w)-cx(s))+abs(cy(w)-cy(s)))
    seeds.append({"area": float(v[4]), "x": cx(s), "y": cy(s)})
uniq = []
for s in seeds:
    if any(abs(s["x"]-o["x"])<8 and abs(s["y"]-o["y"])<8 for o in uniq): continue
    uniq.append(s)
seeds = uniq

NOISE = set("AC IWB FHC MV SD-1 SD-2 SD-3 UP DN sqm sqm. SSL: FFL: GP-05 B".split())
def is_noise(t):
    if re.match(r'^\d+-\d+$', t) or re.match(r'^\d+[A-Z]$', t): return False
    if t in NOISE: return True
    if len(t) < 2: return True
    if re.match(r'^[\d\.\:\=\-/]+$', t): return True
    if re.match(r'^W\d+$', t) or re.match(r'^SD-\d', t) or re.match(r'^CW\d+$', t): return True
    if re.match(r'^\d+R$', t) or re.match(r'^[RT]=\d+$', t): return True
    if t in ("BLOCK","R=150","T=300","SSL","FFL","FSFSLL::44.8.70500"): return True
    return False
def name_for(s):
    near = [w for w in words if 8 < (cx(w)-s["x"]) < 70 and -36 < (cy(w)-s["y"]) < 12
            and not is_noise(w[4])]
    near.sort(key=lambda w: (round(cy(w)), cx(w)))
    out = []
    for w in near:
        t = w[4].strip().rstrip('/')
        if t and t not in out: out.append(t)
    return " ".join(out[:4]) or "Room"
def categorise(area, name):
    n = name.upper()
    if "CORRIDOR" in n or "CIRCULATION" in n: return "circulation"
    if "YEAR" in n: return "classroom"
    if any(k in n for k in ("STORE","KILN")): return "store"
    if any(k in n for k in ("ART","SCIENCE","LAB","MUSIC","LIBRARY")): return "specialist"
    if any(k in n for k in ("STAFF","OFFICE","LOUNGE","ADMIN","RECEPTION")): return "admin"
    if any(k in n for k in ("PRAYER","ABLUTION")): return "prayer"
    if any(k in n for k in ("IDF","ELECTRICAL","JANITOR","PUMP","DATA","RISER")): return "service"
    if "TOILET" in n or "WC" in n or area <= 8: return "service"
    if area >= 150: return "hall"
    if 54 <= area <= 65: return "classroom"
    return "other"

# ---- geometry frame ---------------------------------------------------------
xs=[s["x"] for s in seeds]; ys=[s["y"] for s in seeds]
x0,x1=min(xs)-60,max(xs)+60; y0,y1=min(ys)-60,max(ys)+60
W=int((x1-x0)*ZOOM); H=int((y1-y0)*ZOOM)
def topx(p): return (int((p.x-x0)*ZOOM), int((p.y-y0)*ZOOM))
def sx(s):   return (int((s["x"]-x0)*ZOOM), int((s["y"]-y0)*ZOOM))

# ---- 2. walls (length-filtered thin black linework) -------------------------
line = np.full((H,W),255,np.uint8)
for d in dr:
    if wclass(d) > 0.45: continue
    col = d.get("color") or (0,0,0)
    if col[2] > 0.6 and col[0] < 0.3: continue          # drop blue grid
    for it in d["items"]:
        if it[0]=="l":
            a,b=topx(it[1]),topx(it[2])
            if (a[0]-b[0])**2+(a[1]-b[1])**2 >= LMIN*LMIN: cv2.line(line,a,b,0,1)
        elif it[0]=="re":
            cv2.rectangle(line,topx(it[1].tl),topx(it[1].br),0,1)
walls = cv2.morphologyEx((line<128).astype(np.uint8), cv2.MORPH_CLOSE, np.ones((CLOSE,CLOSE),np.uint8))
free  = (1-walls).astype(np.uint8)

# ---- 3. circulation seeds: only LARGE, ELONGATED free runs (the spines) -----
seedpts = np.ones((H,W),np.uint8)
for s in seeds: seedpts[sx(s)[1], sx(s)[0]] = 0
dist_seed = cv2.distanceTransform(seedpts, cv2.DIST_L2, 5)
dist_wall = cv2.distanceTransform(free, cv2.DIST_L2, 5)
FAR = 4.0/M_PER_PX                        # >4 m from any room label
corridor = ((free>0) & (dist_seed>FAR) & (dist_wall>3)).astype(np.uint8)
ncc, lab, stats, cents = cv2.connectedComponentsWithStats(corridor, 8)
corr_seeds=[]
for k in range(1, ncc):
    if stats[k, cv2.CC_STAT_AREA] < (3.0/M_PER_PX)**2: continue
    ys2,xs2 = np.where(lab==k)
    (_,_),(rw,rh),_ = cv2.minAreaRect(np.column_stack([xs2,ys2]).astype(np.int32))
    major = max(rw,rh)*M_PER_PX
    if major > 9.0:                       # elongated >9 m -> a real corridor/spine
        corr_seeds.append((int(cents[k][0]), int(cents[k][1])))

# ---- 4. watershed -----------------------------------------------------------
markers = np.zeros((H,W),np.int32)
markers[0:3,:]=1; markers[-3:,:]=1; markers[:,0:3]=1; markers[:,-3:]=1
N = len(seeds)
for i,s in enumerate(seeds):
    px,py = sx(s)
    if free[py,px]==0:                                   # nudge off a wall
        d=False
        for r in range(1,15):
            for dy in range(-r,r+1):
                for dx in range(-r,r+1):
                    if 0<=py+dy<H and 0<=px+dx<W and free[py+dy,px+dx]: px,py=px+dx,py+dy; d=True; break
                if d: break
            if d: break
    cv2.circle(markers,(px,py),3,i+2,-1)
for j,(px,py) in enumerate(corr_seeds):
    cv2.circle(markers,(px,py),3,N+2+j,-1)
cv2.watershed(cv2.cvtColor((255-walls*255).astype(np.uint8),cv2.COLOR_GRAY2BGR), markers)

# ---- 5/6. polygonise + QA ---------------------------------------------------
def basin_polygon(idv):
    m=(markers==idv).astype(np.uint8)
    if m.sum()==0: return None,0
    cnts,_=cv2.findContours(m,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    if not cnts: return None,0
    c=max(cnts,key=cv2.contourArea)
    area_px=cv2.contourArea(c)
    eps=0.30/M_PER_PX                                    # 0.30 m simplify
    poly=cv2.approxPolyDP(c,eps,True).reshape(-1,2)
    return poly, area_px

def capped_grow(idv, seedpx, target_px):
    """grow a compact region from the seed, confined to the room's own basin,
    until it reaches the printed area. Stays inside the basin -> never overlaps."""
    ys,xs = np.where(markers==idv)
    if len(xs)==0: return None
    bx0,bx1,by0,by1 = xs.min(),xs.max(),ys.min(),ys.max()
    sub = (markers[by0:by1+1, bx0:bx1+1]==idv).astype(np.uint8)
    g = np.zeros_like(sub)
    spx,spy = seedpx[0]-bx0, seedpx[1]-by0
    if not (0<=spy<sub.shape[0] and 0<=spx<sub.shape[1] and sub[spy,spx]):
        spy,spx = ys[0]-by0, xs[0]-bx0
    g[spy,spx]=1
    k=np.ones((3,3),np.uint8); prev=-1
    for _ in range(4000):
        g = cv2.dilate(g,k) & sub
        c=int(g.sum())
        if c>=target_px or c==prev: break
        prev=c
    cnts,_=cv2.findContours(g,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    if not cnts: return None
    c=max(cnts,key=cv2.contourArea); c[:,:,0]+=bx0; c[:,:,1]+=by0
    return cv2.approxPolyDP(c,0.30/M_PER_PX,True).reshape(-1,2)

spaces=[]; flagged=0
for i,s in enumerate(seeds):
    poly,area_px = basin_polygon(i+2)
    meas = area_px*M_PER_PX*M_PER_PX if poly is not None else 0
    ratio = meas/s["area"] if (s["area"] and poly is not None) else 0
    flag = not (LO < ratio < HI)
    if flag:                                             # trim/grow to true area, in-basin
        tgt = s["area"]/(M_PER_PX*M_PER_PX)
        gp = capped_grow(i+2, sx(s), tgt)
        if gp is not None and len(gp)>=3:
            poly = gp; meas = cv2.contourArea(np.array(poly))*M_PER_PX*M_PER_PX
        flagged += 1
    if poly is None or len(poly)<3: continue
    name = name_for(s)
    pm = [[round((px*1.0)*M_PER_PX,2), round((py*1.0)*M_PER_PX,2)] for px,py in poly]
    spaces.append({"id":i,"name":name,"area":round(s["area"],2),
                   "measured":round(meas,1),"category":categorise(s["area"],name),
                   "flagged":bool(flag),"poly":pm})

# circulation spaces (no printed area -> never flagged)
for j,(px,py) in enumerate(corr_seeds):
    poly,area_px = basin_polygon(N+2+j)
    if poly is None or len(poly)<3: continue
    meas=area_px*M_PER_PX*M_PER_PX
    if meas < 6: continue
    pm=[[round(px*M_PER_PX,2),round(py*M_PER_PX,2)] for px,py in poly]
    spaces.append({"id":1000+j,"name":"Circulation","area":round(meas,1),
                   "measured":round(meas,1),"category":"circulation","flagged":False,"poly":pm})

# normalise origin
allx=[p[0] for s in spaces for p in s["poly"]]; ally=[p[1] for s in spaces for p in s["poly"]]
mnx,mny=min(allx),min(ally)
for s in spaces:
    s["poly"]=[[round(p[0]-mnx,2),round(p[1]-mny,2)] for p in s["poly"]]
    cxs=[p[0] for p in s["poly"]]; cys=[p[1] for p in s["poly"]]
    s["centroid"]=[round(sum(cxs)/len(cxs),2),round(sum(cys)/len(cys),2)]
EX=round(max(p[0] for s in spaces for p in s["poly"]),1)
EY=round(max(p[1] for s in spaces for p in s["poly"]),1)

out={"source":"FP-202 First Floor Plan","level":"First Floor","ffl":4.800,
     "floor_height":3.5,"units":"metres","scale_m_per_px":round(M_PER_PX,5),
     "extent":[EX,EY],"count":len(spaces),"spaces":spaces}
json.dump(out, open("spaces_v2.json","w"), indent=1)
with open("spaces-data.js","w") as f: f.write("window.SPACES = "+json.dumps(out)+";\n")

# QA overlay: polygons over the plan linework
base=cv2.cvtColor((255-walls*255).astype(np.uint8),cv2.COLOR_GRAY2BGR)
for s in spaces:
    pts=np.array([[int(p[0]/M_PER_PX+mnx),int(p[1]/M_PER_PX+mny)] for p in s["poly"]],np.int32)
    col=(0,0,255) if s["flagged"] else (0,170,0) if s["category"]!="circulation" else (200,140,0)
    cv2.polylines(base,[pts],True,col,2)
cv2.imwrite("qa_overlay.png", cv2.resize(base,(W//2,H//2),interpolation=cv2.INTER_AREA))

rooms=[s for s in spaces if s["category"]!="circulation"]
print(f"rooms={len(rooms)}  circulation={len(spaces)-len(rooms)}  corridor_seeds={len(corr_seeds)}")
print(f"good footprints={len(rooms)-flagged}/{len(rooms)}  flagged(->oriented box)={flagged}")
print(f"extent {EX} x {EY} m ; wrote spaces_v2.json, spaces-data.js, qa_overlay.png")
