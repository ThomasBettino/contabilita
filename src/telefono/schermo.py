"""Legge la schermata (dump di uiautomator) e la trasforma in elementi numerati per Ada."""
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

BOUNDS = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")
MAX_ELEMENTI = 120


@dataclass
class Elemento:
    id: int
    testo: str
    desc: str
    rid: str
    classe: str
    cliccabile: bool
    scrollabile: bool
    modificabile: bool
    password: bool
    centro: tuple

    @property
    def etichetta(self) -> str:
        return (self.testo or self.desc).strip()


def parse(xml: str):
    """Restituisce (pacchetto in primo piano, [Elemento])."""
    root = ET.fromstring(xml)
    pacchetto, elementi = "", []
    for n in root.iter("node"):
        pacchetto = pacchetto or n.get("package", "")
        testo, desc = n.get("text", ""), n.get("content-desc", "")
        cliccabile = n.get("clickable") == "true"
        scrollabile = n.get("scrollable") == "true"
        modificabile = n.get("class", "").endswith("EditText")
        if not (testo.strip() or desc.strip() or cliccabile or scrollabile or modificabile):
            continue
        m = BOUNDS.fullmatch(n.get("bounds", ""))
        if not m:
            continue
        x1, y1, x2, y2 = map(int, m.groups())
        if x2 <= x1 or y2 <= y1:
            continue
        elementi.append(Elemento(len(elementi) + 1, testo, desc, n.get("resource-id", ""), n.get("class", ""),
                                 cliccabile, scrollabile, modificabile, n.get("password") == "true",
                                 ((x1 + x2) // 2, (y1 + y2) // 2)))
        if len(elementi) >= MAX_ELEMENTI:
            break
    return pacchetto, elementi


def render(pacchetto: str, elementi) -> str:
    righe = [f"App in primo piano: {pacchetto}"]
    for e in elementi:
        flag = [f for f, v in (("cliccabile", e.cliccabile), ("campo di testo", e.modificabile),
                               ("scorre", e.scrollabile), ("PASSWORD", e.password)) if v]
        et = "" if e.password else e.etichetta[:120].replace("\n", " ")
        righe.append(f'[{e.id}] "{et}"' + (f" ({', '.join(flag)})" if flag else ""))
    if not elementi:
        righe.append("(schermata vuota o non leggibile)")
    return "\n".join(righe)
