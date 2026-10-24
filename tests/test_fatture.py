import io
import json
import sqlite3
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path

from src.ada.fatture import Archivio, ClienteScript, Config, ErroreFatture, calcola, num
from src.ada.server import costruisci, crea_server
from tests.test_ada import FinteRisposte

MESE = time.strftime("%Y-%m")
CFG = Config(url="https://script.google.com/macros/s/X/exec", token="t", ena=8.5, tasse=30.0, giorni=30, pagatore="autoghinzani")


def fattura(id_, lordo, stato="fatturata", numero=None, giorno="02", **extra):
    return {"id": id_, "numero": numero or f"{id_}/2026", "data": f"{MESE}-{giorno}", "descrizione": "Provvigioni",
            "lordo": lordo, "stato": stato, "fonte": "gmail", **extra}


class FintoScript:
    configurato = True

    def __init__(self, fatture=None, acc=None):
        self.fatture, self.acc, self.chiamate, self.guasto = fatture or [], acc or {}, [], False

    def chiama(self, **corpo):
        if self.guasto:
            raise ErroreFatture("script non raggiungibile")
        self.chiamate.append(corpo)
        if corpo["action"] == "list":
            return {"ok": True, "fatture": json.loads(json.dumps(self.fatture)), "accantonamenti": self.acc}
        if corpo["action"] == "update":
            for f in self.fatture:
                if f["id"] == corpo["id"]:
                    f.update(corpo["fields"])
        return {"ok": True}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.mov = Path(self.tmp.name) / "mov.db"
        k = sqlite3.connect(self.mov)
        k.execute("CREATE TABLE movimenti (chiave TEXT, quando TEXT, importo REAL, controparte TEXT, testo TEXT)")
        k.commit()
        k.close()
        self.avvisi = []

    def movimento(self, chiave, importo, controparte="", testo="", quando=None):
        k = sqlite3.connect(self.mov)
        k.execute("INSERT INTO movimenti VALUES (?,?,?,?,?)", (chiave, quando or f"{MESE}-05 10:00:00", importo, controparte, testo))
        k.commit()
        k.close()

    def ctx(self, script):
        c = costruisci(llm=FinteRisposte(), home=Path(self.tmp.name), movimenti=self.mov, token="")
        c.ada.notifica = lambda t, x, i="ada": self.avvisi.append((t, x, i))
        c.ada.archivio = Archivio(c.ada, script, CFG)
        self.addCleanup(c.db.c.close)
        return c

    def chat(self, c):
        return [r["testo"] for r in c.db.tutti("SELECT testo FROM chat WHERE ruolo='ada' ORDER BY id")]


class TestCalcoli(unittest.TestCase):
    def test_come_l_app(self):
        c = calcola({"lordo": "808,00"}, CFG)
        self.assertEqual((c["bollo"], c["ena"], c["netto"], c["tasse"], c["bonifico"]), (2.0, 68.68, 739.32, 221.8, 741.32))

    def test_sotto_soglia_niente_bollo_e_bollo_esplicito(self):
        self.assertEqual(calcola({"lordo": 70}, CFG)["bollo"], 0.0)
        self.assertEqual(calcola({"lordo": 100, "bollo": "0"}, CFG)["bollo"], 0.0)

    def test_numeri_all_italiana(self):
        self.assertEqual(num("1.250,50"), 1250.5)
        self.assertEqual(num("808,00"), 808.0)
        self.assertEqual(num(""), 0.0)


class TestFormato(unittest.TestCase):
    def test_euro_all_italiana(self):
        from src.ada.fatture import eur
        self.assertEqual((eur(741.3), eur(1250.5), eur(0)), ("741,30 €", "1.250,50 €", "0,00 €"))


class TestCliente(unittest.TestCase):
    def test_non_manda_il_token_fuori_da_google(self):
        chiamate = []
        c = ClienteScript("https://evil.example.com/x", "segreto", apri=lambda *a, **k: chiamate.append(a))
        with self.assertRaises(ErroreFatture):
            c.chiama(action="list")
        self.assertEqual(chiamate, [])

    def test_senza_configurazione(self):
        with self.assertRaises(ErroreFatture):
            ClienteScript("", "").chiama(action="list")

    def test_richiesta_come_l_app_e_errori(self):
        visto = {}

        def apri(req, timeout):
            visto["corpo"], visto["tipo"] = json.loads(req.data), req.get_header("Content-type")
            return io.BytesIO(b'{"ok": true, "fatture": []}')
        j = ClienteScript(CFG.url, "tok", apri=apri).chiama(action="list")
        self.assertEqual((visto["corpo"], visto["tipo"]), ({"action": "list", "token": "tok"}, "text/plain;charset=utf-8"))
        self.assertTrue(j["ok"])
        with self.assertRaises(ErroreFatture) as e:
            ClienteScript(CFG.url, "tok", apri=lambda r, timeout: io.BytesIO(b'{"ok": false, "error": "token errato"}')).chiama(action="list")
        self.assertIn("token errato", str(e.exception))


class TestSincronizza(Base):
    def test_primo_giro_silenzioso_poi_avvisa_solo_le_nuove(self):
        s = FintoScript([fattura("a", 808)], {MESE: 100})
        c = self.ctx(s)
        self.assertEqual(c.ada.archivio.sincronizza(), {"nuove": 0, "totale": 1})
        self.assertEqual(self.avvisi, [])
        s.fatture.append(fattura("b", 500, "inviata"))
        self.assertEqual(c.ada.archivio.sincronizza(), {"nuove": 1, "totale": 2})
        self.assertEqual(self.avvisi[-1][0], "Fattura archiviata")
        self.assertNotIn("€", self.avvisi[-1][1])
        c.ada.archivio.sincronizza()
        self.assertEqual(len(self.avvisi), 1)  # niente doppioni

    def test_fattura_cancellata_sparisce(self):
        s = FintoScript([fattura("a", 808), fattura("b", 500)])
        c = self.ctx(s)
        c.ada.archivio.sincronizza()
        s.fatture.pop()
        c.ada.archivio.sincronizza()
        self.assertEqual([f["id"] for f in c.ada.archivio.elenco()], ["a"])

    def test_riepilogo_e_tasse(self):
        s = FintoScript([fattura("a", 808, "incassata"), fattura("b", 500, "inviata")], {MESE: 100})
        c = self.ctx(s)
        c.ada.archivio.sincronizza()
        r = c.ada.archivio.riepilogo()
        self.assertEqual((r["fatture"], r["incassato"], r["accantonato"]), (2, 741.32, 100.0))
        self.assertAlmostEqual(r["da_incassare"], 500 + 2 - 42.5)
        self.assertAlmostEqual(r["tasse_dovute"], 221.8 + round((500 - 42.5) * 0.30, 2))
        self.assertAlmostEqual(r["mancano"], r["tasse_dovute"] - 100)
        self.assertIn("mancano", c.ada._esegui("revisore", "riepilogo_fatture", {}))

    def test_scaduta_oltre_i_giorni(self):
        vecchia = fattura("a", 808, "fatturata")
        vecchia["data"] = time.strftime("%Y-%m-%d", time.localtime(time.time() - 40 * 86400))
        c = self.ctx(FintoScript([vecchia]))
        c.ada.archivio.sincronizza()
        f = c.ada.archivio.elenco()[0]
        self.assertTrue(f["scaduta"])
        self.assertEqual(f["giorni_scaduta"], 10)


class TestIncassi(Base):
    def avvia(self, fatture):
        s = FintoScript(fatture)
        c = self.ctx(s)
        c.ada.archivio.sincronizza()
        c.ada.archivio.elabora_incassi()  # il primo giro ignora lo storico
        self.avvisi.clear()
        return c, s

    def test_il_primo_giro_non_riesamina_lo_storico(self):
        self.movimento("vecchio", 741.32, "Autoghinzani")
        c = self.ctx(FintoScript([fattura("a", 808)]))
        c.ada.archivio.sincronizza()
        self.assertIn("già presenti", c.ada.archivio.elabora_incassi())
        self.assertEqual(c.ada.archivio.elabora_incassi(), "Nessun nuovo bonifico.")
        self.assertEqual(c.ada.archivio._trova("a")["stato"], "fatturata")

    def test_bonifico_del_pagatore_segna_la_fattura_giusta(self):
        c, s = self.avvia([fattura("a", 808, numero="5/2026"), fattura("b", 500, numero="6/2026")])
        self.movimento("m1", 741.32, "Autoghinzani S.r.l.", "Hai ricevuto 741,32 € da Autoghinzani")
        self.assertIn("abbinato", c.ada.archivio.elabora_incassi())
        self.assertEqual(c.ada.archivio._trova("a")["stato"], "incassata")
        self.assertEqual(c.ada.archivio._trova("b")["stato"], "fatturata")  # l'altra non si tocca
        update = [x for x in s.chiamate if x["action"] == "update"][0]
        self.assertEqual((update["id"], update["fields"]["stato"]), ("a", "incassata"))
        self.assertEqual(update["fields"]["dataIncasso"], f"{MESE}-05")
        self.assertEqual(self.avvisi[-1][0], "Bonifico arrivato")
        self.assertNotIn("741", self.avvisi[-1][1])  # niente cifre sul blocco schermo
        self.assertIn("5/2026", self.chat(c)[-1])
        self.assertIn("741,32 €", self.chat(c)[-1])

    def test_non_si_ripete_sullo_stesso_movimento(self):
        c, s = self.avvia([fattura("a", 808)])
        self.movimento("m1", 741.32, "Autoghinzani")
        c.ada.archivio.elabora_incassi()
        c.ada.archivio.elabora_incassi()
        self.assertEqual(len([x for x in s.chiamate if x["action"] == "update"]), 1)

    def test_importi_uguali_chiede_quale(self):
        c, s = self.avvia([fattura("a", 808), fattura("b", 808)])
        self.movimento("m1", 741.32, "Autoghinzani")
        self.assertIn("ambiguo", c.ada.archivio.elabora_incassi())
        self.assertEqual([x for x in s.chiamate if x["action"] == "update"], [])
        self.assertIn("più fatture", self.chat(c)[-1])
        self.assertIn("segnata come incassata", c.ada._esegui("ada", "fattura_incassata", {"id": "b"}))

    def test_pagatore_senza_fattura_corrispondente(self):
        c, s = self.avvia([fattura("a", 808)])
        self.movimento("m1", 100.00, "Autoghinzani")
        self.assertIn("senza fattura", c.ada.archivio.elabora_incassi())
        self.assertIn("nessuna fattura", self.chat(c)[-1])
        self.assertEqual(c.ada.archivio._trova("a")["stato"], "fatturata")

    def test_importo_giusto_ma_mittente_ignoto_chiede_conferma(self):
        c, s = self.avvia([fattura("a", 808)])
        self.movimento("m1", 741.32, "Mario Rossi")
        self.assertIn("da confermare", c.ada.archivio.elabora_incassi())
        a = c.db.uno("SELECT * FROM approvazioni WHERE tipo='incasso'")
        self.assertEqual(c.ada.archivio._trova("a")["stato"], "fatturata")  # niente senza conferma
        c.ada.risolvi(a["id"], "approva")
        self.assertEqual(c.ada.archivio._trova("a")["stato"], "incassata")

    def test_rifiutare_non_cambia_nulla(self):
        c, s = self.avvia([fattura("a", 808)])
        self.movimento("m1", 741.32, "Mario Rossi")
        c.ada.archivio.elabora_incassi()
        c.ada.risolvi(c.db.uno("SELECT id FROM approvazioni")["id"], "rifiuta")
        self.assertEqual(c.ada.archivio._trova("a")["stato"], "fatturata")

    def test_uscite_e_importi_estranei_ignorati(self):
        c, s = self.avvia([fattura("a", 808)])
        self.movimento("m1", -741.32, "Autoghinzani")
        self.movimento("m2", 12.00, "Rimborso qualsiasi")
        self.assertEqual(c.ada.archivio.elabora_incassi(), "Nessun nuovo bonifico.")
        self.assertEqual(self.chat(c), [])
        self.assertEqual(c.ada.archivio._trova("a")["stato"], "fatturata")

    def test_script_giu_il_bonifico_non_va_perso(self):
        c, s = self.avvia([fattura("a", 808)])
        self.movimento("m1", 741.32, "Autoghinzani")
        s.guasto = True
        self.assertIn("rinviato", c.ada.archivio.elabora_incassi())
        s.guasto = False
        self.assertIn("abbinato", c.ada.archivio.elabora_incassi())
        self.assertEqual(c.ada.archivio._trova("a")["stato"], "incassata")

    def test_annulla_incasso_ripristina_lo_stato(self):
        c, s = self.avvia([fattura("a", 808, "inviata")])
        c.ada.archivio.segna_incassata("a")
        self.assertIn("tornata allo stato «inviata»", c.ada.archivio.segna_non_incassata("a"))
        self.assertEqual(s.fatture[0]["stato"], "inviata")

    def test_solo_ada_segna_incassi(self):
        c, s = self.avvia([fattura("a", 808)])
        self.assertEqual(c.ada._esegui("contabilita_piva", "fattura_incassata", {"id": "a"}), "Strumento non consentito.")


class TestRoutineEServer(Base):
    def test_routine_fatture(self):
        c = self.ctx(FintoScript([fattura("a", 808)]))
        rid = c.db.uno("SELECT id FROM routine WHERE nome='fatture'")["id"]
        self.assertIn("1 fatture", c.pian.esegui(rid))
        c.ada.archivio = Archivio(c.ada, ClienteScript("", ""), CFG)
        self.assertIn("Non configurato", c.pian.esegui(rid))
        guasto = FintoScript()
        guasto.guasto = True
        c.ada.archivio = Archivio(c.ada, guasto, CFG)
        self.assertIn("Non riesco", c.pian.esegui(rid))

    def test_api(self):
        s = FintoScript([fattura("a", 808)])
        c = self.ctx(s)
        srv = crea_server(c, "127.0.0.1", 0)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        self.addCleanup(srv.server_close)
        base = f"http://127.0.0.1:{srv.server_address[1]}"

        def post(path, dati):
            req = urllib.request.Request(base + path, data=json.dumps(dati).encode(), headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req) as r:
                    return r.status, json.load(r)
            except urllib.error.HTTPError as e:
                return e.code, json.load(e)

        self.assertEqual(post("/api/fatture/sincronizza", {})[1]["totale"], 1)
        st = json.load(urllib.request.urlopen(base + "/api/stato"))["fatture"]
        self.assertTrue(st["configurato"])
        self.assertEqual(st["elenco"][0]["calc"]["bonifico"], 741.32)
        self.assertIn("incassata", post("/api/fatture/a", {"incassata": True})[1]["messaggio"])
        self.assertIn("tornata", post("/api/fatture/a", {"incassata": False})[1]["messaggio"])
        s.guasto = True
        self.assertEqual(post("/api/fatture/sincronizza", {})[0], 400)
        c.ada.archivio = Archivio(c.ada, ClienteScript("", ""), CFG)
        self.assertEqual(post("/api/fatture/a", {"incassata": True})[0], 400)
        self.assertFalse(json.load(urllib.request.urlopen(base + "/api/stato"))["fatture"]["configurato"])


class TestImpostazioni(Base):
    URL = "https://script.google.com/macros/s/ABC/exec"

    def avvia(self, token, script):
        c = costruisci(llm=FinteRisposte(), home=Path(self.tmp.name), movimenti=self.mov, token=token)
        c.ada.archivio = Archivio(c.ada, ClienteScript("", ""), Config(url="", token=""))
        c.nuovo_cliente = lambda url, tok: script
        self.addCleanup(c.db.c.close)
        srv = crea_server(c, "127.0.0.1", 0)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        self.addCleanup(srv.server_close)
        base = f"http://127.0.0.1:{srv.server_address[1]}"

        def post(path, dati, auth=None):
            h = {"Content-Type": "application/json"}
            if auth:
                h["Authorization"] = "Bearer " + auth
            req = urllib.request.Request(base + path, data=json.dumps(dati).encode(), headers=h)
            try:
                with urllib.request.urlopen(req) as r:
                    return r.status, json.load(r)
            except urllib.error.HTTPError as e:
                return e.code, json.load(e)
        return c, post

    def test_senza_token_di_accesso_non_salva_nulla(self):
        c, post = self.avvia("", FintoScript())
        codice, j = post("/api/impostazioni/fatture", {"url": self.URL, "token": "x"})
        self.assertEqual(codice, 403)
        self.assertIn("ADA_TOKEN", j["errore"])
        self.assertFalse((Path(self.tmp.name) / "segreti.json").exists())

    def test_con_token_prova_salva_applica_e_resta_dopo_il_riavvio(self):
        s = FintoScript([fattura("a", 808)])
        c, post = self.avvia("abc", s)
        codice, j = post("/api/impostazioni/fatture", {"url": self.URL, "token": "codice"}, auth="abc")
        self.assertEqual((codice, j["totale"]), (200, 1))
        self.assertTrue(c.ada.archivio.configurato)
        f = Path(self.tmp.name) / "segreti.json"
        self.assertEqual(oct(f.stat().st_mode & 0o777), "0o600")
        c2 = costruisci(llm=FinteRisposte(), home=Path(self.tmp.name), movimenti=self.mov, token="abc")
        self.addCleanup(c2.db.c.close)
        self.assertEqual((c2.ada.archivio.cliente.url, c2.ada.archivio.cliente.token), (self.URL, "codice"))
        self.assertTrue(c2.ada.archivio.configurato)

    def test_indirizzo_non_google_o_codice_vuoto(self):
        c, post = self.avvia("abc", FintoScript())
        self.assertEqual(post("/api/impostazioni/fatture", {"url": "https://evil.example.com/x", "token": "t"}, auth="abc")[0], 400)
        self.assertEqual(post("/api/impostazioni/fatture", {"url": self.URL, "token": ""}, auth="abc")[0], 400)
        self.assertEqual(post("/api/impostazioni/fatture", {"url": self.URL, "token": "t"})[0], 401)  # senza il token di Ada
        self.assertFalse((Path(self.tmp.name) / "segreti.json").exists())

    def test_script_che_rifiuta_non_viene_salvato(self):
        s = FintoScript()
        s.guasto = True
        c, post = self.avvia("abc", s)
        codice, j = post("/api/impostazioni/fatture", {"url": self.URL, "token": "sbagliato"}, auth="abc")
        self.assertEqual(codice, 400)
        self.assertIn("non ha accettato", j["errore"])
        self.assertFalse((Path(self.tmp.name) / "segreti.json").exists())
        self.assertFalse(c.ada.archivio.configurato)

    def test_stato_dice_se_il_token_c_e(self):
        c, post = self.avvia("abc", FintoScript())
        self.assertTrue(c.fatture_stato()["token_attivo"])
        c.token = ""
        self.assertFalse(c.fatture_stato()["token_attivo"])


if __name__ == "__main__":
    unittest.main()
