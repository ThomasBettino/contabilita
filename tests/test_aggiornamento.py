import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

from src.ada import aggiornamento
from src.ada.server import costruisci, crea_server
from tests.test_ada import FinteRisposte


class TestAggiornamento(unittest.TestCase):
    def runner(self, pull="Updating a..b\nFast-forward", rc_pull=0, rc_test=0):
        chiamate = []

        def run(cmd, **k):
            chiamate.append((cmd, k))
            if "pull" in cmd:
                return SimpleNamespace(returncode=rc_pull, stdout=pull, stderr="")
            if "unittest" in cmd:
                return SimpleNamespace(returncode=rc_test, stdout="", stderr="FAILED (failures=2)" if rc_test else "OK")
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return run, chiamate

    def test_gia_aggiornata(self):
        run, ch = self.runner(pull="Already up to date.")
        r = aggiornamento.aggiorna(run)
        self.assertEqual((r["ok"], r["cambiato"]), (True, False))
        self.assertFalse(any("unittest" in c[0] for c in ch))

    def test_pull_solo_fast_forward(self):
        run, ch = self.runner()
        aggiornamento.aggiorna(run)
        self.assertIn("--ff-only", ch[0][0])

    def test_versione_nuova_che_passa_i_test(self):
        run, ch = self.runner()
        r = aggiornamento.aggiorna(run)
        self.assertEqual((r["ok"], r["cambiato"]), (True, True))
        self.assertFalse(any("reset" in c[0] for c in ch))

    def test_versione_nuova_che_rompe_i_test_torna_indietro(self):
        run, ch = self.runner(rc_test=1)
        r = aggiornamento.aggiorna(run)
        self.assertEqual((r["ok"], r["cambiato"]), (False, False))
        self.assertIn("sono tornata a quella di prima", r["messaggio"])
        reset = [c for c in ch if "reset" in c[0]]
        self.assertEqual(len(reset), 1)
        self.assertEqual(reset[0][0][-2:], ["--hard", "ORIG_HEAD"])

    def test_i_test_girano_senza_chiavi_ne_impostazioni_vere(self):
        import os
        os.environ["ADA_TOKEN"], os.environ["ANTHROPIC_API_KEY"] = "x", "y"
        self.addCleanup(lambda: [os.environ.pop(k, None) for k in ("ADA_TOKEN", "ANTHROPIC_API_KEY")])
        run, ch = self.runner()
        aggiornamento.aggiorna(run)
        env = [c[1]["env"] for c in ch if "unittest" in c[0]][0]
        self.assertNotIn("ADA_TOKEN", env)
        self.assertNotIn("ANTHROPIC_API_KEY", env)

    def test_pull_fallito(self):
        run, _ = self.runner(pull="fatal: Not possible to fast-forward", rc_pull=1)
        r = aggiornamento.aggiorna(run)
        self.assertFalse(r["ok"])
        self.assertIn("non riuscito", r["messaggio"])

    def test_versione(self):
        def run(cmd, **k):
            out = "abc1234|23/10 20:40|Add popup" if "log" in cmd else "ccr-b35db874-occc4m"
            return SimpleNamespace(returncode=0, stdout=out, stderr="")
        v = aggiornamento.versione(run)
        self.assertEqual((v["id"], v["data"], v["titolo"], v["ramo"]), ("abc1234", "23/10 20:40", "Add popup", "ccr-b35db874-occc4m"))
        self.assertEqual(aggiornamento.versione(lambda *a, **k: (_ for _ in ()).throw(OSError()))["id"], "?")


class TestServer(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def avvia(self, token):
        c = costruisci(llm=FinteRisposte(), home=Path(self.tmp.name), movimenti=Path(self.tmp.name) / "n.db", token=token)
        self.addCleanup(c.db.c.close)
        self.riavvii = []
        self.risposta = {"ok": True, "cambiato": True, "messaggio": "Aggiornata: Ada si riavvia."}
        c.fn_aggiorna = lambda: self.risposta
        c.fn_riavvia = lambda: self.riavvii.append(1)
        srv = crea_server(c, "127.0.0.1", 0)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        self.addCleanup(srv.server_close)
        base = f"http://127.0.0.1:{srv.server_address[1]}"

        def post(path, auth=None):
            h = {"Content-Type": "application/json"}
            if auth:
                h["Authorization"] = "Bearer " + auth
            req = urllib.request.Request(base + path, data=b"{}", headers=h)
            try:
                with urllib.request.urlopen(req) as r:
                    return r.status, json.load(r)
            except urllib.error.HTTPError as e:
                return e.code, json.load(e)

        def stato():
            req = urllib.request.Request(base + "/api/stato", headers={"Authorization": "Bearer " + token} if token else {})
            return json.load(urllib.request.urlopen(req))
        return post, stato

    def test_aggiorna_richiede_il_token(self):
        post, _ = self.avvia("")
        codice, j = post("/api/aggiorna")
        self.assertEqual(codice, 403)
        self.assertIn("ADA_TOKEN", j["errore"])
        self.assertEqual(self.riavvii, [])

    def test_aggiorna_riavvia_solo_se_cambia_qualcosa(self):
        post, _ = self.avvia("abc")
        self.assertEqual(post("/api/aggiorna", "abc")[0], 200)
        self.assertEqual(self.riavvii, [1])
        self.risposta = {"ok": True, "cambiato": False, "messaggio": "Ada è già all'ultima versione."}
        post("/api/aggiorna", "abc")
        self.risposta = {"ok": False, "cambiato": False, "messaggio": "La versione nuova non ha superato i test"}
        post("/api/aggiorna", "abc")
        self.assertEqual(self.riavvii, [1])  # niente riavvio se non è cambiato o se è stato annullato

    def test_stato_con_versione_e_token(self):
        _, stato = self.avvia("abc")
        s = stato()
        self.assertTrue(s["token_attivo"])
        self.assertIn("id", s["versione"])
        self.assertNotIn("github", s)


if __name__ == "__main__":
    unittest.main()
