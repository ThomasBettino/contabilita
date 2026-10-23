"""Trasforma il testo di una notifica Revolut in un movimento.

I formati reali delle notifiche vanno verificati sul telefono: ciò che non si
riconosce viene restituito come `None` e salvato grezzo, così il Capo può
vedere gli esempi e migliorare le regole.
"""
import re
from dataclasses import dataclass
from typing import Optional

IMPORTO = re.compile(r"(?:€\s*)?(\d{1,3}(?:[.\s]\d{3})*(?:,\d{1,2})|\d+(?:[.,]\d{1,2})?)\s*(?:€|EUR)?")
USCITA = ("pagamento", "hai pagato", "pagato", "addebito", "prelievo", "bonifico inviato", "hai inviato")
ENTRATA = ("hai ricevuto", "ricevuto", "accredito", "rimborso", "bonifico in arrivo", "ti ha inviato")
CONTROPARTE = re.compile(r"\b(?:a|presso|da|di)\s+(.+?)\s*$", re.IGNORECASE)


@dataclass
class Movimento:
    importo: float  # positivo = entrata, negativo = uscita
    controparte: str
    testo: str


def _numero(s: str) -> float:
    s = s.strip().replace(" ", "")
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    return float(s)


def parse(titolo: str, contenuto: str) -> Optional[Movimento]:
    testo = f"{titolo} {contenuto}".strip()
    basso = testo.lower()
    m = IMPORTO.search(testo)
    if not m:
        return None
    if any(k in basso for k in ENTRATA):
        segno = 1
    elif any(k in basso for k in USCITA):
        segno = -1
    else:
        return None
    resto = testo[m.end():]
    c = CONTROPARTE.search(resto)
    controparte = c.group(1).strip(" .") if c else ""
    return Movimento(segno * _numero(m.group(1)), controparte, testo)
