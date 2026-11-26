"""Write agent_flow.svg (thesis Figure "How each agent decides") next to this script; export.py turns it into a PNG.

Compact portrait layout in the colours of the architecture figure: the harness's event router on top, one card per
agent (built agents in the first row, designed agents in the second) with its two tool steps and tool loop, its
deterministic gate and the two outcomes, and the failure rule at the bottom.
"""
from pathlib import Path
from xml.sax.saxutils import escape

HERE = Path(__file__).parent
INK, MUTED = "#1f2933", "#52606d"
TEAL, TEAL_FILL = "#1f6f78", "#dff0f0"
LINE, GREY, GREY_FILL = "#c3c8cd", "#6b7785", "#f3f3f1"
AMBER, AMBER_FILL = "#c27c0e", "#fcefd9"
ARROW = "#5f6b76"
AGENTS = [  # name, started by, step A, step B, gate, yes, no, built
    ("Household Assistant", "on each household message", ("Read data", "get_home_state"),
     ("Plan", "plan_schedule"), ("Gate: checker", "schedule met, nothing unclear?"),
     ("yes: commit", "MPC constraints"), ("no: ask", "questions in app"), True),
    ("Configurator", "once a week", ("Summarise", "history_summary"), ("Backtest", "compare settings"),
     ("Gate: backtest", "beats the current settings?"), ("yes: apply", "from the next day"),
     ("no: keep", "current settings"), True),
    ("Monitor (designed)", "on a plug-in or a deviation", ("Diagnose", "get_situation"),
     ("Adjust, alert", "propose → preview"), ("Gate: checker", "is an action needed?"),
     ("yes: act", "within the limits"), ("no: no action", "the plan stays"), False),
    ("Explainer (designed)", "after each commit, and daily", ("Read figures", "explain_plan"),
     ("Write message", "cites the figures"), ("Gate: figure check", "figures match the plan?"),
     ("yes: send", "to the household"), ("no: template", "fixed wording"), False),
]
MONO = {"get_home_state", "plan_schedule", "history_summary", "get_situation", "explain_plan"}


def text(x, y, s, size=12, bold=False, color=MUTED, anchor="middle"):
    font = "font-family:Consolas,monospace;" if s in MONO else ""
    weight = "font-weight:bold;" if bold else ""
    return (f'<text x="{x}" y="{y}" text-anchor="{anchor}" dominant-baseline="central" '
            f'style="{font}{weight}font-size:{size}px;fill:{color}">{escape(s)}</text>')


def rect(x, y, w, h, fill, stroke, width=1.2, dashed=False, rx=6):
    dash = ";stroke-dasharray:6 4" if dashed else ""
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" '
            f'style="fill:{fill};stroke:{stroke};stroke-width:{width}{dash}"/>')


def two_line(x, y, w, h, title, sub, fill, stroke, width=1.2, dashed=False):
    return (rect(x, y, w, h, fill, stroke, width, dashed) + text(x + w / 2, y + h / 2 - 9, title, 14, True, INK)
            + text(x + w / 2, y + h / 2 + 9, sub))


def arrow(d, color=ARROW, dashed=False):
    dash = ";stroke-dasharray:4 3" if dashed else ""
    return f'<path d="{d}" style="fill:none;stroke:{color};stroke-width:1.4{dash}" marker-end="url(#a{color[1:]})"/>'


def card(x, y, agent):
    name, started, a, b, gate, yes, no, built = agent
    return "\n".join([
        rect(x, y, 290, 240, "none", LINE, 1, True, 10),
        text(x + 14, y + 20, name, 14, True, INK, "start"), text(x + 14, y + 37, started, anchor="start"),
        two_line(x + 14, y + 50, 124, 46, *a, TEAL_FILL, TEAL, 1.6, not built),
        arrow(f"M{x + 138} {y + 73} H{x + 150}", TEAL),
        two_line(x + 152, y + 50, 124, 46, *b, TEAL_FILL, TEAL, 1.6, not built),
        arrow(f"M{x + 214} {y + 96} V{y + 106} H{x + 76} V{y + 99}", TEAL, True),
        text(x + 145, y + 118, "tool loop", 11, color=TEAL),
        two_line(x + 14, y + 130, 262, 44, *gate, "#ffffff", GREY, 1.6),
        arrow(f"M{x + 76} {y + 174} V{y + 184}"), arrow(f"M{x + 214} {y + 174} V{y + 184}"),
        two_line(x + 14, y + 186, 124, 44, *yes, "#ffffff", LINE),
        two_line(x + 152, y + 186, 124, 44, *no, "#ffffff", LINE),
    ])


def main() -> None:
    markers = "".join(
        f'<marker id="a{c[1:]}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" '
        f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" style="fill:{c}"/></marker>' for c in (ARROW, TEAL))
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="100%" viewBox="0 0 680 668" role="img"><defs>{markers}</defs>',
             rect(40, 12, 600, 36, GREY_FILL, GREY, 1.4),
             text(340, 30, "Event router in the harness, no model: each event starts one agent", 14, True, INK)]
    for i, agent in enumerate(AGENTS):
        x, y = (40, 350)[i % 2], (64, 320)[i // 2]
        if i < 2:
            parts.append(arrow(f"M{x + 145} 48 V{y - 1}"))
        elif i == 2:  # around the outside of the first row, into the card's side
            parts.append(arrow(f"M40 30 H26 V{y + 20} H39"))
        else:
            parts.append(arrow(f"M640 30 H654 V{y + 20} H641"))
        parts.append(card(x, y, agent))
    parts += [rect(40, 576, 600, 50, AMBER_FILL, AMBER, 1.4),
              text(340, 592, "Any failure: timeout, invalid answer, model or network down", 14, True, INK),
              text(340, 610, "keep the plan and settings; the MPC replans hourly; the control layer falls back "
                             "to rules")]
    legend = [(TEAL_FILL, TEAL, False, "built step"), (TEAL_FILL, TEAL, True, "designed, not built"),
              ("#ffffff", GREY, False, "gate or outcome"), (GREY_FILL, GREY, False, "harness"),
              (AMBER_FILL, AMBER, False, "failure rule")]
    x = 40
    for fill, stroke, dashed, label in legend:
        parts.append(rect(x, 642, 22, 14, fill, stroke, 1.2, dashed, 3) + text(x + 28, 649, label, anchor="start"))
        x += 28 + len(label) * 6.4 + 22
    parts.append("</svg>")
    (HERE / "agent_flow.svg").write_text("\n".join(parts) + "\n", encoding="utf-8")
    print("wrote", HERE / "agent_flow.svg")


if __name__ == "__main__":
    main()
