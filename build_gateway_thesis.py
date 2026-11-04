"""Builds gateway_thesis.tex: the template preamble of main.tex (up to \\begin{document}) plus gateway_body.tex,
with \\parencite{...} and \\textcite{...} written out as APA author-year text (the template has no biblatex)."""

import re
from pathlib import Path

HERE = Path(__file__).parent
AUTHORS = {  # key: (authors as cited, year)
    "ahmaditeshnizi2024": ("AhmadiTeshnizi et al.", "2024"),
    "bdew2023": ("BDEW", "2023"),
    "beaudin2015": ("Beaudin \\& Zareipour", "2015"),
    "bischof2018": ("Bischof et al.", "2018"),
    "blonsky2022": ("Blonsky et al.", "2022"),
    "bnetzaEEG": ("Bundesnetzagentur", "n.d."),
    "catapult2026": ("Energy Systems Catapult", "2026"),
    "dwd": ("Deutscher Wetterdienst", "n.d."),
    "elmakroum2026": ("El Makroum et al.", "2026"),
    "emhass": ("EMHASS contributors", "2026"),
    "energycharts": ("Fraunhofer ISE", "n.d."),
    "evcc14a": ("evcc", "n.d."),
    "hevner2004": ("Hevner et al.", "2004"),
    "jonah2026": ("Jonah et al.", "2026"),
    "jung2026": ("Jung", "2026"),
    "kitchenham2007": ("Kitchenham \\& Charters", "2007"),
    "le2026": ("Le", "2026"),
    "liu2025": ("Liu et al.", "2025"),
    "michelon2025": ("Michelon et al.", "2025"),
    "opsd2020": ("Open Power System Data", "2020"),
    "peffers2007": ("Peffers et al.", "2007"),
    "raghavan2025": ("Raghavan \\& Giridhar", "2025"),
    "ramamonjison2023": ("Ramamonjison et al.", "2023"),
    "ruhnau2019": ("Ruhnau et al.", "2019"),
    "when2heat2023": ("Ruhnau \\& Muessel", "2023"),
    "sanguinetti2025": ("Sanguinetti et al.", "2025"),
    "seal2019": ("Seal et al.", "2019"),
    "sha2001": ("Sha", "2001"),
    "sorensen2024": ("Sørensen et al.", "2024"),
    "tuomela2021": ("Tuomela et al.", "2021"),
    "wohlin2014": ("Wohlin", "2014"),
    "xiao2024": ("Xiao et al.", "2024"),
    "yang2025": ("Yang et al.", "2025"),
    "zhang2024": ("Zhang \\& Chen", "2024"),
}


def paren(match: re.Match) -> str:
    keys = [k.strip() for k in match.group(1).split(",")]
    return "(" + "; ".join(f"{AUTHORS[k][0].replace(chr(92) + '&', chr(92) + '&')}, {AUTHORS[k][1]}" for k in keys) + ")"


def narrative(match: re.Match) -> str:
    name, year = AUTHORS[match.group(1).strip()]
    return f"{name.replace(chr(92) + '&', 'and')} ({year})"


def main() -> None:
    lines = (HERE / "main.tex").read_text(encoding="utf-8").splitlines(keepends=True)
    head = "".join(lines[: next(i for i, l in enumerate(lines) if l.startswith("\\begin{document}")) + 1])
    body = (HERE / "gateway_body.tex").read_text(encoding="utf-8")
    body = re.sub(r"\\parencite\{([^}]*)\}", paren, body)
    body = re.sub(r"\\textcite\{([^}]*)\}", narrative, body)
    missing = re.findall(r"\\(?:paren|text)cite\{", body)
    assert not missing, missing
    (HERE / "gateway_thesis.tex").write_text(head + body, encoding="utf-8")
    print("wrote gateway_thesis.tex")


if __name__ == "__main__":
    main()
