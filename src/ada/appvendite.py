"""Il messaggero dell'app «Andamento vendite»: ogni cambiamento fatto nell'app arriva ad Ada come messaggio firmato.

L'app (aperta sul PC o sul telefono) manda alla Gmail dell'utente un messaggio con oggetto
«[ADA] v1|tipo|cliente|dettaglio|data|ora|chiave|id|firma». Ada lo legge dalle notifiche del telefono, insieme a quelle di
Revolut, controlla la firma (un codice che conoscono solo l'app e Ada), lo annota nel diario o nell'agenda e avvisa l'utente.
Nessun messaggio firmato bene, nessuna azione: chiunque può scrivere «[ADA]» in una mail, ma non può firmarla.
"""
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from datetime import date, datetime

TIPI = ("preventivo", "vendita", "perso", "chiamata", "test_drive", "pagamento", "appuntamento", "richiamo", "ping")
DIARIO = ("preventivo", "vendita", "perso", "chiamata", "test_drive", "pagamento")
AGENDA = ("appuntamento", "richiamo")
CAMPO = r"\|[^|\[\]\r\n]{0,80}"
MESSAGGIO = re.compile(r"\[ADA\]\s*(v1(?:" + CAMPO + r"){8})")
LUNGHEZZA_FIRMA = 10
NOME_UTENTE = os.environ.get("ADA_NOME", "Thomas")
SINGOLARE = {"preventivo": "un preventivo", "vendita": "una vendita", "perso": "un cliente perso", "chiamata": "una chiamata",
             "test_drive": "un test drive", "pagamento": "un pagamento", "appuntamento": "un appuntamento", "richiamo": "un richiamo"}
PLURALE = {"preventivo": "preventivi", "vendita": "vendite", "perso": "clienti persi", "chiamata": "chiamate", "test_drive": "test drive",
           "pagamento": "pagamenti", "appuntamento": "appuntamenti", "richiamo": "richiami"}


def firma(segreto, parti):
    """Firma di un messaggio: i primi 10 caratteri dell'HMAC-SHA256 di «v1|tipo|…|id» (l'app calcola la stessa cosa)."""
    return hmac.new(segreto.encode(), "|".join(parti).encode(), hashlib.sha256).hexdigest()[:LUNGHEZZA_FIRMA]


def componi(segreto, tipo, cliente="", dettaglio="", data="", ora="", chiave="", id_=""):
    """Il messaggio come lo scrive l'app (serve ai test e a chi vuole provare a mano)."""
    parti = ["v1", tipo, cliente, dettaglio, data, ora, chiave, id_]
    return "[ADA] " + "|".join(parti + [firma(segreto, parti)])


def _testi(notifica):
    return [v for k, v in notifica.items() if isinstance(v, str) and k != "packageName"]


class AppVendite:
    def __init__(self, ada):
        self.ada = ada

    # ---------- stato e codice ----------
    def _kv(self, chiave, default=None):
        r = self.ada.db.uno("SELECT valore FROM kv WHERE chiave=?", (chiave,))
        return json.loads(r["valore"]) if r else default

    def _imposta(self, chiave, valore):
        self.ada.db.esegui("INSERT INTO kv (chiave, valore) VALUES (?,?) ON CONFLICT(chiave) DO UPDATE SET valore=excluded.valore",
                           (chiave, json.dumps(valore)))

    def segreto(self):
        return self._kv("vendite_segreto", "")

    def crea_segreto(self):
        """Il codice che l'utente copia nell'app una volta sola. Si crea al primo bisogno e poi resta."""
        if not self.segreto():
            self._imposta("vendite_segreto", secrets.token_urlsafe(12))
        return self.segreto()

    def stato(self):
        s = self._kv("app_stato", {})
        return {"attivo": bool(self.segreto()), "ultimo": s.get("ultimo"), "ricevuti": s.get("ricevuti", 0), "non_leggibili": s.get("non_leggibili", 0)}

    def _aggiorna_stato(self, ricevuti=0, non_leggibili=0):
        s = self._kv("app_stato", {})
        s["ricevuti"] = s.get("ricevuti", 0) + ricevuti
        s["non_leggibili"] = s.get("non_leggibili", 0) + non_leggibili
        if ricevuti:
            s["ultimo"] = int(self.ada.agenda.adesso())
        self._imposta("app_stato", s)

    # ---------- lettura dei messaggi ----------
    def _gia_visto(self, chiave):
        if self.ada.db.uno("SELECT 1 AS x FROM app_eventi WHERE chiave=?", (chiave,)):
            return True
        self.ada.db.esegui("INSERT INTO app_eventi (chiave, ts) VALUES (?,?)", (chiave, int(self.ada.agenda.adesso())))
        return False

    def leggi(self, notifiche):
        """Dai testi delle notifiche ricava i messaggi validi, mai visti prima. Conta quelli illeggibili o con la firma sbagliata."""
        segreto, validi, rotti = self.segreto(), [], 0
        for n in notifiche:
            testi = [(t, list(MESSAGGIO.finditer(t))) for t in _testi(n)]
            completo = any(trovati for _, trovati in testi)  # oggetto e anteprima del corpo: se uno è intero, l'altro tagliato non conta
            for testo, trovati in testi:
                if "[ADA]" in testo and not trovati and not completo and not self._gia_visto("x:" + hashlib.sha1(testo.encode()).hexdigest()[:16]):
                    rotti += 1  # c'è il marchio ma il messaggio è tagliato o rovinato
                for m in trovati:
                    parti = m.group(1).split("|")
                    if len(parti) != 9:
                        continue
                    ev = dict(zip(("v", "tipo", "cliente", "dettaglio", "data", "ora", "chiave", "id", "firma"), parti))
                    if not hmac.compare_digest(ev["firma"], firma(segreto, parti[:8])) or ev["tipo"] not in TIPI \
                            or not re.fullmatch(r"(\d{4}-\d{2}-\d{2})?", ev["data"]) or not re.fullmatch(r"(\d{2}:\d{2})?", ev["ora"]) or not ev["id"]:
                        if not self._gia_visto("x:" + hashlib.sha1(m.group(0).encode()).hexdigest()[:16]):
                            rotti += 1
                        continue
                    if not self._gia_visto(ev["id"]):
                        validi.append(ev)
        return validi, rotti

    # ---------- cosa ne fa Ada ----------
    def _giorno(self, data):
        oggi = self.ada.agenda.oggi()
        try:
            d = date.fromisoformat(data)
        except ValueError:
            return oggi
        return oggi if d > date.fromisoformat(oggi) or (date.fromisoformat(oggi) - d).days > 60 else data

    def _nel_diario(self, ev):
        """True se è una novità vera; se Ada la sapeva già (l'aveva raccontata l'utente) la segna solo come presente nell'app."""
        giorno, tipo, cliente, dettaglio = self._giorno(ev["data"]), ev["tipo"], ev["cliente"], ev["dettaglio"]
        if not cliente:
            return False
        db = self.ada.db
        gia = db.tutti("SELECT id, in_app, origine, ts, dettaglio FROM vendite_registro WHERE giorno=? AND tipo=? AND LOWER(cliente)=LOWER(?)",
                       (giorno, tipo, cliente))
        adesso = int(self.ada.agenda.adesso())
        if tipo in ("chiamata", "pagamento"):  # più chiamate al giorno sono normali: conta solo il doppione appena scritto da Ada
            doppie = [r for r in gia if (r["origine"] == "app" and r["dettaglio"] == dettaglio) or (r["origine"] != "app" and adesso - r["ts"] < 1200)]
        else:
            doppie = gia
        if doppie:
            for r in doppie:
                db.esegui("UPDATE vendite_registro SET in_app=1 WHERE id=?", (r["id"],))
            return False
        try:
            self.ada.diario.aggiungi(tipo, cliente, dettaglio, giorno, in_app=True, origine="app")
        except ValueError:
            return False
        return True

    def _in_agenda(self, ev):
        """Ritorna 'nuovo', 'spostato', 'tolto' oppure None se in agenda c'era già tutto. Senza data il messaggio annulla la voce."""
        ag, db = self.ada.agenda, self.ada.db
        cliente, dettaglio, data, ora = ev["cliente"], ev["dettaglio"], ev["data"], ev["ora"]
        if not data:  # nell'app il richiamo o l'appuntamento è stato tolto, fatto o annullato
            mappa = db.uno("SELECT voce FROM app_mappa WHERE chiave=?", (ev["chiave"],)) if ev["chiave"] else None
            if not mappa:
                return None
            db.esegui("DELETE FROM app_mappa WHERE chiave=?", (ev["chiave"],))
            try:
                if ag.voce(mappa["voce"])["stato"] != "attivo":
                    return None
                ag.elimina(mappa["voce"])
            except LookupError:
                return None
            return "tolto"
        if ev["tipo"] == "richiamo":
            titolo, tipo_voce, preavviso = f"Richiamare {cliente}"[:120], "promemoria", 0
            ora = ""
        else:
            titolo = (f"{dettaglio or 'Appuntamento'}: {cliente}" if cliente else (dettaglio or "Appuntamento"))[:120]
            tipo_voce, preavviso = "evento", 30 if ora else 0
        quando = data + (f" {ora}" if ora else "")
        mappa = db.uno("SELECT voce FROM app_mappa WHERE chiave=?", (ev["chiave"],)) if ev["chiave"] else None
        if mappa:
            try:
                v = ag.voce(mappa["voce"])
            except LookupError:
                v = None
            if v and v["stato"] == "attivo":
                if (v["giorno"], v["ora"], v["titolo"]) == (data, ora, titolo):
                    return None
                try:
                    ag.modifica(v["id"], titolo=titolo, quando=quando)
                except ValueError:
                    return None
                return "spostato"
        doppia = db.uno("SELECT id FROM eventi WHERE stato='attivo' AND giorno=? AND ora=? AND LOWER(titolo)=LOWER(?)", (data, ora, titolo))
        if doppia:
            if ev["chiave"]:
                db.esegui("INSERT OR REPLACE INTO app_mappa (chiave, voce) VALUES (?,?)", (ev["chiave"], doppia["id"]))
            return None
        try:
            v = ag.aggiungi(titolo, quando, tipo_voce, "", "", preavviso, origine="app")
        except ValueError:  # data già passata: niente da ricordare
            return None
        if ev["chiave"]:
            db.esegui("INSERT OR REPLACE INTO app_mappa (chiave, voce) VALUES (?,?)", (ev["chiave"], v["id"]))
        return "nuovo"

    def _riga(self, ev, esito):
        c, d = ev["cliente"] or "?", f" ({ev['dettaglio']})" if ev["dettaglio"] else ""
        quando = self.ada.agenda.etichetta(ev["data"], ev["ora"]) if ev["data"] else ""
        if esito == "tolto":
            return f"{'richiamo' if ev['tipo'] == 'richiamo' else 'appuntamento'} di {c}: tolto dall'agenda, l'hai cancellato o chiuso nell'app"
        return {"preventivo": f"preventivo di {c}{d}: segnato nel diario", "vendita": f"vendita a {c}{d}: segnata nel diario",
                "perso": f"{c} perso{d}: segnato nel diario", "chiamata": f"chiamata a {c}{d}: segnata nel diario",
                "test_drive": f"test drive fatto con {c}: segnato nel diario", "pagamento": f"pagamento di {c}{d}: segnato nel diario",
                "appuntamento": f"{ev['dettaglio'] or 'appuntamento'} con {c}, {quando}: " + ("spostato in agenda" if esito == "spostato" else "messo in agenda"),
                "richiamo": f"richiamo di {c}, {quando}: " + ("spostato in agenda" if esito == "spostato" else "messo in agenda")}[ev["tipo"]]

    def _avviso(self, conteggi):
        voci = [f"{n} {PLURALE[t]}" if n > 1 else SINGOLARE[t] for t, n in conteggi.items()]
        elenco = voci[0] if len(voci) == 1 else ", ".join(voci[:-1]) + " e " + voci[-1]
        unico = sum(conteggi.values()) == 1
        segnato = "li ho segnati" if not unico else ("l'ho segnata" if "vendita" in conteggi or "chiamata" in conteggi else "l'ho segnato")
        corpo = f"Hei {NOME_UTENTE}, " + ("bravo! Ho" if "vendita" in conteggi else "ho") + f" visto che hai aggiunto {elenco}: {segnato}."
        if len(corpo) > 120:
            corpo = f"Hei {NOME_UTENTE}, ho visto {sum(conteggi.values())} novità nell'app vendite: le ho segnate."
        return corpo

    def elabora(self, notifiche):
        """Legge le notifiche, applica i messaggi nuovi e avvisa l'utente. Ritorna la frase per il registro, o '' se non c'è niente."""
        if not self.segreto():
            return ""
        validi, rotti = self.leggi(notifiche)
        self._aggiorna_stato(len(validi), rotti)
        righe, conteggi, ping = [], {}, False
        for ev in validi:
            if ev["tipo"] == "ping":
                ping = True
                continue
            esito = self._in_agenda(ev) if ev["tipo"] in AGENDA else ("nuovo" if self._nel_diario(ev) else None)
            if esito:
                righe.append(self._riga(ev, esito))
                if esito != "tolto":
                    conteggi[ev["tipo"]] = conteggi.get(ev["tipo"], 0) + 1
        if ping:
            self.ada.avvisa("App vendite", f"Hei {NOME_UTENTE}, il collegamento con l'app vendite funziona!", "ada-app-vendite")
            self.ada._dici("Il collegamento con l'app Andamento vendite funziona: ho ricevuto il messaggio di prova.")
            self.ada.log("app vendite", "collegamento provato", "ok")
        if conteggi:
            self.ada.avvisa("Ada ha visto una novità", self._avviso(conteggi), "ada-app-vendite")
        if righe:  # chi toglie qualcosa dall'app non riceve una notifica: la riga resta in chat e nel registro
            self.ada._dici("Ho visto che nell'app vendite " + ("hai aggiunto" if conteggi else "è cambiato") + ":\n" + "\n".join("• " + r for r in righe))
            self.ada.log("app vendite", "novità dall'app", "; ".join(righe)[:300])
        nuove = sum(conteggi.values())
        parti = ([f"{nuove} novità dall'app"] if nuove else []) + ([f"{len(righe) - nuove} tolte dall'agenda"] if len(righe) > nuove else []) \
            + (["collegamento provato"] if ping else []) + ([f"{rotti} messaggi non leggibili"] if rotti else [])
        return " · ".join(parti)
