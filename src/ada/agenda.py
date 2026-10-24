"""Agenda e promemoria di Ada: voci con un giorno (e un'ora), avviso sul telefono, anche ricorrenti.

Giorni e ore sono quelli dell'utente (Europe/Rome, o ADA_FUSO): AAAA-MM-GG oppure AAAA-MM-GG HH:MM.
Una voce senza ora vale tutto il giorno e avvisa alle 08:00.
"""
import calendar
import os
import re
import time
from datetime import date, datetime, timedelta

try:
    from zoneinfo import ZoneInfo
except ImportError:  # Python senza zoneinfo
    ZoneInfo = None

TIPI = ("promemoria", "evento")
RIPETIZIONI = ("", "giornaliero", "settimanale", "mensile")
ORA_TUTTO_IL_GIORNO = "08:00"
MAX_VOCI_ATTIVE = 500
ATTESA_MAX_AVVISO = 12 * 3600  # un avviso mancato per più di mezza giornata non si manda più (resta tra gli scaduti)
GIORNI = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]


def fuso():
    try:
        return ZoneInfo(os.environ.get("ADA_FUSO", "Europe/Rome")) if ZoneInfo else None
    except Exception:  # database dei fusi orari assente: si usa l'ora del telefono
        return None


def leggi_quando(quando):
    """«2026-10-24» oppure «2026-10-24 09:30» -> (giorno, ora); ora vuota = tutto il giorno."""
    m = re.fullmatch(r"\s*(\d{4}-\d{2}-\d{2})(?:[ T]+(\d{1,2}):(\d{2}))?\s*", str(quando or ""))
    if not m:
        raise ValueError("La data va scritta così: 2026-10-24 oppure 2026-10-24 09:30.")
    try:
        date.fromisoformat(m.group(1))
        ora = f"{int(m.group(2)):02d}:{m.group(3)}" if m.group(2) is not None else ""
        if ora:
            datetime.strptime(ora, "%H:%M")
    except ValueError:
        raise ValueError("Giorno o ora non esistono: controlla la data.") from None
    return m.group(1), ora


def _avanti(giorno, ripeti):
    d = date.fromisoformat(giorno)
    if ripeti == "giornaliero":
        d += timedelta(days=1)
    elif ripeti == "settimanale":
        d += timedelta(days=7)
    else:  # mensile: stesso giorno del mese dopo, o l'ultimo se non esiste
        anno, mese = (d.year + (d.month == 12), d.month % 12 + 1)
        d = date(anno, mese, min(d.day, calendar.monthrange(anno, mese)[1]))
    return d.isoformat()


class Agenda:
    def __init__(self, db, adesso=time.time):
        self.db, self.adesso = db, adesso

    # ---------- tempo ----------
    def locale(self, epoca=None):
        return datetime.fromtimestamp(self.adesso() if epoca is None else epoca, fuso())

    def oggi(self, epoca=None):
        return self.locale(epoca).strftime("%Y-%m-%d")

    def adesso_testo(self):
        """«sabato 2026-10-24 09:14»: il giorno della settimana aiuta a capire «lunedì prossimo»."""
        d = self.locale()
        return f"{GIORNI[d.weekday()]} {d.strftime('%Y-%m-%d %H:%M')}"

    def _epoca(self, giorno, ora):
        d = datetime.strptime(f"{giorno} {ora or ORA_TUTTO_IL_GIORNO}", "%Y-%m-%d %H:%M")
        return d.replace(tzinfo=fuso()).timestamp() if fuso() else time.mktime(d.timetuple())

    def etichetta(self, giorno, ora="", epoca=None):
        """«oggi 09:30», «domani», «giovedì 29/10 15:00»."""
        oggi = self.oggi(epoca)
        d, delta = date.fromisoformat(giorno), (date.fromisoformat(giorno) - date.fromisoformat(oggi)).days
        nome = {0: "oggi", 1: "domani", -1: "ieri"}.get(delta) or f"{GIORNI[d.weekday()]} {d.day:02d}/{d.month:02d}"
        return nome + (f" {ora}" if ora else "")

    # ---------- voci ----------
    @staticmethod
    def _voce(r):
        return {k: r[k] for k in ("id", "titolo", "giorno", "ora", "tipo", "note", "ripeti", "preavviso", "stato", "origine")}

    def _controlla(self, titolo, tipo, ripeti, preavviso):
        titolo = " ".join(str(titolo or "").split())
        if not 2 <= len(titolo) <= 120:
            raise ValueError("Il titolo deve avere da 2 a 120 caratteri.")
        if tipo not in TIPI:
            raise ValueError("Il tipo è promemoria oppure evento.")
        if ripeti not in RIPETIZIONI:
            raise ValueError("La ripetizione può essere: giornaliero, settimanale, mensile (o nessuna).")
        try:
            preavviso = int(preavviso or 0)
        except (TypeError, ValueError):
            raise ValueError("Il preavviso è un numero di minuti.") from None
        if not 0 <= preavviso <= 7 * 24 * 60:
            raise ValueError("Il preavviso va da 0 minuti a una settimana (10080).")
        return titolo, preavviso

    def aggiungi(self, titolo, quando, tipo="promemoria", note="", ripeti="", preavviso=0, origine="utente"):
        titolo, preavviso = self._controlla(titolo, tipo, ripeti, preavviso)
        giorno, ora = leggi_quando(quando)
        if self._epoca(giorno, ora) < self.adesso() - (3600 if ora else 86400):
            raise ValueError("Questa data è già passata: controlla giorno e ora.")
        if self.db.uno("SELECT COUNT(*) AS n FROM eventi WHERE stato='attivo'")["n"] >= MAX_VOCI_ATTIVE:
            raise ValueError("Ci sono troppe voci attive: chiudine o cancellane qualcuna.")
        cur = self.db.esegui("INSERT INTO eventi (ts, titolo, giorno, ora, tipo, note, ripeti, preavviso, origine) VALUES (?,?,?,?,?,?,?,?,?)",
                             (int(self.adesso()), titolo, giorno, ora, tipo, " ".join(str(note or "").split())[:300], ripeti, preavviso, origine[:30]))
        return self.voce(cur.lastrowid)

    def voce(self, id_):
        r = self.db.uno("SELECT * FROM eventi WHERE id=?", (int(id_),))
        if not r:
            raise LookupError(f"Nessuna voce con id {id_}: usa un id dall'elenco dell'agenda.")
        return self._voce(r)

    def modifica(self, id_, titolo=None, quando=None, note=None, tipo=None, ripeti=None, preavviso=None):
        v = self.voce(id_)
        nuovo = {"titolo": titolo if titolo is not None else v["titolo"], "tipo": tipo or v["tipo"],
                 "ripeti": v["ripeti"] if ripeti is None else ripeti, "preavviso": v["preavviso"] if preavviso is None else preavviso}
        nuovo["titolo"], nuovo["preavviso"] = self._controlla(nuovo["titolo"], nuovo["tipo"], nuovo["ripeti"], nuovo["preavviso"])
        giorno, ora = leggi_quando(quando) if quando else (v["giorno"], v["ora"])
        if quando and self._epoca(giorno, ora) < self.adesso() - (3600 if ora else 86400):
            raise ValueError("Questa data è già passata: controlla giorno e ora.")
        spostata = (giorno, ora) != (v["giorno"], v["ora"]) or nuovo["preavviso"] != v["preavviso"]
        self.db.esegui("UPDATE eventi SET titolo=?, giorno=?, ora=?, tipo=?, ripeti=?, preavviso=?, note=?, stato='attivo'"
                       + (", avvisato=0" if spostata else "") + " WHERE id=?",
                       (nuovo["titolo"], giorno, ora, nuovo["tipo"], nuovo["ripeti"], nuovo["preavviso"],
                        v["note"] if note is None else " ".join(str(note).split())[:300], int(id_)))
        return self.voce(id_)

    def fatto(self, id_):
        v = self.voce(id_)
        if v["ripeti"]:  # ricorrente: si passa alla prossima volta
            self._avanza(v)
            return self.voce(id_)
        self.db.esegui("UPDATE eventi SET stato='fatto' WHERE id=?", (int(id_),))
        return self.voce(id_)

    def elimina(self, id_):
        self.voce(id_)
        self.db.esegui("DELETE FROM eventi WHERE id=?", (int(id_),))

    def _avanza(self, v):
        giorno = v["giorno"]
        for _ in range(800):
            giorno = _avanti(giorno, v["ripeti"])
            if self._epoca(giorno, v["ora"]) - v["preavviso"] * 60 > self.adesso():
                break
        self.db.esegui("UPDATE eventi SET giorno=?, avvisato=0 WHERE id=?", (giorno, v["id"]))

    # ---------- elenchi ----------
    def elenco(self, giorni=14, fatti=8):
        """{'oggi', 'scaduti', 'prossimi', 'fatti'}: scaduti = attivi già passati e non chiusi."""
        ora = self.locale()
        oggi, fine = ora.strftime("%Y-%m-%d"), (ora + timedelta(days=int(giorni))).strftime("%Y-%m-%d")
        adesso_hm = ora.strftime("%H:%M")
        attivi = [self._voce(r) for r in self.db.tutti("SELECT * FROM eventi WHERE stato='attivo' ORDER BY giorno, ora='' DESC, ora, id")]
        passato = lambda v: v["giorno"] < oggi or (v["giorno"] == oggi and v["ora"] and v["ora"] < adesso_hm)
        for v in attivi:
            v["etichetta"] = self.etichetta(v["giorno"], v["ora"])
        return {"oggi": oggi,
                "scaduti": [v for v in attivi if passato(v) and not v["ripeti"]],
                "prossimi": [v for v in attivi if not (passato(v) and not v["ripeti"]) and v["giorno"] <= fine],
                "fatti": [self._voce(r) for r in self.db.tutti("SELECT * FROM eventi WHERE stato='fatto' ORDER BY id DESC LIMIT ?", (fatti,))]}

    def testo(self, giorni=14):
        e = self.elenco(giorni, fatti=0)
        riga = lambda v: f"- id {v['id']} · {self.etichetta(v['giorno'], v['ora'])} · {v['titolo']}" \
                         + (f" ({v['tipo']})" if v["tipo"] != "promemoria" else "") + (f" · si ripete: {v['ripeti']}" if v["ripeti"] else "") \
                         + (f" · {v['note']}" if v["note"] else "")
        parti = []
        if e["scaduti"]:
            parti.append("SCADUTI (da chiudere o spostare):\n" + "\n".join(riga(v) for v in e["scaduti"]))
        parti.append(f"PROSSIMI {giorni} GIORNI:\n" + ("\n".join(riga(v) for v in e["prossimi"]) or "nessuna voce"))
        return "\n".join(parti)

    def contesto(self, ore=36, massimo=6):
        """Poche righe per Ada: quello che sta per succedere, senza doverle chiedere ogni volta."""
        e = self.elenco(2, fatti=0)
        limite = (self.locale() + timedelta(hours=ore)).strftime("%Y-%m-%d %H:%M")
        vicini = [v for v in e["prossimi"] if f"{v['giorno']} {v['ora'] or '23:59'}" <= limite][:massimo]
        if not (vicini or e["scaduti"]):
            return ""
        righe = [f"{self.etichetta(v['giorno'], v['ora'])} {v['titolo']} (id {v['id']})" for v in vicini]
        return ("AGENDA: " + "; ".join(righe) + ("." if righe else "") +
                (f" Scaduti non chiusi: {len(e['scaduti'])}." if e["scaduti"] else ""))

    # ---------- avvisi ----------
    def da_avvisare(self, adesso=None):
        """Voci da segnalare ora: l'ora dell'avviso (ora della voce meno il preavviso) è arrivata. Quelle troppo vecchie si saltano."""
        adesso = self.adesso() if adesso is None else adesso
        out = []
        for r in self.db.tutti("SELECT * FROM eventi WHERE stato='attivo' AND avvisato=0 ORDER BY giorno, ora"):
            v = self._voce(r)
            quando = self._epoca(v["giorno"], v["ora"])
            avviso = quando - v["preavviso"] * 60
            if avviso > adesso:
                continue
            if adesso - avviso > ATTESA_MAX_AVVISO and not v["ripeti"]:
                self.db.esegui("UPDATE eventi SET avvisato=1 WHERE id=?", (v["id"],))  # troppo tardi: resta tra gli scaduti
                continue
            v["in_ritardo"] = adesso - avviso > 3600
            out.append(v)
        return out

    def segna_avvisato(self, id_, adesso=None):
        v = self.voce(id_)
        if v["ripeti"]:
            self._avanza(v)
        else:
            self.db.esegui("UPDATE eventi SET avvisato=1 WHERE id=?", (int(id_),))

    def riepilogo_mattina(self):
        """(titolo, testo) per la notifica del mattino, oppure None se oggi non c'è niente."""
        e = self.elenco(0, fatti=0)
        oggi = [v for v in e["prossimi"] if v["giorno"] == e["oggi"]]
        if not (oggi or e["scaduti"]):
            return None
        parti = [f"{v['ora'] or 'tutto il giorno'} {v['titolo']}" for v in oggi]
        testo = (f"{len(oggi)} oggi: " + "; ".join(parti) if oggi else "")
        if e["scaduti"]:
            testo += ("; " if testo else "") + f"{len(e['scaduti'])} da chiudere"
        return "Agenda di oggi", testo[:120]
