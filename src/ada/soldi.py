"""Lettura dei movimenti (scritti da src.revolut.ingest) e riepiloghi per categoria."""
import hashlib
import re
import sqlite3
import time
import uuid
from datetime import date, timedelta
from pathlib import Path

from ..revolut.store import apri
from .estratto import giorni_tra, leggi_estratto, numero

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


def origine(chiave: str) -> str:
    return "manuale" if chiave.startswith("manuale|") else "estratto" if chiave.startswith("estratto|") else "notifica"


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

    # ---------- elenco e modifiche fatte dall'utente ----------
    def elenco(self, mese=None, limite=300):
        """I movimenti con la loro chiave (serve a rimuoverli), dal più recente."""
        if mese is not None and not re.fullmatch(r"\d{4}-\d{2}", mese):
            raise ValueError("Il mese deve essere nel formato 2026-10.")
        sql = "SELECT chiave, quando, importo, controparte FROM movimenti" + (" WHERE CAST(quando AS TEXT) LIKE ?" if mese else "")
        righe = self._leggi(sql + " ORDER BY CAST(quando AS TEXT) DESC LIMIT ?", ((mese + "%",) if mese else ()) + (limite,))
        for r in righe:
            r["quando"], r["origine"] = str(r["quando"]), origine(r["chiave"])
        return righe

    def aggiungi(self, data, importo, controparte, tipo):
        """Un movimento scritto a mano (un pagamento che non è arrivato come notifica)."""
        if tipo not in ("uscita", "entrata"):
            raise ValueError("Scegli se è un'uscita o un'entrata.")
        v = numero(importo)
        if v is None or v <= 0 or v > 1_000_000:
            raise ValueError("L'importo deve essere un numero maggiore di zero.")
        nome = " ".join(str(controparte or "").split())
        if not 1 <= len(nome) <= 80:
            raise ValueError("Scrivi a chi o per cosa è (al massimo 80 caratteri).")
        try:
            giorno = date.fromisoformat(str(data or ""))
        except ValueError:
            raise ValueError("La data non è valida.") from None
        if giorno > date.today() + timedelta(days=1) or giorno.year < 2000:
            raise ValueError("La data non può essere nel futuro né prima del 2000.")
        quando = f"{giorno.isoformat()} " + (time.strftime("%H:%M:%S") if giorno == date.today() else "12:00:00")
        chiave = f"manuale|{uuid.uuid4().hex[:12]}"
        db = apri(str(self.percorso))
        try:
            db.execute("INSERT INTO movimenti VALUES (?,?,?,?,?)",
                       (chiave, quando, round(-v if tipo == "uscita" else v, 2), nome, "inserito a mano"))
            db.commit()
        finally:
            db.close()
        return {"chiave": chiave, "quando": quando, "importo": round(-v if tipo == "uscita" else v, 2), "controparte": nome}

    def rimuovi(self, chiave):
        """Toglie un movimento (anche uno letto da una notifica: ricordandolo, così non ritorna)."""
        if not self.percorso.exists():
            return False
        db = apri(str(self.percorso))
        try:
            tolti = db.execute("DELETE FROM movimenti WHERE chiave=?", (str(chiave),)).rowcount
            if tolti:
                db.execute("INSERT OR IGNORE INTO rimossi VALUES (?)", (str(chiave),))
            db.commit()
        finally:
            db.close()
        return tolti == 1

    def importa_estratto(self, testo):
        """Confronta l'estratto conto con i movimenti: aggiunge quelli che mancano e segnala gli altri da controllare."""
        letto = leggi_estratto(testo)
        righe = sorted(letto["righe"], key=lambda r: (r["data"], r["ora"]))
        if not righe:
            raise ValueError("Nell'estratto non ho trovato movimenti da importare" +
                             (f" (ignorati: {', '.join(f'{n} {m}' for m, n in letto['ignorate'].items())})." if letto["ignorate"] else "."))
        db = apri(str(self.percorso))
        try:
            noti = [dict(zip(("chiave", "quando", "importo", "controparte"), r)) for r in
                    db.execute("SELECT chiave, quando, importo, controparte FROM movimenti").fetchall()]
            for n in noti:
                n["giorno"] = str(n["quando"])[:10]
            abbinati, nuovi_chiavi, presenti, viste = set(), [], 0, {}
            for r in righe:
                scelti = [n for n in noti if n["chiave"] not in abbinati and abs(n["importo"] - r["importo"]) < 0.005
                          and giorni_tra(n["giorno"], r["data"]) <= 2]
                if scelti:
                    n = min(scelti, key=lambda x: giorni_tra(x["giorno"], r["data"]))
                    abbinati.add(n["chiave"])
                    presenti += 1
                    if not (n["controparte"] or "").strip():
                        db.execute("UPDATE movimenti SET controparte=? WHERE chiave=?", (r["descrizione"], n["chiave"]))
                    continue
                impronta = hashlib.sha1(f"{r['data']}|{r['importo']:.2f}|{r['descrizione']}".encode()).hexdigest()[:10]
                viste[impronta] = viste.get(impronta, 0) + 1  # due righe identiche lo stesso giorno restano due movimenti
                chiave = f"estratto|{r['data']}|{r['importo']:.2f}|{impronta}|{viste[impronta]}"
                db.execute("INSERT OR IGNORE INTO movimenti VALUES (?,?,?,?,?)",
                           (chiave, f"{r['data']} {r['ora']}", r["importo"], r["descrizione"], "da estratto conto"))
                abbinati.add(chiave)
                nuovi_chiavi.append(chiave)
            db.commit()
            primo, ultimo = righe[0]["data"], righe[-1]["data"]
            dubbi = [n for n in noti if n["chiave"] not in abbinati and primo <= n["giorno"] <= ultimo]
        finally:
            db.close()
        return {"righe": len(righe), "nuovi": len(nuovi_chiavi), "presenti": presenti, "ignorate": letto["ignorate"],
                "periodo": [primo, ultimo], "chiavi_nuove": nuovi_chiavi, "totale_da_controllare": len(dubbi),
                "da_controllare": [{"chiave": n["chiave"], "quando": str(n["quando"]), "importo": n["importo"],
                                    "controparte": n["controparte"], "origine": origine(n["chiave"])} for n in dubbi[:40]]}

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
