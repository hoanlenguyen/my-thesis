"""Builds Figure 1.1 (home energy system) as an Excalidraw file and an HTML page that renders it to SVG.

Layout v2 (12 Nov 2026): solar on the left and wind on the right of the smart meter, so no line crosses another.
"""

import json
import sys
from pathlib import Path

OUT = Path(sys.argv[1])
els: list[dict] = []
seed = [1000]


def base(kind: str, eid: str, x: float, y: float, w: float, h: float, **kw) -> dict:
    seed[0] += 7
    e = {"type": kind, "id": eid, "x": x, "y": y, "width": w, "height": h, "angle": 0,
         "strokeColor": kw.pop("stroke", "#1e1e1e"), "backgroundColor": kw.pop("fill", "transparent"),
         "fillStyle": "solid", "strokeWidth": kw.pop("sw", 2), "strokeStyle": kw.pop("style", "solid"),
         "roughness": 1, "opacity": 100, "groupIds": [], "frameId": None, "roundness": kw.pop("round", {"type": 3}),
         "seed": seed[0], "version": 1, "versionNonce": seed[0] + 1, "isDeleted": False,
         "boundElements": [], "updated": 1, "link": None, "locked": False}
    e.update(kw)
    els.append(e)
    return e


def text(eid: str, x: float, y: float, s: str, size: int = 20, w: float | None = None, align: str = "left",
         color: str = "#1e1e1e") -> dict:
    lines = s.split("\n")
    width = w if w is not None else max(len(l) for l in lines) * size * 0.55
    if len(lines) > 1:  # the 0.1.x renderer shifts multi-line text up, so draw one element per line
        out = None
        for i, line in enumerate(lines):
            out = text(f"{eid}_{i}", x, y + i * size * 1.25, line, size, width, align, color)
        return out
    return base("text", eid, x, y, width, size * 1.25, stroke=color, round=None, text=s, originalText=s,
                fontSize=size, fontFamily=1, textAlign=align, verticalAlign="top", containerId=None,
                lineHeight=1.25, baseline=int(size * 0.9), autoResize=True)


def box(eid: str, x: float, y: float, w: float, h: float, label: str, fill: str, size: int = 20,
        stroke: str = "#1e1e1e", style: str = "solid", sw: int = 2) -> None:
    base("rectangle", eid, x, y, w, h, fill=fill, stroke=stroke, style=style, sw=sw)
    th = len(label.split("\n")) * size * 1.25
    text(eid + "_t", x + 12, y + (h - th) / 2, label, size, w - 24, "center")  # free text, centred


def arrow(eid: str, pts: list[tuple[float, float]], color: str, dashed: bool = False, both: bool = False,
          sw: int = 2) -> None:
    x0, y0 = pts[0]
    rel = [[px - x0, py - y0] for px, py in pts]
    xs, ys = [p[0] for p in rel], [p[1] for p in rel]
    base("arrow", eid, x0, y0, max(xs) - min(xs), max(ys) - min(ys), stroke=color, sw=sw,
         style="dashed" if dashed else "solid", round=None, strokeSharpness="sharp", points=rel,
         lastCommittedPoint=None, startBinding=None, endBinding=None,
         startArrowhead="arrow" if both else None, endArrowhead="arrow", elbowed=False)


DC, AC, TWO, COM = "#2f9e44", "#e8590c", "#0c8599", "#c92a2a"

# ── sources, grid and metering: solar left, grid centre, wind right ─────────────────────────────────────────
box("pv", 40, 40, 200, 80, "Solar PV\n(rooftop)", "#fff3bf")
box("pvinv", 40, 180, 200, 90, "Solar inverter", "#e7f5ff")
box("grid", 620, 40, 240, 80, "Public grid", "#e9ecef")
box("meter", 620, 180, 240, 100, "Smart meter", "#e7f5ff")
box("wind", 1100, 40, 200, 80, "Wind turbine\n(small, optional)", "#fff3bf")
box("windinv", 1100, 180, 200, 90, "Wind inverter", "#e7f5ff")

# ── the controller ──────────────────────────────────────────────────────────────────────────────────────────
box("emc", 540, 360, 400, 170,
    "Energy management controller\n= home energy gateway\nruns the HEMS: local small language model,\nMPC, checker, control layer",
    "#c3fae8", 18, stroke="#087f5b", sw=3)

# ── storage and home ────────────────────────────────────────────────────────────────────────────────────────
box("bat", 40, 600, 200, 130, "Home battery\n(with battery\ninverter)", "#d3f9d8")
base("rectangle", "home", 290, 600, 770, 310, fill="#fff9db", stroke="#1e1e1e", sw=2)
text("home_t", 310, 612, "Home and its loads", 20, 300)
devices = ["Heat pump", "Water heater", "Air\nconditioning", "EV charger\nand car",
           "Washing\nmachine", "Dishwasher", "Fridge", "Lighting"]
for i, name in enumerate(devices):
    cx, cy = 310 + (i % 4) * 185, 660 + (i // 4) * 110
    box(f"dev{i}", cx, cy, 170, 90, name, "#ffffff", 18)

# ── household: app (detailed) and voice satellite, over the home Wi-Fi ──────────────────────────────────────
base("rectangle", "zone_house", 1380, 170, 470, 650, fill="#f8f9fa", stroke="#868e96", style="dashed", sw=1)
text("zone_house_t", 1400, 180, "In the household, over the home Wi-Fi", 18, 430, color="#495057")
base("rectangle", "app", 1400, 215, 430, 490, fill="#e5dbff", stroke="#5f3dc4", sw=2)
text("app_t", 1420, 227, "Household app (phone or tablet)", 20, 390, color="#3b2c84")
panels = [
    ("Plans, typed or spoken\n\"car at 80 % by 07:30,\nguests from 18:00\"", 100),
    ("Live view: PV, consumption, battery %,\ngrid import/export, EV, indoor °C", 72),
    ("Today's plan, prices and the\ncommitted requirements", 72),
    ("Savings vs rules, PV used at home", 50),
    ("Questions and messages,\neach with its reason", 72),
]
py = 267
for i, (label, h) in enumerate(panels):
    box(f"panel{i}", 1420, py, 390, h, label, "#ffffff", 16, stroke="#5f3dc4", sw=1)
    py += h + 14
box("sat", 1400, 725, 430, 74, "Voice satellite (optional)\nwake word; speech becomes text on the gateway",
    "#f3f0ff", 16, stroke="#5f3dc4", sw=1)
box("inet", 1380, 845, 470, 110,
    "Internet services\nday-ahead prices · weather forecasts\ncloud LLM (optional fallback)", "#ffd8a8", 18)

# ── power flows ─────────────────────────────────────────────────────────────────────────────────────────────
arrow("p_pv", [(140, 120), (140, 180)], DC)
arrow("p_wind", [(1200, 120), (1200, 180)], DC)
arrow("p_pvinv", [(240, 225), (620, 225)], AC)
arrow("p_windinv", [(1100, 225), (860, 225)], AC)
arrow("p_grid", [(740, 120), (740, 180)], TWO, both=True)
arrow("p_meter", [(690, 280), (690, 360)], TWO, both=True)
arrow("p_home", [(690, 530), (690, 600)], TWO, both=True)
arrow("p_bat", [(140, 600), (140, 470), (540, 470)], TWO, both=True)

# ── communication ───────────────────────────────────────────────────────────────────────────────────────────
arrow("c_meter", [(790, 280), (790, 360)], COM, dashed=True, both=True)
text("c_meter_t", 800, 305, "meter data", 16, 120, color=COM)
arrow("c_pvinv", [(540, 410), (190, 410), (190, 270)], COM, dashed=True, both=True)
text("c_pvinv_t", 260, 385, "Modbus / SunSpec", 16, 200, color=COM)
arrow("c_windinv", [(940, 410), (1150, 410), (1150, 270)], COM, dashed=True, both=True)
text("c_windinv_t", 960, 385, "Modbus / SunSpec", 16, 200, color=COM)
arrow("c_bat", [(540, 505), (210, 505), (210, 600)], COM, dashed=True, both=True)
text("c_bat_t", 260, 510, "battery setpoints", 16, 200, color=COM)
arrow("c_home", [(800, 530), (800, 600)], COM, dashed=True)
text("c_home_t", 810, 548, "device setpoints", 16, 180, color=COM)
arrow("c_app", [(940, 470), (1400, 470)], COM, dashed=True, both=True)
text("c_app_t", 1160, 445, "Wi-Fi, encrypted", 16, 150, color=COM)
arrow("c_inet", [(940, 505), (1320, 505), (1320, 900), (1380, 900)], COM, dashed=True, both=True)
text("c_inet_t", 1000, 512, "prices, forecasts, fallback", 16, 260, color=COM)

# ── legend ──────────────────────────────────────────────────────────────────────────────────────────────────
lx = 40
for eid, label, color, dashed, both in [("l1", "communication", COM, True, True), ("l2", "DC power", DC, False, False),
                                        ("l3", "AC power", AC, False, False),
                                        ("l4", "two-way power flow", TWO, False, True)]:
    arrow(eid, [(lx, 985), (lx + 70, 985)], color, dashed=dashed, both=both)
    text(eid + "_t", lx + 82, 973, label, 18, 200)
    lx += 300

doc = {"type": "excalidraw", "version": 2, "source": "https://excalidraw.com", "elements": els,
       "appState": {"viewBackgroundColor": "#ffffff", "gridSize": None}, "files": {}}
OUT.write_text(json.dumps(doc, indent=1), encoding="utf-8")
html = OUT.with_suffix(".html")
html.write_text(f"""<!doctype html><html><head><meta charset="utf-8"><style>body{{margin:0;background:#fff}}
svg{{display:block}}</style></head><body><div id="o">rendering…</div>
<script src="https://cdn.jsdelivr.net/npm/@excalidraw/utils@0.1.2/dist/excalidraw-utils.min.js"></script>
<script>const scene={json.dumps(doc)};
ExcalidrawUtils.exportToSvg({{elements:scene.elements,appState:{{...scene.appState,exportBackground:true,exportWithDarkMode:false}},files:{{}},exportPadding:20}})
.then(svg=>{{const o=document.getElementById('o');o.innerHTML='';svg.setAttribute('id','fig');o.appendChild(svg);document.title='done';}})
.catch(e=>{{document.getElementById('o').textContent='ERROR '+e;}});</script></body></html>""", encoding="utf-8")
print("wrote", OUT, html, len(els), "elements")
