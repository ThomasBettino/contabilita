"""Diario di lavoro dell'utente: preventivi, vendite, chiamate, test drive, appuntamenti, clienti persi, pagamenti.

L'utente racconta tutto ad Ada e non tocca più l'app delle vendite: il diario è la memoria di Ada, funziona anche quando lo
schermo non è collegato, ed è da qui che nasce il riepilogo delle 18:55.
"""
from datetime import date, timedelta

TIPI = ("preventivo", "vendita", "chiamata", "test_drive", "appuntamento", "perso", "pagamento", "altro")
UNICI = ("preventivo", "vendita", "perso", "test_drive")  # lo stesso cliente non conta due volte nello stesso giorno
ETICHETTE = {"preventivo": ("preventivo", "preventivi"), "vendita": ("vendita", "vendite"), "chiamata": ("chiamata", "chiamate"),
             "test_drive": ("test drive", "test drive"), "appuntamento": ("appuntamento", "appuntamenti"),
             "perso": ("cliente perso", "clienti persi"), "pagamento": ("pagamento", "pagamenti"), "altro": ("altro", "altro")}
GIORNI = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
MAX_GIORNI_INDIETRO = 60


def quanti(n, tipo):
    una, molte = ETICHETTE[tipo]
    return f"{n} {una if n == 1 else molte}"


class Diario:
    def __init__(self, db, agenda):
        self.db, self.agenda = db, agenda

    def aggiungi(self, tipo, cliente="", dettaglio="", giorno=None, in_app=False, origine="clienti_vendite"):
        if tipo not in TIPI:
            raise ValueError("Il tipo è uno fra: " + ", ".join(TIPI) + ".")
        cliente, dettaglio = " ".join(str(cliente or "").split()), " ".join(str(dettaglio or "").split())
        if len(cliente) > 80 or len(dettaglio) > 200:
            raise ValueError("Cliente al massimo 80 caratteri, dettaglio al massimo 200.")
        if tipo != "altro" and not cliente:
            raise ValueError("Serve il nome del cliente.")
        oggi = self.agenda.oggi()
        giorno = str(giorno or oggi)
        try:
            d = date.fromisoformat(giorno)
        except ValueError:
            raise ValueError("Il giorno va scritto così: 2026-10-24.") from None
        if d > date.fromisoformat(oggi):
            raise ValueError("Il giorno non può essere nel futuro: per le cose da fare usa l'agenda.")
        if d < date.fromisoformat(oggi) - timedelta(days=MAX_GIORNI_INDIETRO):
            raise ValueError(f"Il giorno è troppo vecchio (massimo {MAX_GIORNI_INDIETRO} giorni fa).")
        if tipo in UNICI:
            doppio = self.db.uno("SELECT id FROM vendite_registro WHERE giorno=? AND tipo=? AND LOWER(cliente)=LOWER(?)", (giorno, tipo, cliente))
            if doppio:
                raise ValueError(f"C'è già: {tipo.replace('_', ' ')} di {cliente} il {giorno} (id {doppio['id']}). Non lo registro due volte.")
        cur = self.db.esegui("INSERT INTO vendite_registro (ts, giorno, tipo, cliente, dettaglio, in_app, origine) VALUES (?,?,?,?,?,?,?)",
                             (int(self.agenda.adesso()), giorno, tipo, cliente, dettaglio, 1 if in_app else 0, origine[:30]))
        return self.voce(cur.lastrowid)

    def voce(self, id_):
        r = self.db.uno("SELECT * FROM vendite_registro WHERE id=?", (int(id_),))
        if not r:
            raise LookupError(f"Nessuna voce con id {id_} nel diario.")
        return r

    def annulla(self, id_):
        self.voce(id_)
        self.db.esegui("DELETE FROM vendite_registro WHERE id=?", (int(id_),))

    def elenco(self, giorno=None):
        return self.db.tutti("SELECT * FROM vendite_registro WHERE giorno=? ORDER BY id", (giorno or self.agenda.oggi(),))

    def conteggi(self, giorno=None):
        c = {}
        for v in self.elenco(giorno):
            c[v["tipo"]] = c.get(v["tipo"], 0) + 1
        return c

    def testo(self, giorno=None):
        voci = self.elenco(giorno)
        if not voci:
            return "Diario vuoto per questo giorno."
        return "\n".join(f"- id {v['id']} · {v['tipo'].replace('_', ' ')} · {v['cliente'] or '-'}" + (f" · {v['dettaglio']}" if v["dettaglio"] else "")
                         + ("" if v["in_app"] else " · NON ancora nell'app") for v in voci)

    def contesto(self):
        """Una riga per Ada: com'è andata la giornata finora, così risponde senza dover cercare."""
        c = self.conteggi()
        return ("DIARIO DI OGGI: " + ", ".join(quanti(n, t) for t, n in c.items() if n) + ".") if c else ""

    def _giorno_lungo(self, giorno):
        d = date.fromisoformat(giorno)
        return f"{GIORNI[d.weekday()]} {d.day}/{d.month}"

    def riepilogo_sera(self):
        """(messaggio per la chat, testo breve e generico per la notifica) delle 18:55."""
        oggi = self.agenda.oggi()
        domani = (date.fromisoformat(oggi) + timedelta(days=1)).isoformat()
        voci = self.elenco(oggi)
        per_tipo = lambda t: [v for v in voci if v["tipo"] == t]
        righe = [f"Riepilogo vendite di oggi, {self._giorno_lungo(oggi)}:"]
        prev, vend = per_tipo("preventivo"), per_tipo("vendita")
        righe.append(f"• Preventivi fatti: {len(prev)}")
        righe.append(f"• Vendite: {len(vend)}" + (" (" + ", ".join(v["cliente"] for v in vend) + ")" if vend else ""))
        for tipo in ("chiamata", "test_drive", "appuntamento", "pagamento", "perso"):
            if (n := len(per_tipo(tipo))):
                righe.append(f"• {quanti(n, tipo).capitalize()}")
        coda = self.db.uno("SELECT COUNT(*) AS n FROM vendite_coda WHERE stato='da_riportare'")["n"]
        non_app = sum(1 for v in voci if not v["in_app"])
        if coda or non_app:
            righe.append(f"• Da riportare nell'app: {max(coda, non_app)} (li trovi in Agenda, Reparto vendite)")
        agenda = self.agenda.elenco(2, fatti=0)
        domani_voci = [v for v in agenda["prossimi"] if v["giorno"] == domani]
        righe.append(f"Per domani, {self._giorno_lungo(domani)}:")
        righe += [f"• {v['ora'] or 'tutto il giorno'} {v['titolo']}" + (f" ({v['note']})" if v["note"] else "") for v in domani_voci] \
            or ["• Niente in agenda."]
        if agenda["scaduti"]:
            righe.append(f"Hai {len(agenda['scaduti'])} cose scadute da chiudere o spostare.")
        notifica = (f"Oggi: {quanti(len(prev), 'preventivo')}, {quanti(len(vend), 'vendita')}. "
                    f"Domani: {len(domani_voci)} in agenda.")[:120]
        return "\n".join(righe), notifica
