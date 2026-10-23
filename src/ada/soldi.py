"""Lettura dei movimenti (scritti da src.revolut.ingest) e riepiloghi per categoria."""
import sqlite3
import time
from pathlib import Path

# Regole semplici, in ordine: la prima che combacia vince. Il resto è "Altro".
CATEGORIE = [
    ("Abbonamenti", ("netflix", "spotify", "prime", "apple", "google", "disney", "dazn")),
    ("Cibo e bar", ("bar", "caff", "ristorante", "pizz", "trattoria", "sushi", "mcdonald", "esselunga",
                    "coop", "conad", "carrefour", "lidl", "supermerc", "panific", "pasticc", "gelat")),
    ("Trasporti", ("trenitalia", "italo", "uber", "taxi", "atm", "benzina", "eni", "q8", "autostrad",
                   "telepass", "flixbus")),
    ("Casa e bollette", ("enel", "plenitude", "hera", "a2a", "tim", "vodafone", "wind", "iliad",
                         "affitto", "condominio")),
    ("Salute", ("farmacia", "medic", "dentist")),
    ("Shopping", ("amazon", "zara", "h&m", "decathlon", "ikea")),
]


def categoria(controparte: str) -> str:
    c = (controparte or "").lower()
    for nome, parole in CATEGORIE:
        if any(p in c for p in parole):
            return nome
    return "Altro"


class Soldi:
    def __init__(self, percorso):
        self.percorso = Path(percorso)

    def _righe(self, mese):
        if not self.percorso.exists():
            return []
        try:
            db = sqlite3.connect(f"file:{self.percorso}?mode=ro", uri=True)
            sql = "SELECT quando, importo, controparte FROM movimenti"
            args = ()
            if mese:
                sql += " WHERE CAST(quando AS TEXT) LIKE ?"
                args = (mese + "%",)
            righe = db.execute(sql + " ORDER BY CAST(quando AS TEXT) DESC", args).fetchall()
            db.close()
            return righe
        except sqlite3.Error:
            return []

    def riepilogo(self, periodo="mese"):
        mese = time.strftime("%Y-%m") if periodo == "mese" else None
        righe = self._righe(mese)
        entrate = round(sum(r[1] for r in righe if r[1] > 0), 2)
        uscite = round(-sum(r[1] for r in righe if r[1] < 0), 2)
        cat, esercenti = {}, {}
        for _, imp, c in righe:
            if imp < 0:
                cat[categoria(c)] = cat.get(categoria(c), 0) - imp
                esercenti[c or "(senza nome)"] = esercenti.get(c or "(senza nome)", 0) - imp
        ordina = lambda d: [{"nome": k, "totale": round(v, 2)} for k, v in sorted(d.items(), key=lambda x: -x[1])]
        return {
            "periodo": mese or "sempre", "movimenti": len(righe), "entrate": entrate, "uscite": uscite,
            "saldo": round(entrate - uscite, 2), "per_categoria": ordina(cat),
            "top_esercenti": ordina(esercenti)[:8],
            "ultimi": [{"quando": str(q), "importo": i, "controparte": c} for q, i, c in righe[:8]],
        }

    def testo(self, periodo="mese") -> str:
        r = self.riepilogo(periodo)
        if not r["movimenti"]:
            return "Nessun movimento registrato per il periodo richiesto."
        righe = [f"Periodo {r['periodo']}: {r['movimenti']} movimenti, entrate {r['entrate']:.2f} €, "
                 f"uscite {r['uscite']:.2f} €, saldo {r['saldo']:.2f} €.", "Uscite per categoria:"]
        righe += [f"- {c['nome']}: {c['totale']:.2f} €" for c in r["per_categoria"]]
        righe.append("Esercenti più costosi:")
        righe += [f"- {e['nome']}: {e['totale']:.2f} €" for e in r["top_esercenti"][:5]]
        return "\n".join(righe)
