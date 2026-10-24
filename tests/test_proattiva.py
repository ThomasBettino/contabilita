import json
import os
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

from src.ada import cervello
from src.ada.notifica import Notifica
from src.ada.pianificatore import Pianificatore, prossima_esecuzione
from src.ada.server import costruisci, crea_server
from tests.test_ada import FinteRisposte, testo, usa


def con_uso(r, i=1000, o=200):
    return {**r, "usage": {"input_tokens": i, "output_tokens": o}}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.avvisi = []

    def ctx(self, llm=None):
        c = costruisci(llm=llm or FinteRisposte(), home=Path(self.tmp.name), movimenti=Path(self.tmp.name) / "n.db", token="")
        c.ada.notifica = lambda t, x, i="ada": self.avvisi.append((t, x, i))
        self.addCleanup(c.db.c.close)
        return c


class TestOrari(unittest.TestCase):
    def test_prossima_esecuzione(self):
        with mock.patch.dict(os.environ, {"ADA_FUSO": "UTC"}):
            import calendar
            t20 = calendar.timegm((2026, 10, 23, 20, 0, 0))
            t22 = calendar.timegm((2026, 10, 23, 22, 0, 0))
            self.assertEqual(prossima_esecuzione("21:00", None, t20), calendar.timegm((2026, 10, 23, 21, 0, 0)))
            self.assertEqual(prossima_esecuzione("21:00", None, t22), calendar.timegm((2026, 10, 24, 21, 0, 0)))
            self.assertEqual(prossima_esecuzione(None, 360, t20), t20 + 21600)


class TestPianificatore(Base):
    def test_routine_predefinite_e_non_duplicate(self):
        c = self.ctx()
        Pianificatore(c.ada)
        self.assertEqual([r["nome"] for r in c.pian.elenco()], ["riepilogo_sera", "miglioria_quotidiana", "collaudo", "studio", "lettura", "notifiche", "agenda", "agenda_mattina", "fatture", "miglioramento", "promemoria_approvazioni"])

    def test_riepilogo_gira_una_volta_scrive_in_chat_e_avvisa_senza_cifre(self):
        c = self.ctx(FinteRisposte(con_uso(testo("Oggi 0 spese, tutto tranquillo."))))
        rid = c.db.uno("SELECT id FROM routine WHERE nome='riepilogo_sera'")["id"]
        c.db.esegui("UPDATE routine SET prossima=0 WHERE id=?", (rid,))
        c.pian.tick()
        c.pian.tick()  # il secondo tick non deve rieseguire
        self.assertEqual(len(c.ada.llm.chiamate), 1)
        self.assertIn("tranquillo", c.db.uno("SELECT testo FROM chat ORDER BY id DESC")["testo"])
        self.assertEqual(self.avvisi[-1][2], "ada-routine")
        self.assertNotIn("€", self.avvisi[-1][1])
        self.assertGreater(c.db.uno("SELECT prossima FROM routine WHERE id=?", (rid,))["prossima"], time.time())

    def test_limite_di_consumo_ferma_le_routine_ma_non_la_chat(self):
        c = self.ctx(FinteRisposte(testo("ok chat")))
        c.pian.imposta_ritmo("leggero")  # moltiplicatore 1: il tetto è proprio quello impostato
        with mock.patch.object(cervello, "LIMITE_TOKEN", 100):
            c.db.esegui("INSERT INTO consumi VALUES (?,?,?,?)", ("auto:" + time.strftime("%Y-%m-%d"), 90, 20, 1))
            rid = c.db.uno("SELECT id FROM routine WHERE nome='riepilogo_sera'")["id"]
            self.assertIn("limite di consumo", c.pian.esegui(rid))
            self.assertEqual(c.ada.llm.chiamate, [])
            self.assertEqual(c.ada.chiacchiera("ciao"), "ok chat")  # la chat dell'utente non ha tetto

    def test_miglioramento_senza_segnalazioni_non_costa_nulla(self):
        c = self.ctx()
        rid = c.db.uno("SELECT id FROM routine WHERE nome='miglioramento'")["id"]
        self.assertIn("niente da fare", c.pian.esegui(rid))
        self.assertEqual(c.ada.llm.chiamate, [])

    def test_miglioramento_con_segnalazione_e_senza_schermo(self):
        llm = FinteRisposte(con_uso(usa("telefono_schermo")), con_uso(testo("Sistemato.")))
        c = self.ctx(llm)
        c.ada.segnala("revisore", "ha sbagliato un totale", "utente")
        rid = c.db.uno("SELECT id FROM routine WHERE nome='miglioramento'")["id"]
        c.pian.esegui(rid)
        self.assertEqual(len(llm.chiamate), 2)
        self.assertFalse(c.ada.automatico)  # il flag si spegne a fine lavoro

    def test_schermo_vietato_in_automatico(self):
        c = self.ctx()
        c.ada.automatico = True
        self.assertIn("non uso lo schermo", c.ada._esegui("ada", "telefono_schermo", {}))

    def test_promemoria_solo_per_cose_ferme(self):
        c = self.ctx()
        rid = c.db.uno("SELECT id FROM routine WHERE nome='promemoria_approvazioni'")["id"]
        self.assertIn("Niente fermo", c.pian.esegui(rid))
        c.ada._esegui("ada", "richiedi_approvazione", {"tipo": "altro", "titolo": "x", "dettaglio": "y"})
        self.avvisi.clear()
        self.assertIn("Niente fermo", c.pian.esegui(rid))  # troppo recente
        c.db.esegui("UPDATE approvazioni SET ts=ts-8000")
        self.assertIn("Promemoria inviato", c.pian.esegui(rid))
        self.assertEqual(self.avvisi[-1][2], "ada-promemoria")

    def test_errore_di_una_routine_non_ferma_il_pianificatore(self):
        c = self.ctx()
        rid = c.db.uno("SELECT id FROM routine WHERE nome='promemoria_approvazioni'")["id"]
        with mock.patch.object(c.pian, "_promemoria_approvazioni", side_effect=RuntimeError("boom")):
            self.assertIn("Errore", c.pian.esegui(rid))
        self.assertIsNotNone(c.db.uno("SELECT ultima FROM routine WHERE id=?", (rid,))["ultima"])


class TestMiglioriaQuotidiana(Base):
    IDEA = {"titolo": "Grafico delle spese per settimana", "descrizione": "Nella scheda Soldi un grafico a barre con le uscite di "
            "ogni settimana, per vedere subito se questa è più cara delle altre.", "motivo": "Oggi il confronto tra settimane si fa a mente."}

    def test_il_mandato_e_solo_di_ada_e_dice_di_agire(self):
        llm = FinteRisposte(testo("ok"), testo("ok"))
        c = self.ctx(llm)
        c.ada.chiacchiera("ciao")
        self.assertIn("Non chiedere «quale vuoi che faccia partire»", llm.chiamate[0]["system"])
        c.ada._delega("revisore", "controlla 2+2")
        self.assertNotIn("Non chiedere «quale vuoi che faccia partire»", llm.chiamate[1]["system"])

    def test_routine_quotidiana_esiste_alle_6_30_e_guida_a_agire(self):
        c = self.ctx()
        r = c.db.uno("SELECT * FROM routine WHERE nome='miglioria_quotidiana'")
        self.assertEqual((r["ora"], r["tipo"]), ("06:30", "ada"))
        for strumento in ("migliora_prompt", "regola_categoria", "proponi_idea", "stato_sistema"):
            self.assertIn(strumento, r["prompt"])

    def test_idea_una_al_giorno_con_approvazione_e_notifica(self):
        c = self.ctx()
        self.assertIn("proposta all'utente", c.ada._esegui("ada", "proponi_idea", self.IDEA))
        self.assertEqual(self.avvisi[-1][0], "Ada ha bisogno di te")
        self.assertEqual(c.db.uno("SELECT tipo FROM approvazioni")["tipo"], "idea")
        altra = {**self.IDEA, "titolo": "Un'altra funzione molto diversa"}
        self.assertIn("Una idea nuova al giorno", c.ada._esegui("ada", "proponi_idea", altra))

    def test_idea_non_valida_o_doppia(self):
        c = self.ctx()
        self.assertIn("Servono titolo", c.ada._esegui("ada", "proponi_idea", {"titolo": "boh", "descrizione": "x", "motivo": "y"}))
        c.ada._esegui("ada", "proponi_idea", self.IDEA)
        c.db.esegui("UPDATE idee SET ts=ts-90000")  # il giorno dopo
        doppia = {**self.IDEA, "titolo": "Grafico delle spese per settimane"}
        self.assertIn("già proposta", c.ada._esegui("ada", "proponi_idea", doppia))

    def test_troppe_idee_aperte(self):
        c = self.ctx()
        for i in range(cervello.MAX_IDEE_APERTE):
            c.db.esegui("INSERT INTO idee (ts, titolo, descrizione, motivo, stato) VALUES (?,?,?,?,'proposta')",
                        (time.time() - 90000 * (i + 2), f"Idea numero {i} diversa dalle altre", "d" * 40, "m" * 12))
        self.assertIn("troppe idee aperte", c.ada._esegui("ada", "proponi_idea", self.IDEA))

    def test_approvare_o_rifiutare_aggiorna_l_idea(self):
        c = self.ctx()
        c.ada._esegui("ada", "proponi_idea", self.IDEA)
        a = c.db.uno("SELECT id FROM approvazioni")
        c.ada.risolvi(a["id"], "approva")
        self.assertEqual(c.db.uno("SELECT stato FROM idee")["stato"], "approvata")
        c.ada.idea_fatta(1)
        self.assertEqual(c.db.uno("SELECT stato FROM idee")["stato"], "fatta")
        with self.assertRaises(ValueError):
            c.ada.idea_fatta(1)
        c.db.esegui("UPDATE idee SET ts=ts-90000")
        c.ada._esegui("ada", "proponi_idea", {**self.IDEA, "titolo": "Promemoria per le scadenze di fine mese"})
        c.ada.risolvi(c.db.uno("SELECT id FROM approvazioni WHERE stato='in_attesa'")["id"], "rifiuta")
        self.assertEqual(c.db.uno("SELECT stato FROM idee WHERE id=2")["stato"], "rifiutata")

    def test_regola_di_categoria_si_applica_e_resta_dopo_il_riavvio(self):
        import sqlite3
        mov = Path(self.tmp.name) / "m.db"
        k = sqlite3.connect(mov)
        k.execute("CREATE TABLE movimenti (chiave TEXT, quando TEXT, importo REAL, controparte TEXT, testo TEXT)")
        k.execute("INSERT INTO movimenti VALUES ('1', ?, -5.48, 'Anthropic', '')", (time.strftime("%Y-%m-%d 10:00:00"),))
        k.commit()
        k.close()
        c = costruisci(llm=FinteRisposte(), home=Path(self.tmp.name), movimenti=mov, token="")
        self.addCleanup(c.db.c.close)
        self.assertIn("Senza categoria (finiti in Altro): Anthropic", c.ada._esegui("ada", "riepilogo_spese", {}))
        self.assertIn("va in Abbonamenti", c.ada._esegui("ada", "regola_categoria", {"azione": "aggiungi", "parola": "Anthropic", "categoria": "Abbonamenti"}))
        self.assertNotIn("Senza categoria", c.ada._esegui("ada", "riepilogo_spese", {}))
        c2 = costruisci(llm=FinteRisposte(), home=Path(self.tmp.name), movimenti=mov, token="")
        self.addCleanup(c2.db.c.close)
        self.assertEqual(c2.soldi.regole, {"anthropic": "Abbonamenti"})
        c2.ada._esegui("ada", "regola_categoria", {"azione": "rimuovi", "parola": "anthropic"})
        self.assertEqual(c2.soldi.regole, {})

    def test_regola_categoria_valida_i_dati(self):
        c = self.ctx()
        self.assertIn("non valida", c.ada._esegui("ada", "regola_categoria", {"azione": "aggiungi", "parola": "x", "categoria": "Altro"}))
        self.assertIn("non valida", c.ada._esegui("ada", "regola_categoria", {"azione": "aggiungi", "parola": "bar sport", "categoria": "Inventata"}))
        self.assertEqual(c.ada._esegui("revisore", "regola_categoria", {"azione": "aggiungi", "parola": "bar sport", "categoria": "Altro"}),
                         "Strumento non consentito.")

    def test_stato_sistema_mostra_idee_e_attivita(self):
        c = self.ctx()
        c.ada._esegui("ada", "proponi_idea", self.IDEA)
        c.ada.log("sistema", "errore", "qualcosa è andato storto")
        out = c.ada._esegui("ada", "stato_sistema", {})
        self.assertIn("Grafico delle spese per settimana [proposta]", out)
        self.assertIn("qualcosa è andato storto", out)


class TestChiStaLavorando(Base):
    def test_in_corso_solo_mentre_lavora_davvero(self):
        visto = {}
        c = self.ctx()

        class Spia(FinteRisposte):
            def __call__(inner, system, messaggi, strumenti=None, max_tokens=1500):
                visto["durante"] = {k: v["cosa"] for k, v in c.ada.lavori.items()}
                visto["stato"] = {a["nome"]: a["attivo"] for a in c.stato()["agenti"]}
                return super().__call__(system, messaggi, strumenti, max_tokens)
        c.ada.llm = Spia(testo("Il calcolo è giusto."))
        c.ada._delega("revisore", "controlla 2+2")
        self.assertEqual(visto["durante"], {"revisore": "controlla 2+2"})
        self.assertTrue(visto["stato"]["revisore"])
        self.assertFalse(visto["stato"]["sviluppo"])        # nessuno acceso per finta
        self.assertEqual(c.ada.lavori, {})                   # a fine lavoro si spegne
        self.assertFalse({a["nome"]: a["attivo"] for a in c.stato()["agenti"]}["revisore"])

    def test_si_spegne_anche_se_il_lavoro_fallisce(self):
        from src.ada.llm import ErroreLLM

        class Rotto(FinteRisposte):
            def __call__(self, *a, **k):
                raise ErroreLLM("rete")
        c = self.ctx(Rotto())
        c.ada._delega("sviluppo", "fai qualcosa")
        self.assertEqual(c.ada.lavori, {})

    def test_ada_risulta_al_lavoro_durante_la_chat_e_la_routine(self):
        c = self.ctx()
        durante = []

        class Spia(FinteRisposte):
            def __call__(inner, *a, **k):
                durante.append(dict(c.ada.lavori.get("ada") or {}))
                return super().__call__(*a, **k)
        c.ada.llm = Spia(testo("ok"), testo("fatto"))
        c.ada.chiacchiera("ciao")
        c.ada.lavoro_proattivo("fai il riepilogo per favore", "riepilogo_sera")
        self.assertEqual(durante[0]["cosa"], "Sto rispondendo alla tua chat")
        self.assertEqual(durante[1]["cosa"], "Routine: riepilogo sera")
        self.assertEqual(c.ada.lavori, {})

    def test_dettaglio_agente_per_il_popup(self):
        import json as _json
        import urllib.request as _rq
        c = self.ctx()
        c.ada.log("revisore", "lavoro", "controlla 2+2")
        c.ada.log("revisore", "risposta", "Il calcolo è giusto.")
        c.ada.segnala("revisore", "ha sbagliato un totale", "utente")
        c.ada.lavori["revisore"] = {"cosa": "Ricontrollo i totali", "da": int(time.time()) - 5}
        srv = crea_server(c, "127.0.0.1", 0)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        self.addCleanup(srv.server_close)
        d = _json.load(_rq.urlopen(f"http://127.0.0.1:{srv.server_address[1]}/api/agenti/revisore"))
        self.assertEqual(d["titolo"], "Revisore")
        self.assertEqual(d["in_corso"]["cosa"], "Ricontrollo i totali")
        self.assertEqual([a["azione"] for a in d["attivita"]], ["segnalazione", "risposta", "lavoro"])  # dal più recente
        self.assertIn("riepilogo_spese", d["strumenti"])
        self.assertNotIn("migliora_prompt", d["strumenti"])  # il revisore non può migliorare i prompt
        self.assertEqual(d["segnalazioni"][0]["problema"], "ha sbagliato un totale")
        self.assertIn("Revisore", d["prompt"])


class TestStatoSistema(Base):
    def test_stato_sistema_mostra_cosa_aspetta_l_utente(self):
        c = self.ctx()
        c.ada._esegui("contabilita_piva", "richiedi_approvazione", {"tipo": "pagamento", "titolo": "F24 acconto", "dettaglio": "x"})
        c.ada.segnala("revisore", "ha sbagliato un totale", "utente")
        out = c.ada._esegui("ada", "stato_sistema", {})
        self.assertIn("IN ATTESA DELL'UTENTE: 1", out)
        self.assertIn("F24 acconto", out)
        self.assertIn("SEGNALAZIONI APERTE: 1", out)
        self.assertIn("riepilogo_sera", out)
        self.assertEqual(c.ada._esegui("revisore", "stato_sistema", {}), "Strumento non consentito.")

    def test_prompt_delle_routine_di_sistema_si_riallinea_all_avvio(self):
        c = self.ctx()
        c.db.esegui("UPDATE routine SET prompt='vecchio prompt' WHERE nome='riepilogo_sera'")
        Pianificatore(c.ada)
        self.assertIn("stato_sistema", c.db.uno("SELECT prompt FROM routine WHERE nome='riepilogo_sera'")["prompt"])

    def test_riepilogo_spese_indica_l_ultimo_movimento(self):
        import sqlite3
        db = Path(self.tmp.name) / "m.db"
        k = sqlite3.connect(db)
        k.execute("CREATE TABLE movimenti (chiave TEXT, quando TEXT, importo REAL, controparte TEXT, testo TEXT)")
        mese = time.strftime("%Y-%m")
        k.execute("INSERT INTO movimenti VALUES ('1', ?, -5.8, 'Cristal Bar', '')", (f"{mese}-23 14:20:39",))
        k.commit()
        k.close()
        c = costruisci(llm=FinteRisposte(), home=Path(self.tmp.name), movimenti=db, token="")
        self.addCleanup(c.db.c.close)
        self.assertIn(f"Ultimo movimento letto: {mese}-23 14:20:39", c.ada._esegui("ada", "riepilogo_spese", {}))


class TestRoutineDiAda(Base):
    def crea(self, c, **kw):
        a = {"azione": "crea", "nome": "controllo_bollette", "descrizione": "Controlla le bollette",
             "prompt": "Controlla se ci sono bollette in arrivo e riassumile in due righe.", "ora": "09:00"}
        a.update(kw)
        return c.ada._esegui("ada", "gestisci_routine", a)

    def test_crea_modifica_disattiva(self):
        c = self.ctx()
        self.assertIn("creata", self.crea(c))
        self.assertIn("Esiste già", self.crea(c))
        self.assertIn("modificata", self.crea(c, azione="modifica", ora=None, ogni_min=60))
        self.assertIn("disattivata", c.ada._esegui("ada", "gestisci_routine", {"azione": "disattiva", "nome": "controllo_bollette"}))
        self.assertEqual(c.db.uno("SELECT attiva FROM routine WHERE nome='controllo_bollette'")["attiva"], 0)

    def test_limiti(self):
        c = self.ctx()
        self.assertIn("Intervallo minimo", self.crea(c, ora=None, ogni_min=5))
        self.assertIn("Ora non valida", self.crea(c, ora="25:99"))
        self.assertIn("solo uno", self.crea(c, ogni_min=60))
        self.assertIn("almeno 20", self.crea(c, prompt="boh"))
        for i in range(cervello.MAX_ROUTINE):
            self.assertIn("creata", self.crea(c, nome=f"r{i}"))
        self.assertIn("Massimo", self.crea(c, nome="una_di_troppo"))

    def test_routine_di_sistema_solo_on_off(self):
        c = self.ctx()
        self.assertIn("solo attivare", c.ada._esegui("ada", "gestisci_routine", {
            "azione": "modifica", "nome": "miglioramento", "prompt": "x" * 30, "ogni_min": 60}))
        self.assertIn("attivata", c.ada._esegui("ada", "gestisci_routine", {"azione": "attiva", "nome": "miglioramento"}))

    def test_solo_ada_gestisce_routine(self):
        c = self.ctx()
        self.assertEqual(c.ada._esegui("acquisti", "gestisci_routine", {"azione": "crea", "nome": "x"}), "Strumento non consentito.")


class TestConsumi(Base):
    def test_la_chat_non_consuma_il_tetto_delle_routine(self):
        with mock.patch.object(cervello, "LIMITE_TOKEN", 1000):
            c = self.ctx(FinteRisposte(con_uso(testo("a"), 4000, 500), con_uso(testo("b"), 300, 50)))
            c.ada.chiacchiera("ciao")
            co = c.ada.consumo_oggi()
            self.assertEqual((co["totale"], co["automatici"]), (4500, 0))
            self.assertFalse(c.ada.sopra_limite())
            c.ada.lavoro_proattivo("fai un riepilogo breve per favore", "prova")
            co = c.ada.consumo_oggi()
            self.assertEqual((co["totale"], co["automatici"]), (4850, 350))

    def test_la_cache_pesa_un_decimo(self):
        c = self.ctx(FinteRisposte({**testo("ok"), "usage": {"input_tokens": 100, "cache_creation_input_tokens": 200,
                                                                "cache_read_input_tokens": 5000, "output_tokens": 50}}))
        c.ada.chiacchiera("ciao")
        self.assertEqual(c.ada.consumo_oggi()["totale"], 100 + 200 + 500 + 50)


class TestNotificheEConsumi(Base):
    def test_notifica_quando_serve_una_decisione_senza_dettagli(self):
        c = self.ctx()
        c.ada._esegui("ada", "richiedi_approvazione", {"tipo": "pagamento", "titolo": "F24 da 300 euro", "dettaglio": "x", "importo": 300})
        self.assertEqual(self.avvisi[-1][0], "Ada ha bisogno di te")
        self.assertNotIn("300", self.avvisi[-1][1])

    def test_notifica_ordine_pronto(self):
        c = self.ctx()
        c.ada._esegui("acquisti", "proponi_acquisto", {"richiesta": "cuffie", "opzioni": [{"nome": "A", "prezzo_totale": 10}]})
        c.ada.risolvi(1, "approva", 0)
        c.ada.autorizza(1)
        c.ada._pronto(1, "alla cassa")
        self.assertEqual(self.avvisi[-1][0], "Ordine pronto")

    def test_conta_i_token(self):
        c = self.ctx(FinteRisposte(con_uso(testo("ciao"), 500, 40)))
        c.ada.chiacchiera("ciao")
        co = c.ada.consumo_oggi()
        self.assertEqual((co["totale"], co["chiamate"]), (540, 1))

    def test_notifica_termux_non_rompe_se_manca(self):
        def manca(*a, **k):
            raise FileNotFoundError
        self.assertFalse(Notifica(esegui=manca).invia("a", "b"))
        chiamate = []
        Notifica(esegui=lambda cmd, **k: chiamate.append(cmd)).invia("Ada", "ciao")
        self.assertIn("termux-open-url", chiamate[0][-1])


class TestServerRoutine(Base):
    def test_api_routine(self):
        c = self.ctx()
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

        stato = json.load(urllib.request.urlopen(base + "/api/stato"))
        self.assertEqual(len(stato["routine"]), 11)
        self.assertEqual(stato["consumo"]["totale"], 0)
        rid = next(r["id"] for r in stato["routine"] if r["nome"] == "miglioramento")
        self.assertIn("niente da fare", post(f"/api/routine/{rid}/esegui", {})[1]["esito"])
        self.assertEqual(post(f"/api/routine/{rid}", {"attiva": False})[0], 200)
        c.ada._esegui("ada", "proponi_idea", {"titolo": "Grafico delle spese per settimana", "motivo": "serve davvero",
                      "descrizione": "Nella scheda Soldi un grafico a barre con le uscite di ogni settimana."})
        c.ada.risolvi(c.db.uno("SELECT id FROM approvazioni")["id"], "approva")
        idee = json.load(urllib.request.urlopen(base + "/api/stato"))["idee"]
        self.assertIn("Vincoli: non toccare i confini di sicurezza", idee[0]["brief"])
        self.assertEqual(post("/api/idee/1/fatta", {})[0], 200)
        self.assertEqual(post("/api/idee/1/fatta", {})[0], 400)
        self.assertEqual(post("/api/routine/999/esegui", {})[0], 404)


if __name__ == "__main__":
    unittest.main()
