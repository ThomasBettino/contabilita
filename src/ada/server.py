"""Server dell'hub: serve l'app (cartella app/) e l'API JSON di Ada.

Avvio:  python -m src.ada.server
Sicurezza: ascolta solo su 127.0.0.1; fuori dal telefono serve ADA_TOKEN.
"""
import hmac
import json
import mimetypes
import os
import re
import shutil
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

from .agenti import AGENTI, Squadra
from .cervello import Ada, strumenti_di
from .collaudo import Collaudo
from .studio import Studio
from .db import DB, casa
from . import aggiornamento
from .fatture import HOST_SCRIPT, Archivio, ClienteScript, Config, ErroreFatture
from .segreti import Segreti
from .llm import Claude
from .notifica import Notifica
from .pianificatore import RITMI, Pianificatore
from .soldi import Soldi
from ..revolut.ingest import leggi_notifiche_termux
from ..telefono.adb import Adb
from ..telefono.mano import Mano

WEB = Path(__file__).resolve().parents[2] / "app"
LOOPBACK = ("127.0.0.1", "localhost", "::1")
CSP = "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; frame-ancestors 'none'"


class Contesto:
    def __init__(self, ada, db, squadra, soldi, token="", web=WEB, pian=None, segreti=None):
        self.ada, self.db, self.squadra, self.soldi, self.token, self.web = ada, db, squadra, soldi, token, web
        self.pian, self.segreti, self.nuovo_cliente = pian, segreti, ClienteScript
        # punti di aggancio sostituibili nei test
        self.fn_aggiorna, self.fn_riavvia = aggiornamento.aggiorna, aggiornamento.riavvia_tra
        self._versione = None

    def versione(self):
        self._versione = self._versione or aggiornamento.versione()
        return self._versione

    def collaudi_stato(self):
        out = self.db.tutti("SELECT id, ts, categoria, richiesta, trascrizione, voto, problemi FROM collaudi ORDER BY id DESC LIMIT 8")
        for c in out:
            c["problemi"] = json.loads(c["problemi"] or "[]")
        return out

    def agenda_stato(self):
        e = self.ada.agenda.elenco(0, fatti=0)
        return {"scaduti": len(e["scaduti"]), "oggi": sum(1 for v in e["prossimi"] if v["giorno"] == e["oggi"])}

    def vendite_stato(self):
        return {"url": self.ada.vendite_url(),
                "coda": self.db.tutti("SELECT id, ts, frase, riassunto FROM vendite_coda WHERE stato='da_riportare' ORDER BY id"),
                "fatte": self.db.tutti("SELECT id, ts_stato, riassunto FROM vendite_coda WHERE stato='fatto' ORDER BY ts_stato DESC LIMIT 5")}

    def idee_stato(self):
        out = self.db.tutti("SELECT id, ts, titolo, descrizione, motivo, stato FROM idee ORDER BY id DESC LIMIT 15")
        for i in out:
            i["brief"] = brief_idea(i)
        return out

    def fatture_stato(self):
        a = self.ada.archivio
        if not a or not a.configurato:
            return {"configurato": False, "riepilogo": None, "elenco": [], "token_attivo": bool(self.token)}
        return {"configurato": True, "riepilogo": a.riepilogo(), "elenco": a.elenco(), "token_attivo": bool(self.token)}

    def stato(self):
        ora = int(time.time())
        agenti = []
        for nome, (titolo, descr) in AGENTI.items():
            ult = self.db.uno("SELECT ts, azione FROM attivita WHERE agente=? ORDER BY id DESC LIMIT 1", (nome,))
            agenti.append({
                "nome": nome, "titolo": titolo, "descrizione": descr,
                "ultima_attivita": ult,
                "in_corso": self.ada.lavori.get(nome),
                "attivo": nome in self.ada.lavori,
                "segnalazioni_aperte": self.db.uno(
                    "SELECT COUNT(*) AS n FROM segnalazioni WHERE agente=? AND stato='aperta'", (nome,))["n"],
                "versioni": self.db.uno(
                    "SELECT COUNT(*) AS n FROM miglioramenti WHERE agente=? AND stato='applicato'", (nome,))["n"],
            })
        appr = self.db.tutti("SELECT * FROM approvazioni WHERE stato IN ('in_attesa','scelta','autorizzata','pronto') ORDER BY id DESC")
        for a in appr:
            a["dettaglio"] = json.loads(a["dettaglio"] or "{}")
        migl = self.db.tutti("SELECT id, ts, agente, motivo, tipo, stato FROM miglioramenti ORDER BY id DESC LIMIT 20")
        return {
            "ada": {"cervello": self.ada.llm.disponibile, "modello": getattr(self.ada.llm, "modello", "")},
            "telefono": self.ada.mano.stato() if self.ada.mano else {"collegato": False, "fermo": False},
            "agenti": agenti, "approvazioni": appr, "miglioramenti": migl,
            "attivita": self.db.tutti("SELECT ts, agente, azione, dettaglio FROM attivita ORDER BY id DESC LIMIT 40"),
            "segnalazioni_aperte": self.db.uno("SELECT COUNT(*) AS n FROM segnalazioni WHERE stato='aperta'")["n"],
            "soldi": self.soldi.riepilogo("mese"),
            "routine": self.pian.elenco() if self.pian else [],
            "fatture": self.fatture_stato(),
            "idee": self.idee_stato(),
            "ritmo": {"scelto": self.pian.ritmo() if self.pian else None,
                      "opzioni": {k: {"etichetta": v["etichetta"], "descrizione": v["descrizione"]} for k, v in RITMI.items()}},
            "lettura": self.ada.soldi.stato_lettura(),
            "agenda": self.agenda_stato(),
            "vendite": {"url": bool(self.ada.vendite_url()),
                        "in_coda": self.db.uno("SELECT COUNT(*) AS n FROM vendite_coda WHERE stato='da_riportare'")["n"]},
            "collaudi": self.collaudi_stato(),
            "appunti": self.db.tutti("SELECT id, ts, tipo, titolo, testo FROM appunti ORDER BY id DESC LIMIT 8"),
            "libri": self.ada.studio.elenco_libri() if getattr(self.ada, "studio", None) else [],
            "token_attivo": bool(self.token),
            "versione": self.versione(),
            "consumo": self.ada.consumo_oggi(),
        }


def brief_idea(i) -> str:
    """Testo pronto da dare a uno sviluppatore (o a Claude Code) per realizzare l'idea."""
    return (f"Idea per l'app Ada (repository thomasbettino/contabilita, branch ccr-b35db874-occc4m).\n"
            f"Titolo: {i['titolo']}\nCosa: {i['descrizione']}\nPerché: {i['motivo']}\n"
            "Vincoli: non toccare i confini di sicurezza (src/telefono/guardiano.py, REGOLE in src/ada/agenti.py); "
            "aggiungere test; testi in italiano; non aggiungere dipendenze.")


def crea_handler(ctx):
    class Handler(BaseHTTPRequestHandler):
        server_version = "Ada"

        def log_message(self, *a):
            pass

        def _invia(self, codice, corpo, tipo="application/json"):
            if not isinstance(corpo, bytes):
                corpo = json.dumps(corpo, ensure_ascii=False).encode()
            self.send_response(codice)
            self.send_header("Content-Type", tipo + ("; charset=utf-8" if tipo.startswith("text") or "json" in tipo else ""))
            self.send_header("Content-Length", str(len(corpo)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", CSP)
            self.end_headers()
            self.wfile.write(corpo)

        def _ok_accesso(self):
            if ctx.token:
                dato = self.headers.get("Authorization", "").removeprefix("Bearer ")
                return hmac.compare_digest(dato, ctx.token)
            # senza token: solo loopback, e il Host deve essere locale (difesa da DNS rebinding)
            host = re.sub(r":\d+$", "", self.headers.get("Host", "")).strip("[]")
            return host in LOOPBACK

        def _corpo(self, massimo=65536):
            if "application/json" not in self.headers.get("Content-Type", ""):
                raise ValueError("Content-Type deve essere application/json.")
            n = int(self.headers.get("Content-Length") or 0)
            if n > massimo:
                restante = min(n, 20_000_000)  # si legge e si butta, così chi invia riceve la risposta e non un errore di rete
                while restante > 0:
                    restante -= len(self.rfile.read(min(65536, restante)) or b"\0" * restante)
                raise ValueError("Richiesta troppo grande." if massimo <= 65536 else "Il file è troppo grande: carica un periodo più corto.")
            return json.loads(self.rfile.read(n) or b"{}")

        def do_GET(self):
            path = self.path.split("?")[0]
            self.query = parse_qs(self.path.partition("?")[2])
            if path.startswith("/api/"):
                return self._api("GET", path)
            rel = "index.html" if path == "/" else path.lstrip("/")
            f = (ctx.web / rel).resolve()
            if ctx.web.resolve() not in f.parents or not f.is_file():
                return self._invia(404, {"errore": "non trovato"})
            self._invia(200, f.read_bytes(), mimetypes.guess_type(f.name)[0] or "application/octet-stream")

        def do_POST(self):
            self._api("POST", self.path.split("?")[0])

        def _api(self, metodo, path):
            if not self._ok_accesso():
                return self._invia(401, {"errore": "accesso negato"})
            try:
                corpo = self._corpo(3_000_000 if path == "/api/estratto" else 65536) if metodo == "POST" else {}
                self._invia(200, self._rotta(metodo, path, corpo))
            except LookupError as e:
                self._invia(404, {"errore": str(e)})
            except PermissionError as e:
                self._invia(403, {"errore": str(e)})
            except (ValueError, KeyError, TypeError) as e:
                self._invia(400, {"errore": str(e)})
            except Exception as e:
                ctx.ada.log("sistema", "errore", f"{type(e).__name__}: {e}")
                self._invia(500, {"errore": "errore interno"})

        def _rotta(self, metodo, path, corpo):
            if metodo == "GET" and path == "/api/stato":
                return ctx.stato()
            if metodo == "GET" and path == "/api/lavori":
                return {"lavori": [{"nome": n, "titolo": AGENTI[n][0], **v} for n, v in list(ctx.ada.lavori.items()) if n in AGENTI]}
            if metodo == "GET" and path == "/api/chat":
                msgs = ctx.db.tutti("SELECT ts, ruolo, testo, azioni FROM chat ORDER BY id DESC LIMIT 50")[::-1]
                for m in msgs:
                    m["azioni"] = json.loads(m["azioni"]) if m["azioni"] else []
                return {"messaggi": msgs}
            if metodo == "POST" and path == "/api/chat":
                risposta = ctx.ada.chiacchiera(corpo.get("messaggio", ""))
                ultima = ctx.db.uno("SELECT azioni FROM chat WHERE ruolo='ada' ORDER BY id DESC LIMIT 1")
                return {"risposta": risposta, "azioni": json.loads(ultima["azioni"]) if ultima and ultima["azioni"] else []}
            if path == "/api/impostazioni/fatture" and metodo == "POST":
                if not ctx.token:  # senza token qualunque app del telefono potrebbe leggere o cambiare i codici
                    raise PermissionError("Per salvare i codici nell'app serve prima un token di accesso (ADA_TOKEN: in Termux scrivi «sh scripts/token.sh», vedi docs/FATTURE.md).")
                url, tok = str(corpo.get("url", "")).strip(), str(corpo.get("token", "")).strip()
                if not url.startswith(HOST_SCRIPT) or not tok:
                    raise ValueError("L'indirizzo deve iniziare con https://script.google.com/ e il codice non può essere vuoto.")
                cliente = ctx.nuovo_cliente(url, tok)
                try:
                    cliente.chiama(action="list")  # si prova prima di salvare
                except ErroreFatture as e:
                    raise ValueError(f"Lo script non ha accettato indirizzo o codice ({e}).")
                ctx.segreti.scrivi(fatture_url=url, fatture_token=tok)
                ctx.ada.archivio.imposta(url, tok, cliente)
                ctx.db.esegui("UPDATE routine SET attiva=1 WHERE nome='fatture'")  # Ada può averla spenta quando non c'era lo script
                ctx.ada.log("utente", "archivio fatture collegato")
                return ctx.ada.archivio.sincronizza()
            if path == "/api/fatture/sincronizza" and metodo == "POST":
                a = ctx.ada.archivio
                if not a or not a.configurato:
                    raise ValueError("Archivio non configurato: vedi docs/FATTURE.md.")
                try:
                    s = a.sincronizza()
                    return {**s, "incassi": a.elabora_incassi()}
                except ErroreFatture as e:
                    raise ValueError(f"Script non raggiungibile: {e}")
            m = re.fullmatch(r"/api/fatture/([^/]+)", path)
            if metodo == "POST" and m:
                a = ctx.ada.archivio
                if not a or not a.configurato:
                    raise ValueError("Archivio non configurato.")
                try:
                    msg = a.segna_incassata(m.group(1), da="utente") if corpo.get("incassata") else a.segna_non_incassata(m.group(1))
                except ErroreFatture as e:
                    raise ValueError(f"Script non raggiungibile: {e}")
                return {"messaggio": msg}
            if metodo == "GET" and path == "/api/movimenti":
                mese = (self.query.get("mese") or [time.strftime("%Y-%m")])[0]
                return {"mese": mese, "movimenti": ctx.ada.soldi.elenco(mese)}
            if path in ("/api/movimenti", "/api/movimenti/rimuovi", "/api/estratto") and metodo == "POST":
                if not ctx.token:  # cambia i conti, e da lì le fatture da incassare: mai senza token
                    raise PermissionError("Per modificare i movimenti o caricare un estratto serve prima un token di accesso (ADA_TOKEN: in Termux scrivi «sh scripts/token.sh», vedi docs/AVVIO.md).")
                soldi = ctx.ada.soldi
                if path == "/api/movimenti":
                    m = soldi.aggiungi(corpo.get("data"), corpo.get("importo"), corpo.get("controparte"), corpo.get("tipo"))
                    ctx.ada.log("utente", "movimento aggiunto", m["controparte"])
                    return m
                if path == "/api/movimenti/rimuovi":
                    if not soldi.rimuovi(corpo.get("chiave", "")):
                        raise LookupError("Movimento non trovato (forse è già stato tolto).")
                    ctx.ada.log("utente", "movimento rimosso")
                    return {"ok": True}
                r = soldi.importa_estratto(str(corpo.get("testo", "")))
                for chiave in r.pop("chiavi_nuove"):  # i movimenti storici non devono far scattare avvisi o abbinamenti alle fatture
                    ctx.db.esegui("INSERT OR IGNORE INTO movimenti_visti VALUES (?)", (chiave,))
                ctx.ada.log("utente", "estratto conto", f"{str(corpo.get('nome', ''))[:40]}: {r['nuovi']} nuovi, {r['presenti']} già presenti")
                return r
            if metodo == "GET" and path == "/api/agenda":
                giorni = max(1, min(int((self.query.get("giorni") or ["30"])[0]), 365))
                e = ctx.ada.agenda.elenco(giorni)
                for v in e["fatti"]:
                    v["etichetta"] = ctx.ada.agenda.etichetta(v["giorno"], v["ora"])
                return e
            if metodo == "POST" and path == "/api/agenda":
                v = ctx.ada.agenda.aggiungi(corpo.get("titolo"), corpo.get("quando"), corpo.get("tipo") or "promemoria",
                                            corpo.get("note", ""), corpo.get("ripeti") or "", corpo.get("preavviso_min") or 0, origine="utente")
                ctx.ada.log("utente", "agenda", f"aggiunto: {v['titolo']}")
                return v
            m = re.fullmatch(r"/api/agenda/(\d+)", path)
            if metodo == "POST" and m:
                return {"messaggio": ctx.ada._agenda_cambia("utente", {"id": int(m.group(1)), "azione": corpo.get("azione"),
                                                                       "quando": corpo.get("quando"), "titolo": corpo.get("titolo")})}
            if metodo == "GET" and path == "/api/vendite":
                return ctx.vendite_stato()
            if metodo == "POST" and path == "/api/vendite/impostazioni":
                url = str(corpo.get("url", "")).strip()
                if url and not re.fullmatch(r"https://(claude\.ai|claude\.site)/[A-Za-z0-9_./-]{3,200}", url):
                    raise ValueError("L'indirizzo deve essere il link dell'app, per esempio https://claude.ai/artifact/…")
                ctx.db.esegui("INSERT INTO kv (chiave, valore) VALUES ('vendite_url', ?) ON CONFLICT(chiave) DO UPDATE SET valore=excluded.valore",
                              (json.dumps(url),))
                ctx.ada.log("utente", "app vendite", "indirizzo impostato" if url else "indirizzo tolto")
                return {"url": url}
            m = re.fullmatch(r"/api/vendite/coda/(\d+)", path)
            if metodo == "POST" and m:
                if corpo.get("azione") not in ("fatto", "elimina"):
                    raise ValueError("L'azione è fatto oppure elimina.")
                if not ctx.db.uno("SELECT id FROM vendite_coda WHERE id=?", (int(m.group(1)),)):
                    raise LookupError("Voce non trovata.")
                if corpo["azione"] == "fatto":
                    ctx.db.esegui("UPDATE vendite_coda SET stato='fatto', ts_stato=? WHERE id=?", (int(time.time()), int(m.group(1))))
                else:
                    ctx.db.esegui("DELETE FROM vendite_coda WHERE id=?", (int(m.group(1)),))
                return {"ok": True}
            if path == "/api/ritmo" and metodo == "POST":
                if not ctx.token:  # cambia quanto si spende: mai senza token
                    raise PermissionError("Per cambiare il ritmo di lavoro serve prima un token di accesso (ADA_TOKEN: in Termux scrivi «sh scripts/token.sh», vedi docs/AVVIO.md).")
                ctx.pian.imposta_ritmo(str(corpo.get("ritmo", "")))
                return {"scelto": ctx.pian.ritmo()}
            if path == "/api/aggiorna" and metodo == "POST":
                if not ctx.token:  # cambia il programma che gira sul telefono: mai senza token
                    raise PermissionError("Per aggiornare dall'app serve prima un token di accesso (ADA_TOKEN: in Termux scrivi «sh scripts/token.sh», vedi docs/AVVIO.md).")
                r = ctx.fn_aggiorna()
                ctx.ada.log("utente", "aggiornamento", r["messaggio"][:140])
                if r["cambiato"]:
                    ctx.fn_riavvia()
                return r
            m = re.fullmatch(r"/api/idee/(\d+)/fatta", path)
            if metodo == "POST" and m:
                ctx.ada.idea_fatta(int(m.group(1)))
                return {"ok": True}
            m = re.fullmatch(r"/api/routine/(\d+)/esegui", path)
            if metodo == "POST" and m:
                return {"esito": ctx.pian.esegui(int(m.group(1)), manuale=True)}
            m = re.fullmatch(r"/api/routine/(\d+)", path)
            if metodo == "POST" and m:
                ctx.db.esegui("UPDATE routine SET attiva=? WHERE id=?", (1 if corpo.get("attiva") else 0, int(m.group(1))))
                return {"ok": True}
            if path == "/api/telefono/collega" and metodo == "POST":
                if ctx.ada.mano is None:
                    raise ValueError("Telefono non configurato.")
                porta = corpo.get("porta")
                if porta not in (None, ""):
                    porta = int(porta)
                    if not 1024 <= porta <= 65535:
                        raise ValueError("Porta non valida.")
                else:
                    porta = None
                if ctx.ada.mano.fermo:
                    raise ValueError("Lo schermo è fermato: tocca ▶ Riattiva in alto, poi Collega schermo.")
                msg = ctx.ada.mano.collega(porta)
                ctx.ada.log("utente", "collegamento telefono", msg[:120])
                return {**ctx.ada.mano.stato(), "messaggio": msg}
            if path == "/api/telefono" and metodo == "POST":
                if ctx.ada.mano is None:
                    raise ValueError("Telefono non configurato.")
                ctx.ada.mano.fermo = bool(corpo.get("fermo"))
                ctx.ada.log("utente", "telefono fermato" if ctx.ada.mano.fermo else "telefono riattivato")
                return ctx.ada.mano.stato()
            if metodo == "POST" and path == "/api/ciclo":
                return {"risposta": ctx.ada.ciclo_miglioramento()}
            if metodo == "POST" and path == "/api/feedback":
                agente = corpo.get("agente", "")
                testo = str(corpo.get("testo", "")).strip()
                if agente not in AGENTI or not testo:
                    raise ValueError("Servono un agente valido e un testo.")
                ctx.ada.segnala(agente, testo, "utente")
                return {"ok": True}
            m = re.fullmatch(r"/api/agenti/([a-z_]+)", path)
            if metodo == "GET" and m:
                if m.group(1) not in AGENTI:
                    raise LookupError("Agente sconosciuto.")
                nome = m.group(1)
                return {"nome": nome, "titolo": AGENTI[nome][0], "descrizione": AGENTI[nome][1],
                        "prompt": ctx.squadra.prompt(nome), "in_corso": ctx.ada.lavori.get(nome),
                        "strumenti": [t["name"] for t in strumenti_di(nome)],
                        "attivita": ctx.db.tutti("SELECT ts, azione, dettaglio FROM attivita WHERE agente=? ORDER BY id DESC LIMIT 10", (nome,)),
                        "segnalazioni": ctx.db.tutti("SELECT id, problema, ts FROM segnalazioni WHERE agente=? AND stato='aperta' ORDER BY id", (nome,)),
                        "miglioramenti": ctx.db.tutti(
                            "SELECT id, ts, motivo, tipo, stato FROM miglioramenti WHERE agente=? ORDER BY id DESC LIMIT 10",
                            (nome,))}
            m = re.fullmatch(r"/api/approvazioni/(\d+)", path)
            if metodo == "POST" and m:
                if corpo.get("esito") not in ("approva", "rifiuta"):
                    raise ValueError("esito deve essere approva o rifiuta.")
                return ctx.ada.risolvi(int(m.group(1)), corpo["esito"], corpo.get("opzione"))
            m = re.fullmatch(r"/api/approvazioni/(\d+)/autorizza", path)
            if metodo == "POST" and m:
                r = ctx.ada.autorizza(int(m.group(1)))
                threading.Thread(target=ctx.ada.prepara_acquisto, args=(int(m.group(1)),), daemon=True).start()
                return r
            m = re.fullmatch(r"/api/approvazioni/(\d+)/chiudi", path)
            if metodo == "POST" and m:
                ctx.ada.chiudi_acquisto(int(m.group(1)), corpo.get("esito"))
                return {"ok": True}
            m = re.fullmatch(r"/api/miglioramenti/(\d+)/annulla", path)
            if metodo == "POST" and m:
                ctx.ada.annulla(int(m.group(1)))
                return {"ok": True}
            raise LookupError("rotta sconosciuta")

    return Handler


def crea_server(ctx, host="127.0.0.1", porta=8765):
    return ThreadingHTTPServer((host, porta), crea_handler(ctx))


def costruisci(llm=None, home=None, movimenti=None, token=None):
    home = Path(home) if home else casa()
    home.mkdir(parents=True, exist_ok=True)
    db, squadra = DB(home / "ada.db"), Squadra(home)
    soldi = Soldi(movimenti or os.environ.get("ADA_MOVIMENTI") or Path.home() / "movimenti.db")
    llm = llm or Claude()
    ada = Ada(db, squadra, soldi, llm)
    # collaudatore e giudice possono usare un modello più economico: parlano soltanto, non agiscono
    economico = Claude(chiave=llm.chiave, modello=os.environ.get("ADA_MODEL_ECONOMICO") or "claude-haiku-5-5") \
        if isinstance(llm, Claude) else llm
    ada.collaudo = Collaudo(ada, economico)
    ada.studio = Studio(ada, home / "libri")
    # le notifiche di Revolut le legge Ada stessa ogni 2 minuti (se Termux:API c'è): non dipende dallo schermo né dal lavoro di Android
    ada.lettore_notifiche = leggi_notifiche_termux if shutil.which("termux-notification-list") else None
    segreti = Segreti(home / "segreti.json")
    cfg = Config()
    salvati = segreti.leggi()
    cfg.url, cfg.token = salvati.get("fatture_url") or cfg.url, salvati.get("fatture_token") or cfg.token
    ada.archivio = Archivio(ada, ClienteScript(cfg.url, cfg.token), cfg)
    ada.mano = Mano(Adb(seriale=os.environ.get("ADA_ADB_SERIALE") or None),
                    autorizzato=ada.autorizzazione_attiva, log=ada.log)
    return Contesto(ada, db, squadra, soldi, os.environ.get("ADA_TOKEN", "") if token is None else token,
                    pian=Pianificatore(ada), segreti=segreti)


def main():
    host, porta = os.environ.get("ADA_HOST", "127.0.0.1"), int(os.environ.get("ADA_PORT", "8765"))
    ctx = costruisci()
    if host not in LOOPBACK and not ctx.token:
        sys.exit("Rifiuto di partire su una rete aperta senza ADA_TOKEN: imposta un token o usa ADA_HOST=127.0.0.1.")
    ctx.ada.notifica = Notifica(url=f"http://localhost:{porta}").invia
    ctx.pian.avvia()
    srv = crea_server(ctx, host, porta)
    print(f"Ada è pronta su http://{host}:{porta}  (cervello: {'collegato' if ctx.ada.llm.disponibile else 'NON collegato'})", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nAda si ferma.")


if __name__ == "__main__":
    main()
