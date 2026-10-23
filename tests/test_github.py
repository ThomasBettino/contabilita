import io
import json
import sqlite3
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

from src.ada import aggiornamento
from src.ada.db import DB
from src.ada.github import ClienteGitHub, ErroreGitHub, corpo_issue
from src.ada.server import costruisci, crea_server
from tests.test_ada import FinteRisposte

IDEA = {"titolo": "Grafico delle spese per settimana", "descrizione": "Nella scheda Soldi un grafico a barre con le uscite di "
        "ogni settimana, per vedere subito se questa è più cara delle altre.", "motivo": "Oggi il confronto si fa a mente."}


class FintoGitHub:
    configurato = True
    repo = "proprietario/app"

    def __init__(self, guasto=False):
        self.guasto, self.issue = guasto, []

    def crea_issue(self, titolo, corpo):
        if self.guasto:
            raise ErroreGitHub("HTTP 401: Bad credentials")
        self.issue.append((titolo, corpo))
        return {"numero": 40 + len(self.issue), "url": f"https://github.com/proprietario/app/issues/{40 + len(self.issue)}"}

    def verifica(self):
        if self.guasto:
            raise ErroreGitHub("HTTP 404: Not Found")
        return {"privato": True, "ramo": "main"}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.avvisi = []

    def ctx(self, github=None, token=""):
        c = costruisci(llm=FinteRisposte(), home=Path(self.tmp.name), movimenti=Path(self.tmp.name) / "n.db", token=token)
        c.ada.notifica = lambda t, x, i="ada": self.avvisi.append((t, x, i))
        c.ada.github = github
        self.addCleanup(c.db.c.close)
        return c

    def approva_idea(self, c):
        c.ada._esegui("ada", "proponi_idea", IDEA)
        a = c.db.uno("SELECT id FROM approvazioni WHERE tipo='idea' AND stato='in_attesa'")
        c.ada.risolvi(a["id"], "approva")


class TestCliente(unittest.TestCase):
    def cliente(self, risposta, repo="proprietario/app", token="ghp_segretissimo"):
        visto = {}

        def apri(req, timeout):
            visto.update(url=req.full_url, metodo=req.get_method(), intest={k.lower(): v for k, v in req.header_items()},
                         corpo=json.loads(req.data) if req.data else None)
            if isinstance(risposta, Exception):
                raise risposta
            return io.BytesIO(json.dumps(risposta).encode())
        return ClienteGitHub(repo, token, apri=apri), visto

    def test_crea_issue_come_si_aspetta_github(self):
        c, v = self.cliente({"number": 12, "html_url": "https://github.com/proprietario/app/issues/12"})
        self.assertEqual(c.crea_issue("Titolo", "Corpo"), {"numero": 12, "url": "https://github.com/proprietario/app/issues/12"})
        self.assertEqual((v["metodo"], v["url"]), ("POST", "https://api.github.com/repos/proprietario/app/issues"))
        self.assertEqual(v["corpo"], {"title": "Titolo", "body": "Corpo", "labels": ["idea-ada"]})
        self.assertEqual(v["intest"]["authorization"], "Bearer ghp_segretissimo")
        self.assertEqual(v["intest"]["x-github-api-version"], "2022-11-28")

    def test_errori_senza_mai_mostrare_il_codice(self):
        errore = urllib.error.HTTPError("u", 401, "x", {}, io.BytesIO(b'{"message": "Bad credentials"}'))
        c, _ = self.cliente(errore)
        with self.assertRaises(ErroreGitHub) as e:
            c.crea_issue("t", "c")
        self.assertEqual(str(e.exception), "HTTP 401: Bad credentials")
        self.assertNotIn("segretissimo", str(e.exception))
        c, _ = self.cliente(urllib.error.URLError("giù"))
        with self.assertRaises(ErroreGitHub) as e:
            c.verifica()
        self.assertIn("non raggiungibile", str(e.exception))

    def test_non_configurato(self):
        for repo, token in (("proprietario/app", ""), ("senza-barra", "t"), ("a/b/c", "t"), ("", "t")):
            c, v = self.cliente({}, repo, token)
            self.assertFalse(c.configurato)
            with self.assertRaises(ErroreGitHub):
                c.crea_issue("t", "c")
            self.assertEqual(v, {})  # nessuna richiesta partita

    def test_verifica(self):
        c, v = self.cliente({"private": False, "default_branch": "main"})
        self.assertEqual(c.verifica(), {"privato": False, "ramo": "main"})
        self.assertEqual(v["url"], "https://api.github.com/repos/proprietario/app")

    def test_testo_del_problema(self):
        t = corpo_issue({**IDEA})
        self.assertTrue(t.startswith("@claude"))
        for atteso in (IDEA["titolo"], IDEA["motivo"], "guardiano.py", "pull request", "test"):
            self.assertIn(atteso, t)


class TestIdeeSuGitHub(Base):
    def test_idea_approvata_diventa_un_problema_e_in_sviluppo(self):
        g = FintoGitHub()
        c = self.ctx(g)
        self.approva_idea(c)
        i = c.db.uno("SELECT * FROM idee")
        self.assertEqual((i["stato"], i["issue_numero"]), ("in_sviluppo", 41))
        self.assertEqual(g.issue[0][0], "[Idea di Ada] Grafico delle spese per settimana")
        self.assertEqual(self.avvisi[-1][2], "ada-sviluppo")
        c.ada.idea_fatta(i["id"])  # da "in sviluppo" si può chiudere
        self.assertEqual(c.db.uno("SELECT stato FROM idee")["stato"], "fatta")

    def test_rifiutata_non_pubblica(self):
        g = FintoGitHub()
        c = self.ctx(g)
        c.ada._esegui("ada", "proponi_idea", IDEA)
        c.ada.risolvi(c.db.uno("SELECT id FROM approvazioni")["id"], "rifiuta")
        self.assertEqual(g.issue, [])

    def test_se_github_fallisce_l_idea_resta_approvata_e_si_riprova(self):
        g = FintoGitHub(guasto=True)
        c = self.ctx(g)
        self.approva_idea(c)
        self.assertEqual(c.db.uno("SELECT stato, issue_numero FROM idee")["stato"], "approvata")
        self.assertTrue(any("pubblicazione idea" in (a["dettaglio"] or "") for a in c.db.tutti("SELECT dettaglio FROM attivita")))
        with self.assertRaises(ValueError):
            c.ada.pubblica_idea(1)
        g.guasto = False
        self.assertIn("problema #41", c.ada.pubblica_idea(1))
        with self.assertRaises(ValueError):
            c.ada.pubblica_idea(1)  # già inviata: niente doppioni
        self.assertEqual(len(g.issue), 1)

    def test_senza_collegamento_resta_approvata(self):
        c = self.ctx(None)
        self.approva_idea(c)
        self.assertEqual(c.db.uno("SELECT stato FROM idee")["stato"], "approvata")
        with self.assertRaises(ValueError) as e:
            c.ada.pubblica_idea(1)
        self.assertIn("non collegato", str(e.exception))

    def test_idee_con_dati_personali_vengono_rifiutate(self):
        c = self.ctx(FintoGitHub())
        for sporco in ("Mostrare quanto spendo: 58,40 € al giorno", "Scrivere a mario.rossi@example.com ogni sera",
                       "Controllare IT60X0542811101000000123456 ogni mese", "Avvisare se supero 120 euro", "Chiamare 3331234567 domani"):
            r = c.ada._esegui("ada", "proponi_idea", {**IDEA, "descrizione": sporco + " e poi altro testo per arrivare alla lunghezza minima"})
            self.assertIn("dati personali", r, sporco)
        self.assertEqual(c.db.tutti("SELECT * FROM idee"), [])
        self.assertIn("proposta all'utente", c.ada._esegui("ada", "proponi_idea", IDEA))

    def test_stato_sistema_conta_le_idee_in_sviluppo_come_aperte(self):
        c = self.ctx(FintoGitHub())
        self.approva_idea(c)
        self.assertIn("[in_sviluppo]", c.ada._esegui("ada", "stato_sistema", {}))


class TestMigrazione(unittest.TestCase):
    def test_database_vecchi_ricevono_le_colonne_nuove(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "vecchio.db"
            k = sqlite3.connect(p)
            k.execute("CREATE TABLE idee (id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, titolo TEXT, descrizione TEXT, "
                      "motivo TEXT, stato TEXT DEFAULT 'proposta', approvazione_id INTEGER, ts_stato INTEGER)")
            k.execute("INSERT INTO idee (ts, titolo, descrizione, motivo) VALUES (1, 'vecchia', 'd', 'm')")
            k.commit()
            k.close()
            db = DB(p)
            self.addCleanup(db.c.close)
            r = db.uno("SELECT titolo, issue_numero, issue_url FROM idee")
            self.assertEqual((r["titolo"], r["issue_numero"], r["issue_url"]), ("vecchia", None, None))
            DB(p).c.close()  # una seconda apertura non deve fallire


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
        self.assertIn("tornata a quella di prima" if "tornata" in r["messaggio"] else "sono tornata", r["messaggio"])
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


class TestServer(Base):
    def avvia(self, token, github=None):
        c = self.ctx(github, token)
        c.fn_aggiorna = lambda: self.risposta_aggiorna
        c.fn_riavvia = lambda: self.riavvii.append(1)
        c.nuovo_github = lambda repo, tok: self.cliente_gh
        self.riavvii, self.risposta_aggiorna, self.cliente_gh = [], {"ok": True, "cambiato": True, "messaggio": "Aggiornata: Ada si riavvia."}, FintoGitHub()
        srv = crea_server(c, "127.0.0.1", 0)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        self.addCleanup(srv.server_close)
        base = f"http://127.0.0.1:{srv.server_address[1]}"

        def post(path, dati=None, auth=None):
            h = {"Content-Type": "application/json"}
            if auth:
                h["Authorization"] = "Bearer " + auth
            req = urllib.request.Request(base + path, data=json.dumps(dati or {}).encode(), headers=h)
            try:
                with urllib.request.urlopen(req) as r:
                    return r.status, json.load(r)
            except urllib.error.HTTPError as e:
                return e.code, json.load(e)

        def stato():
            req = urllib.request.Request(base + "/api/stato", headers={"Authorization": "Bearer " + token} if token else {})
            return json.load(urllib.request.urlopen(req))
        return c, post, stato

    def test_aggiorna_richiede_il_token(self):
        c, post, _ = self.avvia("")
        codice, j = post("/api/aggiorna")
        self.assertEqual(codice, 403)
        self.assertIn("ADA_TOKEN", j["errore"])
        self.assertEqual(self.riavvii, [])

    def test_aggiorna_riavvia_solo_se_cambia_qualcosa(self):
        c, post, _ = self.avvia("abc")
        self.assertEqual(post("/api/aggiorna", auth="abc")[0], 200)
        self.assertEqual(self.riavvii, [1])
        self.risposta_aggiorna = {"ok": True, "cambiato": False, "messaggio": "Ada è già all'ultima versione."}
        post("/api/aggiorna", auth="abc")
        self.risposta_aggiorna = {"ok": False, "cambiato": False, "messaggio": "La versione nuova non ha superato i test"}
        post("/api/aggiorna", auth="abc")
        self.assertEqual(self.riavvii, [1])  # niente riavvio se non è cambiato o se è stato annullato

    def test_collegamento_github_prova_salva_e_resta(self):
        c, post, stato = self.avvia("abc")
        self.assertEqual(post("/api/impostazioni/github", {"repo": "proprietario/app", "token": "ghp_x"})[0], 401)
        self.assertEqual(post("/api/impostazioni/github", {"repo": "storto", "token": "ghp_x"}, auth="abc")[0], 400)
        self.cliente_gh.guasto = True
        codice, j = post("/api/impostazioni/github", {"repo": "proprietario/app", "token": "sbagliato"}, auth="abc")
        self.assertEqual(codice, 400)
        self.assertIn("non ha accettato", j["errore"])
        self.assertFalse((Path(self.tmp.name) / "segreti.json").exists())
        self.cliente_gh.guasto = False
        codice, j = post("/api/impostazioni/github", {"repo": "proprietario/app", "token": "ghp_x"}, auth="abc")
        self.assertEqual((codice, j["privato"]), (200, True))
        f = Path(self.tmp.name) / "segreti.json"
        self.assertEqual(oct(f.stat().st_mode & 0o777), "0o600")
        self.assertEqual(stato()["github"], {"configurato": True, "repo": "proprietario/app", "token_attivo": True})
        c2 = costruisci(llm=FinteRisposte(), home=Path(self.tmp.name), movimenti=Path(self.tmp.name) / "n.db", token="abc")
        self.addCleanup(c2.db.c.close)
        self.assertEqual((c2.ada.github.repo, c2.ada.github.token, c2.ada.github.configurato), ("proprietario/app", "ghp_x", True))

    def test_senza_token_di_accesso_non_salva_il_codice_github(self):
        c, post, _ = self.avvia("")
        self.assertEqual(post("/api/impostazioni/github", {"repo": "proprietario/app", "token": "ghp_x"})[0], 403)
        self.assertFalse((Path(self.tmp.name) / "segreti.json").exists())

    def test_pubblica_e_stato_con_versione_e_link(self):
        c, post, stato = self.avvia("abc", FintoGitHub(guasto=True))
        self.approva_idea(c)
        self.assertEqual(post("/api/idee/1/pubblica", auth="abc")[0], 400)
        c.ada.github = FintoGitHub()
        self.assertEqual(post("/api/idee/1/pubblica", auth="abc")[0], 200)
        s = stato()
        self.assertEqual(s["idee"][0]["issue_numero"], 41)
        self.assertTrue(s["idee"][0]["issue_url"].startswith("https://github.com/"))
        self.assertIn("id", s["versione"])


class TestFileDiConfigurazione(unittest.TestCase):
    def test_workflow(self):
        t = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "claude.yml").read_text()
        for atteso in ("anthropics/claude-code-action@v1", "anthropic_api_key: ${{ secrets.ANTHROPIC_API_KEY }}",
                       "idea-ada", "@claude", "issues:", "issue_comment:", "timeout-minutes"):
            self.assertIn(atteso, t)
        self.assertNotIn("pull_request_target", t)  # mai eseguire codice di fork con i segreti


if __name__ == "__main__":
    unittest.main()
