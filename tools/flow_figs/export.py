"""Export the request-path and plan_schedule diagrams (SVG files next to this script) to thesis PNGs."""
import re
import shutil
import subprocess
from pathlib import Path

HERE = Path(__file__).parent  # SVG sources next to this script
DEST = Path(__import__("os").environ.get("FLOW_FIGS_DEST", HERE.parents[1] / "attachments" / "gateway"))  # preview elsewhere
CSS = """
:root{--b:#B4B2A9;--t:#888780}
html,body{margin:0;padding:0;background:#fff}
text{font-family:Arial,Helvetica,sans-serif}
.t{font-size:14px;fill:#3d3d3a}.ts{font-size:12px;fill:#5F5E5A}.th{font-size:14px;font-weight:bold;fill:#2C2C2A}
.arr{stroke:#5F5E5A;stroke-width:1.2;fill:none}
.c-amber>rect{fill:#FAEEDA;stroke:#854F0B}.c-amber>.th{fill:#633806}.c-amber>.ts{fill:#854F0B}
.c-teal>rect,.c-teal>circle{fill:#E1F5EE;stroke:#0F6E56}.c-teal>.th{fill:#085041}.c-teal>.ts{fill:#0F6E56}
.c-blue>rect{fill:#E6F1FB;stroke:#185FA5}.c-blue>.th{fill:#0C447C}.c-blue>.ts{fill:#185FA5}
.c-gray>rect{fill:#F1EFE8;stroke:#5F5E5A}.c-gray>.th{fill:#2C2C2A}.c-gray>.ts{fill:#5F5E5A}
.c-coral>rect{fill:#FAECE7;stroke:#993C1D}.c-coral>.th{fill:#712B13}.c-coral>.ts{fill:#993C1D}
.c-green>rect{fill:#EAF3DE;stroke:#3B6D11}.c-green>.th{fill:#27500A}.c-green>.ts{fill:#3B6D11}
"""
chrome = next(p for p in [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                          r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                          shutil.which("chrome") or ""] if p and Path(p).exists())
for name in ("request_path", "plan_schedule", "agent_flow", "runtime_day"):
    svg = (HERE / f"{name}.svg").read_text(encoding="utf-8")
    w, h = map(float, re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', svg).groups())
    svg = svg.replace('width="100%"', f'width="{w:g}" height="{h:g}"')
    page = f'<!doctype html><html><head><meta charset="utf-8"><style>{CSS}</style></head><body>{svg}</body></html>'
    tmp = HERE / f"{name}.tmp.html"
    tmp.write_text(page, encoding="utf-8")
    png = DEST / f"{name}.png"
    subprocess.run([chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--window-size={int(w)},{int(h)}",
                    "--force-device-scale-factor=3", f"--screenshot={png}", tmp.as_uri()], check=True,
                   capture_output=True)
    print(png, png.stat().st_size)
    tmp.unlink()
# The PNGs are then cropped to their content (PIL ImageChops bbox, 30 px margin) before use in the thesis.
