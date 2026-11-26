"""Write architecture.svg (thesis Figure "Architecture of the HEMS on the gateway") next to this script.

A narrower redraw of the plan page's architecture diagram (docs/gateway_thesis_plan.html), so that its text prints at
about 7 to 9 pt on the thesis page: the same rows (outside the gateway, agent layer, tools, deterministic harness,
control layer, devices), the same arrows and the same colours, without the icons. export.py turns it into a PNG.
"""
from pathlib import Path
from xml.sax.saxutils import escape

HERE = Path(__file__).parent
FG, MUTED, LINE = "#1d2622", "#5a6661", "#c9d1cd"
GRID, GRID_SOFT, SUN, SUN_SOFT, BG = "#1f6f78", "#dcefef", "#b86e00", "#fbefd9", "#f6f7f5"
STYLE = {  # kind: (fill, stroke, width)
    "box": ("#ffffff", LINE, 1.4), "agent": (GRID_SOFT, GRID, 1.6), "sun": (SUN_SOFT, SUN, 1.4),
    "det": (BG, MUTED, 1.2), "zone": ("none", LINE, 1.2)}
out = []


def text(x, y, s, size=12, bold=False, color=MUTED, anchor="start", mono=False, rotate=None):
    font = "font-family:Consolas,'Courier New',monospace;" if mono else ""
    weight = "font-weight:bold;" if bold else ""
    rot = f' transform="rotate({rotate} {x} {y})"' if rotate else ""
    out.append(f'<text x="{x}" y="{y}" text-anchor="{anchor}" dominant-baseline="central"{rot} '
               f'style="{font}{weight}font-size:{size}px;fill:{color}">{escape(s)}</text>')


def rect(x, y, w, h, kind, dashed=False, rx=8):
    fill, stroke, width = STYLE[kind]
    dash = ";stroke-dasharray:6 5" if dashed else ""
    out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" '
               f'style="fill:{fill};stroke:{stroke};stroke-width:{width}{dash}"/>')


def node(x, y, w, h, kind, title, subs=(), dashed=False, mono_sub=False, center=False):
    rect(x, y, w, h, kind, dashed)
    cx, anchor = (x + w / 2, "middle") if center else (x + 14, "start")
    lines = 1 + len(subs)
    top = y + h / 2 - (lines - 1) * 9
    text(cx, top, title, 14, True, FG, anchor)
    for i, s in enumerate(subs):
        text(cx, top + 20 + i * 17, s, 12, color=MUTED, anchor=anchor, mono=mono_sub)


def arrow(d, color=MUTED, dashed=False, both=False):
    dash = ";stroke-dasharray:5 4" if dashed else ""
    m = color[1:]
    start = f' marker-start="url(#m{m})"' if both else ""
    out.append(f'<path d="{d}" style="fill:none;stroke:{color};stroke-width:1.5{dash}"{start} marker-end="url(#m{m})"/>')


def main() -> None:
    # row A: outside the gateway
    node(20, 20, 220, 60, "box", "Household", ["plans, changes, answers"])
    node(270, 20, 220, 60, "sun", "Market and weather", ["prices, tariff, DWD forecasts"])
    node(520, 20, 220, 60, "box", "Cloud LLM (fallback)", ["only when the local SLM fails"], dashed=True)
    arrow("M60 80 V120", GRID)
    text(68, 100, "plans, changes", color=GRID)
    arrow("M230 122 V82", GRID, dashed=True)
    text(238, 100, "messages, questions", color=GRID)
    arrow("M375 80 V232", SUN)
    text(383, 94, "prices, forecasts")
    arrow("M720 80 V112", dashed=True)
    text(712, 94, "fallback only", anchor="end")

    # row B: the agent layer
    rect(12, 114, 736, 94, "zone", dashed=True, rx=10)
    text(388, 107, "AGENT LAYER · local SLM on the gateway", 11, color=MUTED, mono=True)
    agents = [("Household Assistant", ["on each message", "plan → constraints, asks"], False),
              ("Explainer", ["after each commit, daily", "plan → message, report"], True),
              ("Monitor", ["on plug-in or deviation", "diagnoses, adjusts"], True),
              ("Configurator", ["weekly, offline", "history → MPC settings"], False)]
    for i, (title, subs, dashed) in enumerate(agents):
        x = (20, 200, 385, 565)[i]
        node(x, 122, 175 if i != 1 else 170, 78, "agent", title, subs, dashed=dashed, center=True)
    for x, label in ((50, "constraints"), (230, "committed plan"), (415, "situation, fixes"), (595, "settings")):
        arrow(f"M{x} 202 V232", GRID, both=True)
        text(x + 8, 217, label, color=GRID)

    # row C: the only way in, the validated tools
    rect(20, 234, 720, 52, "sun")
    text(34, 260, "Tools", 14, True, FG)
    text(92, 251, "get_home_state · get_prices · get_weather_forecast · get_appliances · plan_schedule", 12, mono=True)
    text(92, 269, "history_summary · backtest · get_situation · explain_plan", 12, mono=True)

    # row D: the deterministic harness
    arrow("M110 288 V322")
    text(118, 305, "constraints, settings, forecasts")
    arrow("M380 322 V288", dashed=True)
    text(388, 305, "violations, preview")
    arrow("M640 322 V288")
    text(648, 305, "history, backtest")
    node(20, 324, 200, 92, "box", "EMHASS (MPC)", ["tuned settings", "LP / MILP", "replans hourly"])
    node(280, 324, 200, 92, "box", "Checker", ["comfort, EV by departure", "battery, grid limit", "feasibility"])
    node(540, 324, 200, 92, "box", "History store", ["meters, weather", "forecast errors", "committed plans, events"])
    arrow("M220 370 H278")
    text(249, 360, "plan", anchor="middle")
    arrow("M480 370 H538")
    text(509, 360, "commit", anchor="middle")
    text(740, 432, "DETERMINISTIC HARNESS", 11, anchor="end", mono=True)

    # row E: the control layer
    arrow("M380 416 V468")
    text(388, 444, "checked plan only")
    rect(20, 470, 720, 74, "det")
    text(34, 490, "Control layer · every 15 min", 14, True, FG)
    text(34, 510, "holds the planned grid exchange · battery absorbs forecast error · keeps comfort, EV deadline,")
    text(34, 527, "battery limits · fallback rules · raises deviation events")

    # row F: the devices
    arrow("M100 544 V598", SUN)
    arrow("M287 544 V598")
    arrow("M472 544 V598")
    text(480, 571, "setpoints")
    node(20, 600, 165, 56, "sun", "PV + battery")
    node(205, 600, 165, 56, "box", "Heat pump", ["SG Ready / EEBus"], mono_sub=True)
    node(390, 600, 165, 56, "box", "EV charger", ["OCPP"], mono_sub=True)
    node(575, 600, 165, 56, "box", "Home Assistant", ["device integration"], mono_sub=True)
    arrow("M740 628 H756 V370 H742")
    text(770, 499, "measurements, events", rotate=-90, anchor="middle")

    text(380, 682, "No agent computes a schedule or switches a device; every agent acts only through the validated "
                   "tools.", anchor="middle")
    text(380, 700, "Dashed agent boxes: designed, not built or evaluated.", anchor="middle")

    markers = "".join(
        f'<marker id="m{c[1:]}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" '
        f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" style="fill:{c}"/></marker>' for c in (MUTED, GRID, SUN))
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="100%" viewBox="0 0 780 714" role="img"><defs>{markers}</defs>\n'
           + "\n".join(out) + "\n</svg>\n")
    (HERE / "architecture.svg").write_text(svg, encoding="utf-8")
    print("wrote", HERE / "architecture.svg")


if __name__ == "__main__":
    main()
