"""Builds Figure 1.1 (home energy system) as a clean SVG and an HTML page that shows it at its exact size.

Layout v3 (16 Nov 2026): flat style (no hand-drawn look), Arial; solar and wind both on the left, each above its
inverter; the loads box is "Smart loads"; no protocol names on the inverter links.
Wiring v4 (16 Nov 2026): power meets at a distribution board (the home's AC bus) and never passes through the
controller; DC only panels -> solar inverter and battery <-> battery inverter; the wind turbine delivers AC to a
rectifier and inverter; colour says AC or DC, two arrowheads say the power flows both ways.
Wiring v5 (16 Nov 2026): one hybrid inverter with solar, wind (through a rectifier) and the battery on its DC
side, as hybrid inverters are built; AC lines are blue.
Two variants on the same diagram (16 Nov 2026): Figure 1.1 is a generic home energy system (one app box, one
internet box, the controller by name only); Figure 1.2 (--thesis) adds what this thesis puts into it: the small
language model in the controller, the household app's panels, the voice satellite and the cloud fallback.
Render to PNG with headless Chrome (see render() below):
    uv run python tools/make_home_energy_system_fig.py attachments/gateway/home_energy_system
    uv run python tools/make_home_energy_system_fig.py --thesis attachments/gateway/home_energy_system_slm
"""

import shutil
import subprocess
import sys
from pathlib import Path
from xml.sax.saxutils import escape

THESIS = "--thesis" in sys.argv  # Figure 1.2: the same system with the thesis's additions
W, H = (1720 if THESIS else 1420), 1010
FONT = "Arial, Helvetica, sans-serif"
DC, AC, TWO, COM = "#2f9e44", "#1971c2", "#0b7285", "#c92a2a"  # AC is blue so it differs from the red dashes
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
        sw: float = 1.5, sub: str = "", sub_size: float = 16, dashed: bool = False) -> None:
    fill, stroke = KIND[kind]
    dash = ' stroke-dasharray="8 5"' if dashed else ""
    nodes.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="{fill}" stroke="{stroke}" '
                 f'stroke-width="{sw}"{dash}/>')
    lines = [(l, size, weight, INK) for l in label.split("\n") if l]
    lines += [(l, sub_size, 400, MUTED) for l in sub.split("\n") if l]
    gap = 1.3
    total = sum(s * gap for _, s, _, _ in lines)
    cy = y + (h - total) / 2
    for line, s, wt, col in lines:
        cy += s * gap
        txt(x + w / 2, cy - s * 0.3, line, s, wt, col, into=nodes)


def arrow(pts: list[tuple[float, float]], color: str, dashed: bool = False, both: bool = False,
          top: bool = False) -> None:
    """top=True draws the arrow over the boxes (for links that end inside the controller group)."""
    d = "M" + " L".join(f"{x:.0f},{y:.0f}" for x, y in pts)
    mid = {DC: "dc", AC: "ac", TWO: "two", COM: "com"}[color]
    dash = ' stroke-dasharray="7 5"' if dashed else ""
    start = f' marker-start="url(#{mid})"' if both else ""
    (labels if top else edges).append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="2.2"{dash}{start} '
                 f'marker-end="url(#{mid})"/>')


def lbl(x: float, y: float, s: str, anchor: str = "start") -> None:
    txt(x, y, s, 16, 400, COM, anchor)


# ── generation and storage on the left: solar, wind and the battery share one hybrid inverter ────────────────
box(30, 40, 125, 90, "Solar PV", "source", size=18, sub="rooftop", sub_size=14)
box(165, 40, 125, 90, "Wind turbine", "source", size=18, sub="small, optional\nwith rectifier", sub_size=14)
box(30, 200, 260, 80, "Hybrid inverter", "convert", sub="DC inputs: solar, wind, battery")
box(30, 430, 260, 90, "Home battery", "storage")

# ── the home's AC side: the inverter, the meter and the loads meet at the distribution board ──────────────────
fill, stroke = KIND["grid"]
nodes.append(f'<rect x="340" y="150" width="70" height="420" rx="8" fill="{fill}" stroke="{stroke}" '
             f'stroke-width="1.5"/>')
nodes.append(f'<text transform="translate(368,360) rotate(-90)" font-size="19" font-weight="600" fill="{INK}" '
             f'text-anchor="middle">Distribution board</text>')
nodes.append(f'<text transform="translate(392,360) rotate(-90)" font-size="16" font-weight="400" fill="{MUTED}" '
             f'text-anchor="middle">the home’s AC bus</text>')

# ── grid, meter, controller ───────────────────────────────────────────────────────────────────────────────────
box(620, 40, 260, 70, "Public grid", "grid")
box(620, 150, 260, 100, "Smart meter", "convert")
if THESIS:
    # The gateway keeps the deterministic parts; the small model runs on a companion device beside it, or on the
    # gateway itself when it has enough memory (Sec. 4.x Implementation, "Deployment on one device or two"; one-device
    # test in Sec. 5.4.x), so the companion device is drawn dashed: optional. The energy management controller is the
    # role (the HEMS). All outside links end at the gateway, which runs the harness and passes the model its data.
    # One device (author's decision, 18 Nov 2026): the home energy gateway, the energy management controller, is a
    # Raspberry Pi 5 or a mini PC that runs EMHASS as the optimiser and the small language model side by side.
    nodes.append('<rect x="530" y="318" width="440" height="272" rx="10" fill="#dcf5ea" stroke="#1b7f5b" '
                 'stroke-width="2.5"/>')
    txt(750, 346, "Home energy gateway", 20, 700, INK, into=nodes)
    txt(750, 368, "energy management controller", 15, 400, MUTED, into=nodes)
    nodes.append('<rect x="548" y="382" width="404" height="190" rx="8" fill="#ffffff" stroke="#1b7f5b" '
                 'stroke-width="1.6"/>')
    txt(750, 406, "Raspberry Pi 5 or mini PC", 17, 600, INK, into=nodes)
    box(564, 420, 172, 92, "EMHASS", "convert", size=18, sw=1.6, sub="optimiser (MPC):\nschedules the devices",
        sub_size=14)
    box(764, 420, 172, 92, "Small language\nmodel", "source", size=18, sw=1.6, sub="reads plans,\nsets constraints",
        sub_size=14)
    txt(750, 540, "harness and checker · control layer · fallback rules", 14, 400, MUTED, into=nodes)
    txt(750, 560, "talks to the devices locally", 14, 400, MUTED, into=nodes)
else:
    box(540, 330, 420, 210, "Energy management controller", "control", size=21, sw=2.5,
        sub="(home energy gateway)", sub_size=17)

# ── smart loads ───────────────────────────────────────────────────────────────────────────────────────────────
LY = 640 if THESIS else 620  # top of the loads box
fill, stroke = KIND["group"]
nodes.append(f'<rect x="300" y="{LY}" width="790" height="270" rx="10" fill="{fill}" stroke="{stroke}" '
             f'stroke-width="1.5"/>')
txt(322, LY + 32, "Smart loads", 20, 700, INK, "start", into=nodes)
devices = ["Heat pump", "Water heater", "Air\nconditioning", "EV charger\nand car",
           "Washing\nmachine", "Dishwasher", "Smart\nthermostats", "Smart\nlight bulbs"]
for i, name in enumerate(devices):
    box(322 + (i % 4) * 190, LY + 52 + (i // 4) * 104, 176, 90, name, "load", size=18, weight=400, sw=1.2)

# ── the household's app and the internet: one box each (the thesis's own design is in Figure 1.2) ─────────────
if THESIS:
    box(1200, 30, 480, 110, "Internet services", "net", size=20,
        sub="day-ahead prices \u00b7 weather forecasts\ncloud LLM (optional fallback)", sub_size=17)
    fill, stroke = KIND["app"]
    nodes.append(f'<rect x="1220" y="226" width="440" height="456" rx="8" fill="{fill}" stroke="{stroke}" '
                 f'stroke-width="1.8"/>')
    txt(1240, 256, "Household app", 19, 700, "#3b2c84", "start", into=nodes)
    py = 272
    for label, h in [("Plans, typed or spoken\n\u201ccharge the car for work tomorrow,\nguests from six\u201d", 92),
                     ("Live view: PV, consumption, battery %,\ngrid import/export, EV, indoor \u00b0C", 68),
                     ("Today\u2019s plan, prices and the\ncommitted requirements", 68),
                     ("Savings vs rules, PV used at home", 50),
                     ("Questions and messages,\neach with its reason", 68)]:
        box(1240, py, 400, h, label, "panel", size=16, weight=400, sw=1)
        py += h + 12
else:
    box(1120, 345, 270, 90, "Household app", "app")
    box(1120, 465, 270, 90, "Internet services", "net", sub="day-ahead prices, weather forecasts")

# ── power flows ───────────────────────────────────────────────────────────────────────────────────────────────
# Power never passes through the controller. DC on the inverter's input side: the panels, the wind turbine (whose
# variable AC a rectifier turns into DC first) and the battery. AC from the inverter to the board, the meter, the
# grid and the loads. Two arrowheads = power flows both ways (grid import and export, battery charge and discharge).
arrow([(92, 130), (92, 198)], DC)                              # panels -> hybrid inverter
arrow([(227, 130), (227, 198)], DC)                            # turbine with rectifier -> hybrid inverter
arrow([(160, 428), (160, 282)], DC, both=True)                 # battery <-> hybrid inverter
arrow([(290, 240), (338, 240)], AC, both=True)                 # hybrid inverter <-> board
arrow([(412, 200), (618, 200)], AC, both=True)                 # board <-> smart meter
arrow([(750, 110), (750, 148)], AC, both=True)                 # smart meter <-> grid
arrow([(375, 570), (375, LY - 2)], AC)                            # board -> loads

# ── communication ─────────────────────────────────────────────────────────────────────────────────────────────
if THESIS:
    arrow([(640, 250), (640, 316)], COM, dashed=True, both=True)
    lbl(652, 290, "meter data")
    arrow([(30, 240), (12, 240), (12, 615), (512, 615), (512, 470), (528, 470)], COM, dashed=True, both=True)
    lbl(40, 607, "inverter data, battery setpoints")
    arrow([(820, 590), (820, LY - 2)], COM, dashed=True)
    lbl(832, 618, "device setpoints")
    arrow([(764, 466), (738, 466)], COM, dashed=True, top=True)  # the model's constraints into the optimiser
    arrow([(970, 400), (1176, 400), (1176, 120), (1198, 120)], COM, dashed=True, both=True)
    lbl(990, 372, "prices, forecasts,")
    lbl(990, 392, "fallback, model updates")
    arrow([(970, 520), (1218, 520)], COM, dashed=True, both=True)
    lbl(1094, 494, "home Wi-Fi, or a VPN", "middle")
    lbl(1094, 510, "when away; encrypted", "middle")
else:
    arrow([(820, 250), (820, 328)], COM, dashed=True, both=True)
    lbl(832, 295, "meter data")
    arrow([(30, 240), (12, 240), (12, 595), (660, 595), (660, 542)], COM, dashed=True, both=True)
    lbl(395, 587, "inverter data, battery setpoints")
    arrow([(820, 540), (820, 618)], COM, dashed=True)
    lbl(832, 585, "device setpoints")
    arrow([(960, 390), (1118, 390)], COM, dashed=True, both=True)
    lbl(1040, 380, "home Wi-Fi", "middle")
    arrow([(1118, 510), (962, 510)], COM, dashed=True)
    lbl(1040, 500, "prices, forecasts", "middle")

# ── legend ────────────────────────────────────────────────────────────────────────────────────────────────────
lx = 40
for name, color, dashed, both in [("communication", COM, True, True), ("DC power", DC, False, False),
                                  ("AC power", AC, False, False),
                                  ("two arrowheads: power flows both ways", AC, False, True)]:
    arrow([(lx, 965), (lx + 60, 965)], color, dashed, both)
    txt(lx + 74, 971, name, 17, 400, INK, "start")
    lx += 290

markers = "".join(
    f'<marker id="{m}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5.5" markerHeight="5.5" '
    f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{c}"/></marker>'
    for m, c in [("dc", DC), ("ac", AC), ("two", TWO), ("com", COM)])
svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
       f'font-family="{FONT}" role="img" aria-label="A home energy system: solar PV, a small wind turbine and the '
       f'home battery share one hybrid inverter; the inverter, the smart loads and the smart meter to the public grid '
       f'meet at the distribution board, the home AC bus. No power passes through the energy management controller '
       f'(the home energy gateway): it reads the meter and inverters, sets the battery and the smart loads, talks to the '
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
    out = Path(next(a for a in sys.argv[1:] if not a.startswith("--")))
    out.with_suffix(".svg").write_text(svg, encoding="utf-8")
    render(out.with_suffix(".svg"), out.with_suffix(".png"))
    print("wrote", out.with_suffix(".svg"), out.with_suffix(".png"))
