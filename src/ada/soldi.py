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


NOMI_CATEGORIE = [nome for nome, _ in CATEGORIE] + ["Altro"]


def categoria(controparte: str, extra=None) -> str:
    c = (controparte or "").lower()
    for parola, nome in (extra or {}).items():  # regole imparate da Ada: hanno la precedenza
        if parola in c:
            return nome
    for nome, parole in CATEGORIE:
        if any(p in c for p in parole):
            return nome
    return "Altro"


class Soldi:
    def __init__(self, percorso):
        self.percorso = Path(percorso)
        self.regole = {}  # parola -> categoria, caricate da Ada

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

    def tutti(self):
        """Tutti i movimenti con la loro chiave, dal più vecchio (serve ad abbinare i bonifici alle fatture)."""
        if not self.percorso.exists():
            return []
        try:
            db = sqlite3.connect(f"file:{self.percorso}?mode=ro", uri=True)
            righe = db.execute("SELECT chiave, quando, importo, controparte, testo FROM movimenti "
                               "ORDER BY CAST(quando AS TEXT)").fetchall()
            db.close()
        except sqlite3.Error:
            return []
        return [{"chiave": c, "quando": str(q), "importo": i, "controparte": cp, "testo": t} for c, q, i, cp, t in righe]

    def riepilogo(self, periodo="mese"):
        mese = time.strftime("%Y-%m") if periodo == "mese" else None
        righe = self._righe(mese)
        entrate = round(sum(r[1] for r in righe if r[1] > 0), 2)
        uscite = round(-sum(r[1] for r in righe if r[1] < 0), 2)
        cat, esercenti, altro = {}, {}, {}
        for _, imp, c in righe:
            if imp < 0:
                k = categoria(c, self.regole)
                cat[k] = cat.get(k, 0) - imp
                if k == "Altro":
                    altro[c or "(senza nome)"] = altro.get(c or "(senza nome)", 0) - imp
                esercenti[c or "(senza nome)"] = esercenti.get(c or "(senza nome)", 0) - imp
        ordina = lambda d: [{"nome": k, "totale": round(v, 2)} for k, v in sorted(d.items(), key=lambda x: -x[1])]
        return {
            "periodo": mese or "sempre", "movimenti": len(righe), "entrate": entrate, "uscite": uscite,
            "saldo": round(entrate - uscite, 2), "per_categoria": ordina(cat),
            "top_esercenti": ordina(esercenti)[:8], "non_categorizzati": ordina(altro)[:6],
            "ultimi": [{"quando": str(q), "importo": i, "controparte": c} for q, i, c in righe[:8]],
        }

    def _leggi(self, sql, args=()):
        if not self.percorso.exists():
            return []
        try:
            db = sqlite3.connect(f"file:{self.percorso}?mode=ro", uri=True)
            db.row_factory = sqlite3.Row
            righe = [dict(r) for r in db.execute(sql, args).fetchall()]
            db.close()
            return righe
        except sqlite3.Error:
            return []

    def lettura(self):
        """Com'è andata l'ultima lettura delle notifiche (la scrive src.revolut.ingest), oppure None."""
        r = self._leggi("SELECT quando, totale, revolut, nuovi, non_riconosciuti, errore FROM letture WHERE id=1")
        return r[0] if r else None

    def non_riconosciute(self, n=3):
        return self._leggi("SELECT titolo, contenuto FROM non_riconosciute ORDER BY CAST(quando AS TEXT) DESC LIMIT ?", (n,))

    def stato_lettura(self, adesso=None) -> str:
        """Frase per Ada e per l'utente: la lettura delle notifiche funziona o no, e che cosa ha visto."""
        l = self.lettura()
        if not l:
            return "Lettura notifiche Revolut: nessuna lettura registrata (la routine «notifiche» non è ancora partita o Termux:API non c'è)."
        fa = max(0, int((adesso or time.time()) - l["quando"]) // 60)
        if l["errore"]:
            frase = f"Lettura notifiche Revolut: l'ultima ({fa} min fa) è FALLITA: {l['errore']}."
        else:
            frase = (f"Lettura notifiche Revolut: ultima {fa} min fa, funziona. Nella tendina in quel momento: "
                     f"notifiche Revolut {l['revolut']}, movimenti nuovi {l['nuovi']}, non riconosciute {l['non_riconosciuti']}. "
                     "Android mostra solo le notifiche ancora presenti: se una è stata cancellata prima della lettura non si recupera.")
        nr = self.non_riconosciute()
        if nr:
            frase += " Ultime notifiche Revolut che non so leggere: " + " | ".join(
                f"{(x['titolo'] or '')[:40]}: {(x['contenuto'] or '')[:80]}" for x in nr)
        return frase

    def testo(self, periodo="mese") -> str:
        r = self.riepilogo(periodo)
        if not r["movimenti"]:
            return "Nessun movimento registrato per il periodo richiesto.\n" + self.stato_lettura()
        righe = [f"Periodo {r['periodo']}: {r['movimenti']} movimenti, entrate {r['entrate']:.2f} €, "
                 f"uscite {r['uscite']:.2f} €, saldo {r['saldo']:.2f} €.",
                 f"Ultimo movimento letto: {r['ultimi'][0]['quando']}.", "Uscite per categoria:"]
        righe += [f"- {c['nome']}: {c['totale']:.2f} €" for c in r["per_categoria"]]
        righe.append("Esercenti più costosi:")
        righe += [f"- {e['nome']}: {e['totale']:.2f} €" for e in r["top_esercenti"][:5]]
        if r["non_categorizzati"]:
            righe.append("Senza categoria (finiti in Altro): " + ", ".join(
                f"{e['nome']} {e['totale']:.2f} €" for e in r["non_categorizzati"]))
        righe.append(self.stato_lettura())
        return "\n".join(righe)
