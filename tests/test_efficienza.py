import io
import json
import sqlite3
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

from src.ada import cervello
from src.ada.db import DB
from src.ada.llm import MARCATORE, Claude
from src.ada.server import costruisci, crea_server
from tests.test_ada import FinteRisposte, testo, usa


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def ctx(self, llm):
        c = costruisci(llm=llm, home=Path(self.tmp.name), movimenti=Path(self.tmp.name) / "n.db", token="")
        self.addCleanup(c.db.c.close)
        return c


class TestCache(Base):
    def llm(self):
        inviati = []

        def apri(req, timeout):
            inviati.append(json.loads(req.data))
            return io.BytesIO(b'{"content": []}')
        return Claude(chiave="k", apri=apri), inviati

    def test_la_parte_stabile_e_in_cache_e_il_contesto_no(self):
        llm, inviati = self.llm()
        llm("istruzioni stabili" + MARCATORE + "Oggi è 23/10 21:30", [{"role": "user", "content": "x"}], [{"name": "a"}])
        blocchi = inviati[0]["system"]
        self.assertEqual([b["text"] for b in blocchi], ["istruzioni stabili", "Oggi è 23/10 21:30"])
        self.assertIn("cache_control", blocchi[0])
        self.assertNotIn("cache_control", blocchi[1])
        self.assertNotIn("##CONTESTO", json.dumps(inviati[0]))

    def test_senza_cache_un_testo_solo_senza_marcatore(self):
        llm, inviati = self.llm()
        llm.cache = False
        llm("stabile" + MARCATORE + "contesto", [{"role": "user", "content": "x"}])
        self.assertEqual(inviati[0]["system"], "stabile\n\ncontesto")

    def test_il_testo_stabile_non_cambia_tra_una_richiesta_e_l_altra(self):
        llm = FinteRisposte(testo("a"), testo("b"))
        c = self.ctx(llm)
        c.ada.chiacchiera("prima")
        c.ada.segnala("revisore", "un problema nuovo comparso tra le due richieste", "utente")
        c.db.esegui("UPDATE routine SET attiva=0 WHERE nome='fatture'")
        c.ada.chiacchiera("seconda")
        s1, s2 = (x["system"] for x in llm.chiamate)
        self.assertNotEqual(s1, s2)  # il contesto è cambiato…
        self.assertEqual(s1.partition(MARCATORE)[0], s2.partition(MARCATORE)[0])  # …ma la parte in cache no
        self.assertIn("non muovi mai denaro", s1.partition(MARCATORE)[0])
        self.assertIn("Non chiedere «quale vuoi che faccia partire»", s1.partition(MARCATORE)[0])
        self.assertIn("SEGNALAZIONI APERTE", s2.partition(MARCATORE)[2])
        self.assertNotIn("Oggi è", s1.partition(MARCATORE)[0])


class TestCosaDiceAdaDelConsumo(Base):
    def test_il_tetto_non_riguarda_la_chat(self):
        c = self.ctx(FinteRisposte())
        c.db.esegui("INSERT INTO consumi VALUES (?,?,?,?)", (__import__("time").strftime("%Y-%m-%d"), 450000, 23000, 30))
        out = c.ada._esegui("ada", "stato_sistema", {})
        self.assertIn("473000 token in totale (la chat con l'utente non ha tetto e non va mai limitata)", out)
        self.assertIn("lavori automatici 0 su un tetto di 800000", out)
        self.assertIn("non limitare mai per quel motivo il lavoro che ti chiede l'utente", cervello.MANDATO)


class TestStoria(Base):
    def test_i_messaggi_vecchi_e_lunghi_si_accorciano_gli_ultimi_no(self):
        c = self.ctx(FinteRisposte())
        for i in range(4):
            c.db.esegui("INSERT INTO chat (ts, ruolo, testo) VALUES (1,'utente',?)", (f"domanda {i}",))
            c.db.esegui("INSERT INTO chat (ts, ruolo, testo) VALUES (2,'ada',?)", (f"risposta {i} " + "lunga " * 200,))
        c.db.esegui("INSERT INTO chat (ts, ruolo, testo) VALUES (3,'utente','ultima domanda')")
        msgs = c.ada._storia()
        vecchi = [m for m in msgs[:-2]]
        self.assertTrue(all(len(m["content"]) <= 501 for m in vecchi))
        self.assertTrue(any(m["content"].endswith("…") for m in vecchi))
        self.assertEqual(msgs[-1]["content"], "ultima domanda")
        self.assertGreater(len(msgs[-2]["content"]), 500)  # il penultimo resta intero
        self.assertLessEqual(len(msgs), 12)


class TestAzioniNellaChat(Base):
    def avvia(self, llm):
        c = self.ctx(llm)
        srv = crea_server(c, "127.0.0.1", 0)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        self.addCleanup(srv.server_close)
        base = f"http://127.0.0.1:{srv.server_address[1]}"

        def post(dati):
            req = urllib.request.Request(base + "/api/chat", data=json.dumps(dati).encode(), headers={"Content-Type": "application/json"})
            return json.load(urllib.request.urlopen(req))
        return c, post, lambda: json.load(urllib.request.urlopen(base + "/api/chat"))["messaggi"]

    def test_sotto_la_risposta_ci_sono_gli_strumenti_usati(self):
        llm = FinteRisposte(usa("stato_sistema"), usa("aggiungi_regola_prompt", agente="revisore",
                                                         regola="Controlla sempre gli arrotondamenti a due decimali.", motivo="errore"),
                            testo("Fatto: ho aggiunto la regola."))
        c, post, messaggi = self.avvia(llm)
        r = post({"messaggio": "sistema il revisore"})
        self.assertEqual([a["nome"] for a in r["azioni"]], ["stato_sistema", "aggiungi_regola_prompt"])
        self.assertIn("applicata subito", r["azioni"][1]["esito"])
        ada = [m for m in messaggi() if m["ruolo"] == "ada"][-1]
        self.assertEqual([a["nome"] for a in ada["azioni"]], ["stato_sistema", "aggiungi_regola_prompt"])  # restano dopo il ricaricamento
        utente = [m for m in messaggi() if m["ruolo"] == "utente"][-1]
        self.assertEqual(utente["azioni"], [])

    def test_senza_strumenti_nessuna_azione(self):
        c, post, messaggi = self.avvia(FinteRisposte(testo("Ciao!")))
        self.assertEqual(post({"messaggio": "ciao"})["azioni"], [])

    def test_le_azioni_non_si_confondono_con_quelle_di_un_assistente_delegato(self):
        llm = FinteRisposte(usa("delega", agente="revisore", compito="controlla 2+2"), usa("riepilogo_spese"),
                            testo("Il calcolo è giusto."), testo("Il revisore dice che è tutto a posto."))
        c, post, _ = self.avvia(llm)
        r = post({"messaggio": "fai controllare"})
        self.assertEqual([a["nome"] for a in r["azioni"]], ["delega"])  # le sue, non quelle del revisore

    def test_routine_e_ciclo_scrivono_con_le_azioni(self):
        c = self.ctx(FinteRisposte(usa("stato_sistema"), testo("Riepilogo pronto.")))
        c.ada.lavoro_proattivo("fai il riepilogo per favore", "riepilogo_sera")
        riga = c.db.uno("SELECT azioni FROM chat WHERE ruolo='ada'")
        self.assertEqual(json.loads(riga["azioni"])[0]["nome"], "stato_sistema")

    def test_database_vecchi_ricevono_la_colonna(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "vecchio.db"
            k = sqlite3.connect(p)
            k.execute("CREATE TABLE chat (id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, ruolo TEXT, testo TEXT)")
            k.execute("INSERT INTO chat (ts, ruolo, testo) VALUES (1, 'utente', 'ciao vecchio')")
            k.commit()
            k.close()
            db = DB(p)
            self.addCleanup(db.c.close)
            r = db.uno("SELECT testo, azioni FROM chat")
            self.assertEqual((r["testo"], r["azioni"]), ("ciao vecchio", None))
            DB(p).c.close()  # una seconda apertura non deve fallire


if __name__ == "__main__":
    unittest.main()
