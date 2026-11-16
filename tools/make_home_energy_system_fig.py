"""Builds Figure 1.1 (home energy system) as a clean SVG and an HTML page that shows it at its exact size.

Layout v3 (16 Nov 2026): flat style (no hand-drawn look), Arial; solar and wind both on the left, each above its
inverter; the loads box is "Smart loads"; no protocol names on the inverter links.
Render to PNG with headless Chrome (see render() below):
    uv run python tools/make_home_energy_system_fig.py attachments/gateway/home_energy_system
"""

import shutil
import subprocess
import sys
from pathlib import Path
from xml.sax.saxutils import escape

W, H = 1720, 1010
FONT = "Arial, Helvetica, sans-serif"
DC, AC, TWO, COM = "#2f9e44", "#d9480f", "#0b7285", "#c92a2a"
INK, MUTED = "#1f2933", "#52606d"
# fill, stroke per kind of element
KIND = {
    "source": ("#fff4cc", "#b08900"),
    "convert": ("#e7f1fb", "#3a6ea5"),
    "grid": ("#eef0f2", "#6b7785"),
    "control": ("#dcf5ea", "#1b7f5b"),
    "storage": ("#e3f6e5", "#2f7d3b"),
    "load": ("#ffffff", "#7b8794"),
    "group": ("#fbf8ec", "#a39e8a"),
    "app": ("#efe9ff", "#5f3dc4"),
    "panel": ("#ffffff", "#8c74d6"),
    "net": ("#ffe8cc", "#c2610c"),
}
edges: list[str] = []
nodes: list[str] = []
labels: list[str] = []


def txt(x: float, y: float, s: str, size: float = 18, weight: int = 400, color: str = INK,
        anchor: str = "middle", into: list[str] | None = None) -> None:
    (labels if into is None else into).append(
        f'<text x="{x:.0f}" y="{y:.0f}" font-size="{size}" font-weight="{weight}" fill="{color}" '
        f'text-anchor="{anchor}">{escape(s)}</text>')


def box(x: float, y: float, w: float, h: float, label: str, kind: str, size: float = 20, weight: int = 600,
        sw: float = 1.5, sub: str = "", sub_size: float = 16) -> None:
    fill, stroke = KIND[kind]
    nodes.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="{fill}" stroke="{stroke}" '
                 f'stroke-width="{sw}"/>')
    lines = [(l, size, weight, INK) for l in label.split("\n") if l]
    lines += [(l, sub_size, 400, MUTED) for l in sub.split("\n") if l]
    gap = 1.3
    total = sum(s * gap for _, s, _, _ in lines)
    cy = y + (h - total) / 2
    for line, s, wt, col in lines:
        cy += s * gap
        txt(x + w / 2, cy - s * 0.3, line, s, wt, col, into=nodes)


def arrow(pts: list[tuple[float, float]], color: str, dashed: bool = False, both: bool = False) -> None:
    d = "M" + " L".join(f"{x:.0f},{y:.0f}" for x, y in pts)
    mid = {DC: "dc", AC: "ac", TWO: "two", COM: "com"}[color]
    dash = ' stroke-dasharray="7 5"' if dashed else ""
    start = f' marker-start="url(#{mid})"' if both else ""
    edges.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="2.2"{dash}{start} '
                 f'marker-end="url(#{mid})"/>')


def lbl(x: float, y: float, s: str, anchor: str = "start") -> None:
    txt(x, y, s, 16, 400, COM, anchor)


# ── generation on the left: solar above wind, each above its inverter ────────────────────────────────────────
box(40, 40, 230, 70, "Solar PV", "source", sub="rooftop")
box(40, 150, 230, 70, "Solar inverter", "convert")
box(40, 270, 230, 70, "Wind turbine", "source", sub="small, optional")
box(40, 380, 230, 70, "Wind inverter", "convert")
box(40, 640, 230, 120, "Home battery", "storage", sub="with battery inverter")

# ── grid, meter, controller ───────────────────────────────────────────────────────────────────────────────────
box(620, 40, 260, 70, "Public grid", "grid")
box(620, 150, 260, 100, "Smart meter", "convert")
box(540, 330, 420, 210, "Energy management controller", "control", size=21, sw=2.5,
    sub="= home energy gateway\nruns the HEMS: local small language model,\nMPC, checker and control layer",
    sub_size=17)

# ── smart loads ───────────────────────────────────────────────────────────────────────────────────────────────
fill, stroke = KIND["group"]
nodes.append(f'<rect x="300" y="620" width="790" height="270" rx="10" fill="{fill}" stroke="{stroke}" '
             f'stroke-width="1.5"/>')
txt(322, 652, "Smart loads", 20, 700, INK, "start", into=nodes)
devices = ["Heat pump", "Water heater", "Air\nconditioning", "EV charger\nand car",
           "Washing\nmachine", "Dishwasher", "Smart\nthermostats", "Smart\nlight bulbs"]
for i, name in enumerate(devices):
    box(322 + (i % 4) * 190, 672 + (i // 4) * 104, 176, 90, name, "load", size=18, weight=400, sw=1.2)

# ── household: app and voice satellite, over the home Wi-Fi; internet services ────────────────────────────────
nodes.append('<rect x="1200" y="140" width="480" height="620" rx="10" fill="#f8f9fa" stroke="#8a94a0" '
             'stroke-width="1.3" stroke-dasharray="7 5"/>')
txt(1220, 170, "In the household, over the home Wi-Fi", 17, 400, MUTED, "start", into=nodes)
fill, stroke = KIND["app"]
nodes.append(f'<rect x="1220" y="186" width="440" height="470" rx="8" fill="{fill}" stroke="{stroke}" '
             f'stroke-width="1.8"/>')
txt(1240, 216, "Household app (phone or tablet)", 19, 700, "#3b2c84", "start", into=nodes)
py = 232
for label, h in [("Plans, typed or spoken\n\u201ccar at 80 % by 07:30,\nguests from 18:00\u201d", 92),
                 ("Live view: PV, consumption, battery %,\ngrid import/export, EV, indoor \u00b0C", 68),
                 ("Today\u2019s plan, prices and the\ncommitted requirements", 68),
                 ("Savings vs rules, PV used at home", 50),
                 ("Questions and messages,\neach with its reason", 68)]:
    box(1240, py, 400, h, label, "panel", size=16, weight=400, sw=1)
    py += h + 12
box(1220, 672, 440, 72, "Voice satellite (optional)", "panel", size=17, weight=600, sw=1.2,
    sub="wake word; speech becomes text on the gateway", sub_size=15)
box(1200, 790, 480, 110, "Internet services", "net", size=20,
    sub="day-ahead prices \u00b7 weather forecasts\ncloud LLM (optional fallback)", sub_size=17)

# ── power flows ───────────────────────────────────────────────────────────────────────────────────────────────
arrow([(155, 110), (155, 148)], DC)
arrow([(155, 340), (155, 378)], DC)
arrow([(270, 185), (618, 185)], AC)
arrow([(270, 400), (460, 400), (460, 225), (618, 225)], AC)
arrow([(750, 110), (750, 148)], TWO, both=True)
arrow([(700, 250), (700, 328)], TWO, both=True)
arrow([(700, 540), (700, 618)], TWO, both=True)
arrow([(120, 640), (120, 480), (538, 480)], TWO, both=True)

# ── communication ─────────────────────────────────────────────────────────────────────────────────────────────
arrow([(820, 250), (820, 328)], COM, dashed=True, both=True)
lbl(832, 295, "meter data")
arrow([(40, 205), (20, 205), (20, 455), (538, 455)], COM, dashed=True, both=True)
arrow([(270, 430), (538, 430)], COM, dashed=True, both=True)
arrow([(205, 640), (205, 515), (538, 515)], COM, dashed=True, both=True)
lbl(300, 508, "battery setpoints")
arrow([(820, 540), (820, 618)], COM, dashed=True)
lbl(832, 585, "device setpoints")
arrow([(960, 400), (1198, 400)], COM, dashed=True, both=True)
lbl(1080, 390, "Wi-Fi, encrypted", "middle")
arrow([(960, 500), (1150, 500), (1150, 845), (1198, 845)], COM, dashed=True, both=True)
lbl(975, 492, "prices, forecasts, fallback")

# ── legend ────────────────────────────────────────────────────────────────────────────────────────────────────
lx = 40
for name, color, dashed, both in [("communication", COM, True, True), ("DC power", DC, False, False),
                                  ("AC power", AC, False, False), ("two-way power flow", TWO, False, True)]:
    arrow([(lx, 965), (lx + 60, 965)], color, dashed, both)
    txt(lx + 74, 971, name, 17, 400, INK, "start")
    lx += 290

markers = "".join(
    f'<marker id="{m}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5.5" markerHeight="5.5" '
    f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{c}"/></marker>'
    for m, c in [("dc", DC), ("ac", AC), ("two", TWO), ("com", COM)])
svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
       f'font-family="{FONT}" role="img" aria-label="A home energy system: solar PV and a small wind turbine '
       f'feed inverters, the inverters and the grid meet at the smart meter, and the energy management controller '
       f'(the home energy gateway) reads the meter and inverters, sets the battery and the smart loads, talks to the '
       f'household app over the home Wi-Fi and gets prices and forecasts from the internet.">'
       f'<defs>{markers}</defs><rect width="{W}" height="{H}" fill="#ffffff"/>'
       + "".join(edges) + "".join(nodes) + "".join(labels) + "</svg>")


def render(svg_path: Path, png_path: Path) -> None:
    html = svg_path.with_suffix(".html")
    html.write_text(f'<!doctype html><html><head><meta charset="utf-8"><style>html,body{{margin:0;'
                    f'background:#fff}}svg{{display:block}}</style></head><body>{svg}</body></html>',
                    encoding="utf-8")
    chrome = next(p for p in [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                              r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                              shutil.which("chrome") or ""] if p and Path(p).exists())
    subprocess.run([chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--window-size={W},{H}",
                    "--force-device-scale-factor=2", f"--screenshot={png_path.resolve()}", html.resolve().as_uri()],
                   check=True, capture_output=True)


if __name__ == "__main__":
    out = Path(sys.argv[1])
    out.with_suffix(".svg").write_text(svg, encoding="utf-8")
    render(out.with_suffix(".svg"), out.with_suffix(".png"))
    print("wrote", out.with_suffix(".svg"), out.with_suffix(".png"))
