"""Server dell'hub: serve l'app (cartella app/) e l'API JSON di Ada.

Avvio:  python -m src.ada.server
Sicurezza: ascolta solo su 127.0.0.1; fuori dal telefono serve ADA_TOKEN.
"""
import hmac
import json
import mimetypes
import os
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .agenti import AGENTI, Squadra
from .cervello import Ada
from .db import DB, casa
from .llm import Claude
from .soldi import Soldi
from ..telefono.adb import Adb
from ..telefono.mano import Mano

WEB = Path(__file__).resolve().parents[2] / "app"
LOOPBACK = ("127.0.0.1", "localhost", "::1")
CSP = "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; frame-ancestors 'none'"


class Contesto:
    def __init__(self, ada, db, squadra, soldi, token="", web=WEB):
        self.ada, self.db, self.squadra, self.soldi, self.token, self.web = ada, db, squadra, soldi, token, web

    def stato(self):
        ora = int(time.time())
        agenti = []
        for nome, (titolo, descr) in AGENTI.items():
            ult = self.db.uno("SELECT ts, azione FROM attivita WHERE agente=? ORDER BY id DESC LIMIT 1", (nome,))
            agenti.append({
                "nome": nome, "titolo": titolo, "descrizione": descr,
                "ultima_attivita": ult,
                "attivo": bool(ult and ora - ult["ts"] < 300),
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
        }


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

        def _corpo(self):
            if "application/json" not in self.headers.get("Content-Type", ""):
                raise ValueError("Content-Type deve essere application/json.")
            n = int(self.headers.get("Content-Length") or 0)
            if n > 65536:
                raise ValueError("Richiesta troppo grande.")
            return json.loads(self.rfile.read(n) or b"{}")

        def do_GET(self):
            path = self.path.split("?")[0]
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
                corpo = self._corpo() if metodo == "POST" else {}
                self._invia(200, self._rotta(metodo, path, corpo))
            except LookupError as e:
                self._invia(404, {"errore": str(e)})
            except (ValueError, KeyError, TypeError) as e:
                self._invia(400, {"errore": str(e)})
            except Exception as e:
                ctx.ada.log("sistema", "errore", f"{type(e).__name__}: {e}")
                self._invia(500, {"errore": "errore interno"})

        def _rotta(self, metodo, path, corpo):
            if metodo == "GET" and path == "/api/stato":
                return ctx.stato()
            if metodo == "GET" and path == "/api/chat":
                return {"messaggi": ctx.db.tutti("SELECT ts, ruolo, testo FROM chat ORDER BY id DESC LIMIT 50")[::-1]}
            if metodo == "POST" and path == "/api/chat":
                return {"risposta": ctx.ada.chiacchiera(corpo.get("messaggio", ""))}
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
                return {"nome": m.group(1), "prompt": ctx.squadra.prompt(m.group(1)),
                        "miglioramenti": ctx.db.tutti(
                            "SELECT id, ts, motivo, tipo, stato FROM miglioramenti WHERE agente=? ORDER BY id DESC LIMIT 10",
                            (m.group(1),))}
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
    ada = Ada(db, squadra, soldi, llm or Claude())
    ada.mano = Mano(Adb(seriale=os.environ.get("ADA_ADB_SERIALE") or None),
                    autorizzato=ada.autorizzazione_attiva, log=ada.log)
    return Contesto(ada, db, squadra, soldi, os.environ.get("ADA_TOKEN", "") if token is None else token)


def main():
    host, porta = os.environ.get("ADA_HOST", "127.0.0.1"), int(os.environ.get("ADA_PORT", "8765"))
    ctx = costruisci()
    if host not in LOOPBACK and not ctx.token:
        sys.exit("Rifiuto di partire su una rete aperta senza ADA_TOKEN: imposta un token o usa ADA_HOST=127.0.0.1.")
    srv = crea_server(ctx, host, porta)
    print(f"Ada è pronta su http://{host}:{porta}  (cervello: {'collegato' if ctx.ada.llm.disponibile else 'NON collegato'})", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nAda si ferma.")


if __name__ == "__main__":
    main()
