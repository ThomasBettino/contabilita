import json
import sqlite3
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from src.ada import cervello
from src.ada.server import costruisci, crea_server
from src.ada.soldi import Soldi, categoria


class FinteRisposte:
    """Finto modello: restituisce risposte preparate e ricorda cosa gli è stato chiesto."""
    disponibile = True
    modello = "finto"

    def __init__(self, *risposte):
        self.risposte, self.chiamate = list(risposte), []

    def __call__(self, system, messaggi, strumenti=None, max_tokens=1500, scelta=None):
        self.chiamate.append({"system": system, "strumenti": [t["name"] for t in strumenti or []],
                              "max_tokens": max_tokens, "ultimo": messaggi[-1], "scelta": scelta})
        return self.risposte.pop(0)


def testo(t):
    return {"stop_reason": "end_turn", "content": [{"type": "text", "text": t}]}


def usa(nome, **args):
    return {"stop_reason": "tool_use", "content": [{"type": "tool_use", "id": "t1", "name": nome, "input": args}]}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)

    def ctx(self, llm, movimenti=None):
        ctx = costruisci(llm=llm, home=self.home, movimenti=movimenti or self.home / "nessuno.db", token="")
        self.addCleanup(ctx.db.c.close)
        return ctx


class TestMiglioramento(Base):
    def test_piccola_subito_grande_con_ok_e_annulla(self):
        ctx = self.ctx(FinteRisposte())
        ada, sq = ctx.ada, ctx.squadra
        vecchio = sq.prompt("revisore")
        piccolo = vecchio.rstrip() + "\n- Controlla anche gli arrotondamenti a due decimali."
        self.assertIn("applicata subito", ada._esegui("ada", "migliora_prompt",
                      {"agente": "revisore", "nuovo_prompt": piccolo, "motivo": "arrotondamenti"}))
        self.assertEqual(sq.prompt("revisore").strip(), piccolo.strip())
        mid = ctx.db.uno("SELECT id FROM miglioramenti ORDER BY id DESC")["id"]
        ada.annulla(mid)
        self.assertEqual(sq.prompt("revisore").strip(), vecchio.strip())

        grande = "# Revisore\n\n" + "Controlla tutto con la massima attenzione. " * 30
        out = ada._esegui("ada", "migliora_prompt", {"agente": "revisore", "nuovo_prompt": grande, "motivo": "riscrittura"})
        self.assertIn("serve l'ok", out)
        self.assertEqual(sq.prompt("revisore").strip(), vecchio.strip())  # non ancora applicata
        appr = ctx.db.uno("SELECT id FROM approvazioni WHERE tipo='prompt' AND stato='in_attesa'")
        ada.risolvi(appr["id"], "approva")
        self.assertEqual(sq.prompt("revisore").strip(), grande.strip())

    def test_grande_rifiutata_non_cambia_nulla(self):
        ctx = self.ctx(FinteRisposte())
        vecchio = ctx.squadra.prompt("quotidiano")
        ctx.ada._esegui("ada", "migliora_prompt", {"agente": "quotidiano", "motivo": "x",
                        "nuovo_prompt": "# Quotidiano\n" + "Nuova versione completamente diversa. " * 20})
        a = ctx.db.uno("SELECT id FROM approvazioni WHERE stato='in_attesa'")
        ctx.ada.risolvi(a["id"], "rifiuta")
        self.assertEqual(ctx.squadra.prompt("quotidiano"), vecchio)

    def test_limite_modifiche_piccole_nelle_24h(self):
        ctx = self.ctx(FinteRisposte())
        prompt = ctx.squadra.prompt("sviluppo").rstrip()
        esiti = []
        for i in range(cervello.MAX_PICCOLE_24H + 1):
            prompt += f"\n- Regola extra numero {i}."
            esiti.append(ctx.ada._esegui("ada", "migliora_prompt",
                                         {"agente": "sviluppo", "nuovo_prompt": prompt, "motivo": f"m{i}"}))
        self.assertIn("applicata subito", esiti[0])
        self.assertIn("serve l'ok", esiti[-1])

    def test_rifiuta_prompt_vuoto_e_agente_ignoto(self):
        ctx = self.ctx(FinteRisposte())
        self.assertIn("rifiutato", ctx.ada._esegui("ada", "migliora_prompt",
                                                    {"agente": "revisore", "nuovo_prompt": "ciao", "motivo": "x"}))
        self.assertIn("sconosciuto", ctx.ada._esegui("ada", "migliora_prompt",
                                                      {"agente": "../etc", "nuovo_prompt": "x" * 100, "motivo": "x"}))


class TestSoldiESicurezza(Base):
    def test_pagamento_solo_richiesta_mai_eseguito(self):
        ctx = self.ctx(FinteRisposte())
        out = ctx.ada._esegui("contabilita_piva", "richiedi_approvazione",
                              {"tipo": "pagamento", "titolo": "F24", "dettaglio": "acconto", "importo": 300})
        self.assertIn("Non è stato eseguito nulla", out)
        a = ctx.db.uno("SELECT * FROM approvazioni")
        self.assertEqual(a["stato"], "in_attesa")
        ctx.ada.risolvi(a["id"], "approva")
        log = [r["azione"] for r in ctx.db.tutti("SELECT azione FROM attivita")]
        self.assertIn("pagamento approvato", log)

    def test_assistenti_non_hanno_strumenti_di_ada(self):
        ctx = self.ctx(FinteRisposte())
        for nome in ("migliora_prompt", "delega", "chiudi_segnalazione"):
            self.assertEqual(ctx.ada._esegui("revisore", nome, {}), "Strumento non consentito.")

    def test_regole_di_sistema_sempre_nel_prompt(self):
        llm = FinteRisposte(testo("ciao"))
        ctx = self.ctx(llm)
        ctx.ada.chiacchiera("ciao")
        self.assertIn("non muovi mai denaro", llm.chiamate[0]["system"])
        self.assertIn("richiedi_approvazione", llm.chiamate[0]["strumenti"])

    def test_ada_delega_e_riporta(self):
        llm = FinteRisposte(usa("delega", agente="revisore", compito="controlla 2+2"),
                            testo("OK, il calcolo è giusto."), testo("Il revisore dice che è tutto a posto."))
        ctx = self.ctx(llm)
        self.assertEqual(ctx.ada.chiacchiera("controlla"), "Il revisore dice che è tutto a posto.")
        self.assertNotIn("migliora_prompt", llm.chiamate[1]["strumenti"])  # il revisore non li ha
        self.assertEqual(ctx.db.uno("SELECT agente FROM attivita WHERE azione='lavoro'")["agente"], "revisore")

    def test_senza_cervello_risponde_e_non_cade(self):
        class Spento(FinteRisposte):
            disponibile = False
        ctx = self.ctx(Spento())
        self.assertIn("ANTHROPIC_API_KEY", ctx.ada.chiacchiera("ciao"))

    def test_categorie_e_riepilogo(self):
        db = self.home / "mov.db"
        c = sqlite3.connect(db)
        c.execute("CREATE TABLE movimenti (chiave TEXT, quando TEXT, importo REAL, controparte TEXT, testo TEXT)")
        import time
        mese = time.strftime("%Y-%m")
        c.executemany("INSERT INTO movimenti VALUES (?,?,?,?,?)", [
            ("1", f"{mese}-02 10:00:00", -5.8, "Cristal Bar Di Wang X.", ""),
            ("2", f"{mese}-03 10:00:00", -12.0, "Esselunga", ""),
            ("3", f"{mese}-04 10:00:00", 100.0, "Mario Rossi", "")])
        c.commit()
        c.close()
        r = Soldi(db).riepilogo("mese")
        self.assertEqual((r["entrate"], r["uscite"], r["saldo"]), (100.0, 17.8, 82.2))
        self.assertEqual(r["per_categoria"][0]["nome"], "Cibo e bar")
        self.assertEqual(categoria("Lo Sconosciuto"), "Altro")
        self.assertEqual(Soldi(self.home / "manca.db").riepilogo()["movimenti"], 0)


class TestCacheLLM(unittest.TestCase):
    def llm(self, *risposte):
        import io
        from src.ada.llm import Claude
        inviati = []

        def apri(req, timeout):
            inviati.append(json.loads(req.data))
            r = risposte[min(len(inviati) - 1, len(risposte) - 1)]
            if isinstance(r, Exception):
                raise r
            return io.BytesIO(json.dumps(r).encode())
        return Claude(chiave="k", apri=apri), inviati

    def test_system_e_ultimo_strumento_vanno_in_cache(self):
        llm, inviati = self.llm({"content": []})
        llm("sono il prompt", [{"role": "user", "content": "x"}], [{"name": "a"}, {"name": "b"}])
        corpo = inviati[0]
        self.assertEqual(corpo["system"][0]["cache_control"], {"type": "ephemeral"})
        self.assertNotIn("cache_control", corpo["tools"][0])
        self.assertEqual(corpo["tools"][1]["cache_control"], {"type": "ephemeral"})

    def test_uno_strumento_puo_essere_imposto_al_modello(self):
        llm, inviati = self.llm({"content": []})
        llm("p", [{"role": "user", "content": "x"}], [{"name": "dai_voto"}], scelta="dai_voto")
        llm("p", [{"role": "user", "content": "x"}], [{"name": "dai_voto"}])
        llm("p", [{"role": "user", "content": "x"}], None, scelta="dai_voto")  # senza strumenti non c'è niente da imporre
        self.assertEqual(inviati[0]["tool_choice"], {"type": "tool", "name": "dai_voto"})
        self.assertNotIn("tool_choice", inviati[1])
        self.assertNotIn("tool_choice", inviati[2])

    def test_se_l_api_rifiuta_la_cache_si_riprova_senza(self):
        import urllib.error
        errore = urllib.error.HTTPError("u", 400, "x", {}, __import__("io").BytesIO(b'{"error":"cache_control not supported"}'))
        llm, inviati = self.llm(errore, {"content": [{"type": "text", "text": "ok"}]})
        r = llm("p", [{"role": "user", "content": "x"}], [{"name": "a"}])
        self.assertEqual(r["content"][0]["text"], "ok")
        self.assertEqual(len(inviati), 2)
        self.assertEqual(inviati[1]["system"], "p")
        self.assertFalse(llm.cache)


class TestServer(Base):
    def avvia(self, token=""):
        ctx = costruisci(llm=FinteRisposte(testo("Ciao, sono Ada.")), home=self.home,
                         movimenti=self.home / "n.db", token=token)
        self.addCleanup(ctx.db.c.close)
        srv = crea_server(ctx, "127.0.0.1", 0)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        self.addCleanup(srv.server_close)
        return f"http://127.0.0.1:{srv.server_address[1]}"

    def chiama(self, base, path, dati=None, intest=None, tipo="application/json"):
        h = dict(intest or {})
        if dati is not None:
            h["Content-Type"] = tipo
        req = urllib.request.Request(base + path, data=None if dati is None else json.dumps(dati).encode(), headers=h)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def test_pagina_stato_chat(self):
        base = self.avvia()
        code, corpo = self.chiama(base, "/")
        self.assertEqual(code, 200)
        self.assertIn(b"Ada", corpo)
        code, corpo = self.chiama(base, "/api/stato")
        self.assertEqual(code, 200)
        self.assertEqual(len(json.loads(corpo)["agenti"]), 9)
        code, corpo = self.chiama(base, "/api/chat", {"messaggio": "ciao"})
        self.assertEqual(json.loads(corpo)["risposta"], "Ciao, sono Ada.")
        self.assertEqual(len(json.loads(self.chiama(base, "/api/chat")[1])["messaggi"]), 2)

    def test_percorsi_vietati_e_post_non_json(self):
        base = self.avvia()
        self.assertEqual(self.chiama(base, "/../src/ada/db.py")[0], 404)
        self.assertEqual(self.chiama(base, "/%2e%2e/src/ada/db.py")[0], 404)
        self.assertEqual(self.chiama(base, "/api/chat", {"messaggio": "x"}, tipo="text/plain")[0], 400)

    def test_token(self):
        base = self.avvia(token="segreto")
        self.assertEqual(self.chiama(base, "/api/stato")[0], 401)
        self.assertEqual(self.chiama(base, "/api/stato", intest={"Authorization": "Bearer sbagliato"})[0], 401)
        self.assertEqual(self.chiama(base, "/api/stato", intest={"Authorization": "Bearer segreto"})[0], 200)

    def test_host_estraneo_rifiutato_senza_token(self):
        base = self.avvia()
        self.assertEqual(self.chiama(base, "/api/stato", intest={"Host": "evil.example.com"})[0], 401)

    def test_feedback_e_approvazioni(self):
        base = self.avvia()
        self.assertEqual(self.chiama(base, "/api/feedback", {"agente": "revisore", "testo": "ha sbagliato"})[0], 200)
        self.assertEqual(self.chiama(base, "/api/feedback", {"agente": "boh", "testo": "x"})[0], 400)
        self.assertEqual(self.chiama(base, "/api/approvazioni/99", {"esito": "approva"})[0], 400)
        stato = json.loads(self.chiama(base, "/api/stato")[1])
        self.assertEqual(stato["segnalazioni_aperte"], 1)


if __name__ == "__main__":
    unittest.main()
