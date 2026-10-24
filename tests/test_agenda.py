import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from src.ada import cervello
from src.ada.agenda import Agenda, leggi_quando
from src.ada.agenti import SEED_PRECEDENTI, Squadra
from src.ada.cervello import STRUMENTI_ADA, strumenti_di
from src.ada.db import DB
from src.ada.server import costruisci, crea_server
from tests.test_ada import FinteRisposte, testo, usa

PROMPT_VECCHIO_VENDITE = "# Clienti e vendite\n\nSei l'assistente per clienti, preventivi e solleciti di pagamento. Lavori per Ada.\n\n## Stato attuale\nNon hai ancora accesso a un archivio clienti né all'email. Lavori su ciò che l'utente o Ada ti passano: prepari preventivi, testi di solleciti gentili e fermi, liste di clienti da ricontattare.\n\n## Come lavori\n- Tono professionale e cordiale, mai aggressivo nei solleciti.\n- Ogni sollecito indica: fattura, importo, scadenza, richiesta chiara.\n- Non inviare nulla: prepari il testo, la decisione di inviare è dell'utente.\n"
PROMPT_VECCHIO_QUOTIDIANO = "# Quotidiano\n\nSei l'assistente della gestione quotidiana dell'utente: email, calendario, promemoria, ricerche. Lavori per Ada.\n\n## Stato attuale\nGmail, Calendario e WhatsApp non sono ancora collegati. Finché non lo sono, aiuti a organizzare e preparare: bozze di messaggi, liste di cose da fare, priorità, promemoria da proporre. Dillo chiaramente quando una richiesta richiede un accesso che non c'è.\n\n## Come lavori\n- Prepara bozze, non inviarle: l'invio lo decide l'utente tramite Ada.\n- Dai priorità: cosa è urgente oggi, cosa può aspettare.\n- Risposte brevi e già pronte da usare.\n"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)

    def ctx(self, llm=None, token=""):
        c = costruisci(llm=llm or FinteRisposte(), home=self.home, movimenti=self.home / "n.db", token=token)
        self.addCleanup(c.db.c.close)
        self.t = c.ada.agenda._epoca("2026-10-24", "09:00")  # sabato 24 ottobre 2026, ore 9
        c.ada.agenda.adesso = c.pian.adesso = lambda: self.t
        self.inviate = []
        c.ada.notifica = lambda titolo, testo_, id_: self.inviate.append((titolo, testo_, id_))
        return c

    def quando(self, c, giorno, ora):
        return c.ada.agenda._epoca(giorno, ora)


class TestLeggiQuando(unittest.TestCase):
    def test_formati_validi(self):
        self.assertEqual(leggi_quando("2026-10-24"), ("2026-10-24", ""))
        self.assertEqual(leggi_quando("2026-10-24 09:30"), ("2026-10-24", "09:30"))
        self.assertEqual(leggi_quando(" 2026-10-24T9:05 "), ("2026-10-24", "09:05"))

    def test_formati_sbagliati(self):
        for brutto in ("domani", "24/10/2026", "2026-13-01", "2026-02-30", "2026-10-24 25:00", "2026-10-24 09:75", "", None):
            with self.assertRaises(ValueError, msg=str(brutto)):
                leggi_quando(brutto)


class TestAgenda(Base):
    def agenda(self):
        return self.ctx().ada.agenda

    def test_aggiungi_e_leggi(self):
        a = self.agenda()
        v = a.aggiungi("  Chiamare   Zanetti ", "2026-10-25 09:30", note=" Vuole  pensarci ", origine="clienti_vendite")
        self.assertEqual((v["titolo"], v["giorno"], v["ora"], v["tipo"], v["note"], v["origine"]),
                         ("Chiamare Zanetti", "2026-10-25", "09:30", "promemoria", "Vuole pensarci", "clienti_vendite"))
        self.assertEqual(a.etichetta(v["giorno"], v["ora"]), "domani 09:30")
        self.assertEqual(a.etichetta("2026-10-24"), "oggi")
        self.assertEqual(a.etichetta("2026-10-29", "15:00"), "giovedì 29/10 15:00")
        self.assertEqual(a.adesso_testo(), "sabato 2026-10-24 09:00")

    def test_dati_sbagliati(self):
        a = self.agenda()
        casi = [(("x", "2026-10-25"), "titolo"), (("Cosa", "2026-10-25", "boh"), "tipo"), (("Cosa", "2026-10-25", "evento", "", "ogni tanto"), "ripetizione"),
                (("Cosa", "2026-10-25", "evento", "", "", -5), "preavviso"), (("Cosa", "2026-10-25", "evento", "", "", 99999), "preavviso"),
                (("Cosa", "2026-10-25", "evento", "", "", "abc"), "preavviso"), (("Cosa", "2026-10-23"), "passata"),
                (("Cosa", "2026-10-24 07:00"), "passata"), (("Cosa", "ieri"), "data")]
        for args, parte in casi:
            with self.assertRaises(ValueError, msg=str(args)) as e:
                a.aggiungi(*args)
            self.assertIn(parte, str(e.exception).lower(), args)
        a.aggiungi("Appena passato", "2026-10-24 08:30")  # entro un'ora si accetta
        a.aggiungi("Oggi tutto il giorno", "2026-10-24")

    def test_elenco_ordine_scaduti_e_fatti(self):
        c = self.ctx()
        a = c.ada.agenda
        c.db.esegui("INSERT INTO eventi (ts, titolo, giorno, ora) VALUES (1, 'Vecchio', '2026-10-23', '')")
        c.db.esegui("INSERT INTO eventi (ts, titolo, giorno, ora) VALUES (1, 'Stamattina', '2026-10-24', '07:00')")
        a.aggiungi("Pomeriggio", "2026-10-25 15:00")
        a.aggiungi("Mattina", "2026-10-25 09:30")
        a.aggiungi("Tutto il giorno", "2026-10-25")
        lontano = a.aggiungi("Lontano", "2026-12-25 10:00")
        fatto = a.aggiungi("Finito", "2026-10-26 10:00")
        a.fatto(fatto["id"])
        e = a.elenco(14)
        self.assertEqual([v["titolo"] for v in e["scaduti"]], ["Vecchio", "Stamattina"])
        self.assertEqual([v["titolo"] for v in e["prossimi"]], ["Tutto il giorno", "Mattina", "Pomeriggio"])  # senza ora per primo
        self.assertNotIn(lontano["id"], [v["id"] for v in e["prossimi"]])
        self.assertEqual([v["titolo"] for v in e["fatti"]], ["Finito"])
        testo_ = a.testo(14)
        self.assertIn("SCADUTI (da chiudere o spostare):", testo_)
        self.assertIn("domani 09:30 · Mattina", testo_)

    def test_avviso_all_ora_e_con_preavviso(self):
        c = self.ctx()
        a = c.ada.agenda
        a.aggiungi("All'ora", "2026-10-24 10:00")
        a.aggiungi("Con preavviso", "2026-10-24 11:00", preavviso=60)
        a.aggiungi("Tutto il giorno", "2026-10-25")
        self.assertEqual(a.da_avvisare(self.t), [])  # 9:00: niente ancora
        t10 = self.quando(c, "2026-10-24", "10:00")
        self.assertEqual([v["titolo"] for v in a.da_avvisare(t10)], ["All'ora", "Con preavviso"])  # il secondo avvisa alle 10 (11 meno un'ora)
        self.assertEqual([v["titolo"] for v in a.da_avvisare(self.quando(c, "2026-10-25", "08:00"))][-1], "Tutto il giorno")  # alle 8

    def test_avviso_in_ritardo_e_troppo_tardi(self):
        c = self.ctx()
        a = c.ada.agenda
        v = a.aggiungi("Dimenticato", "2026-10-24 09:30")
        tardi = self.quando(c, "2026-10-24", "11:00")
        (x,) = a.da_avvisare(tardi)
        self.assertTrue(x["in_ritardo"])
        self.assertEqual(a.da_avvisare(self.quando(c, "2026-10-24", "09:31"))[0]["in_ritardo"], False)
        self.assertEqual(a.da_avvisare(self.quando(c, "2026-10-25", "09:31")), [])  # più di 12 ore: si salta in silenzio
        self.t = self.quando(c, "2026-10-25", "10:00")
        self.assertEqual([x["titolo"] for x in a.elenco(1)["scaduti"]], ["Dimenticato"])  # resta tra gli scaduti da chiudere

    def test_segna_avvisato_una_volta_sola(self):
        c = self.ctx()
        a = c.ada.agenda
        v = a.aggiungi("Una volta", "2026-10-24 10:00")
        t10 = self.quando(c, "2026-10-24", "10:00")
        self.assertEqual(len(a.da_avvisare(t10)), 1)
        a.segna_avvisato(v["id"], t10)
        self.assertEqual(a.da_avvisare(t10), [])

    def test_ricorrenze(self):
        c = self.ctx()
        a = c.ada.agenda
        g = a.aggiungi("Ogni giorno", "2026-10-24 10:00", ripeti="giornaliero")
        s = a.aggiungi("Ogni settimana", "2026-10-24 10:00", ripeti="settimanale")
        m = a.aggiungi("Fine mese", "2026-10-31 10:00", ripeti="mensile")
        t10 = self.quando(c, "2026-10-24", "10:00")
        for v in a.da_avvisare(t10):
            a.segna_avvisato(v["id"], t10)
        self.assertEqual((a.voce(g["id"])["giorno"], a.voce(s["id"])["giorno"]), ("2026-10-25", "2026-10-31"))
        self.assertEqual(a.da_avvisare(t10), [])  # riarmati per la prossima volta
        self.t = self.quando(c, "2026-10-31", "10:00")
        for v in a.da_avvisare(self.t):
            a.segna_avvisato(v["id"], self.t)
        self.assertEqual(a.voce(m["id"])["giorno"], "2026-11-30")  # il 31 non c'è: ultimo giorno del mese
        self.assertEqual(a.voce(s["id"])["giorno"], "2026-11-07")
        gennaio = a.aggiungi("Gennaio", "2026-12-31 10:00", ripeti="mensile")
        a._avanza(a.voce(gennaio["id"]))
        self.assertEqual(a.voce(gennaio["id"])["giorno"], "2027-01-31")
        self.assertEqual(a.elenco(1)["scaduti"], [])  # le ricorrenti non sono mai «scadute»

    def test_dopo_un_lungo_spegnimento_la_ricorrenza_salta_a_domani(self):
        c = self.ctx()
        a = c.ada.agenda
        v = a.aggiungi("Giornaliero", "2026-10-24 10:00", ripeti="giornaliero")
        self.t = self.quando(c, "2026-11-03", "12:00")
        a.fatto(v["id"])
        self.assertEqual(a.voce(v["id"])["giorno"], "2026-11-04")

    def test_modifica_fatto_elimina(self):
        c = self.ctx()
        a = c.ada.agenda
        v = a.aggiungi("Chiamare", "2026-10-24 10:00")
        t10 = self.quando(c, "2026-10-24", "10:00")
        a.segna_avvisato(v["id"], t10)
        w = a.modifica(v["id"], quando="2026-10-26 11:00", titolo="Chiamare Rossi")
        self.assertEqual((w["giorno"], w["ora"], w["titolo"]), ("2026-10-26", "11:00", "Chiamare Rossi"))
        self.assertEqual(c.db.uno("SELECT avvisato FROM eventi")["avvisato"], 0)  # spostata: avvisa di nuovo
        with self.assertRaises(ValueError):
            a.modifica(v["id"], quando="2026-10-01")
        self.assertEqual(a.fatto(v["id"])["stato"], "fatto")
        a.elimina(v["id"])
        with self.assertRaises(LookupError):
            a.voce(v["id"])

    def test_contesto_per_ada(self):
        c = self.ctx()
        a = c.ada.agenda
        self.assertEqual(a.contesto(), "")
        a.aggiungi("Domani presto", "2026-10-25 08:00")
        a.aggiungi("Tra tre giorni", "2026-10-27 08:00")
        self.assertEqual(a.contesto(), "AGENDA: domani 08:00 Domani presto (id 1).")
        c.db.esegui("INSERT INTO eventi (ts, titolo, giorno, ora) VALUES (1, 'Vecchio', '2026-10-20', '')")
        self.assertIn("Scaduti non chiusi: 1.", a.contesto())

    def test_riepilogo_mattina(self):
        c = self.ctx()
        a = c.ada.agenda
        self.assertIsNone(a.riepilogo_mattina())
        a.aggiungi("Chiamare Zanetti", "2026-10-24 15:00")
        a.aggiungi("Pagare il bollo", "2026-10-24")
        c.db.esegui("INSERT INTO eventi (ts, titolo, giorno, ora) VALUES (1, 'Vecchio', '2026-10-20', '')")
        titolo, corpo = a.riepilogo_mattina()
        self.assertEqual(titolo, "Agenda di oggi")
        self.assertEqual(corpo, "2 oggi: tutto il giorno Pagare il bollo; 15:00 Chiamare Zanetti; 1 da chiudere")


class TestStrumenti(Base):
    def test_chi_ha_quali_strumenti(self):
        nomi = lambda chi: {t["name"] for t in strumenti_di(chi)}
        agenda = {"agenda_aggiungi", "agenda_elenco", "agenda_cambia"}
        for chi in ("ada", "quotidiano", "clienti_vendite"):
            self.assertTrue(agenda <= nomi(chi), chi)
        for chi in ("revisore", "contabilita_piva", "contabilita_privata", "acquisti", "sviluppo", "collaudatore"):
            self.assertFalse(agenda & nomi(chi), chi)
        self.assertIn("avvisa_utente", nomi("ada"))
        self.assertIn("avvisa_utente", nomi("clienti_vendite"))
        self.assertFalse("avvisa_utente" in nomi("quotidiano"))
        v = nomi("clienti_vendite")
        self.assertTrue({"telefono_apri", "telefono_scrivi", "telefono_tocca", "telefono_schermo", "vendite_coda"} <= v)
        self.assertFalse({"proponi_acquisto", "acquisto_pronto", "gestisci_routine", "migliora_prompt", "delega"} & v)  # niente acquisti né poteri da capo
        self.assertEqual(len([t for t in STRUMENTI_ADA if t["name"] == "agenda_aggiungi"]), 1)

    def test_ada_aggiunge_voce_e_il_log_la_ricorda(self):
        c = self.ctx(FinteRisposte(usa("agenda_aggiungi", titolo="Chiamare Zanetti", quando="2026-10-25 09:30", preavviso_min=10),
                                   testo("Fatto: domani alle 9:30.")))
        self.assertEqual(c.ada.chiacchiera("ricordami domani alle 9:30 di chiamare Zanetti"), "Fatto: domani alle 9:30.")
        (v,) = c.db.tutti("SELECT * FROM eventi")
        self.assertEqual((v["titolo"], v["giorno"], v["ora"], v["preavviso"], v["origine"]), ("Chiamare Zanetti", "2026-10-25", "09:30", 10, "ada"))
        self.assertIn("agenda: aggiunto: Chiamare Zanetti (domani 09:30)", [f"{a['azione']}: {a['dettaglio']}" for a in c.db.tutti("SELECT * FROM attivita")])
        sistema = c.ada.llm.chiamate[0]["system"]
        self.assertIn("Oggi è sabato 2026-10-24 09:00.", sistema)

    def test_errori_dello_strumento_tornano_al_modello(self):
        c = self.ctx()
        r = c.ada._esegui("ada", "agenda_aggiungi", {"titolo": "Cosa", "quando": "domani"})
        self.assertIn("Errore nello strumento agenda_aggiungi", r)
        self.assertIn("La data va scritta così", r)
        self.assertEqual(c.db.tutti("SELECT * FROM eventi"), [])

    def test_elenco_e_cambia(self):
        c = self.ctx()
        e = lambda nome, **a: c.ada._esegui("quotidiano", nome, a)
        e("agenda_aggiungi", titolo="Dentista", quando="2026-10-26 16:00")
        self.assertIn("id 1 · lunedì 26/10 16:00 · Dentista", e("agenda_elenco"))
        self.assertIn("Aggiornato: Dentista, martedì 27/10 16:00.", e("agenda_cambia", id=1, azione="sposta", quando="2026-10-27 16:00"))
        self.assertIn("Aggiornato: Dentista privato", e("agenda_cambia", id=1, azione="rinomina", titolo="Dentista privato"))
        self.assertEqual(e("agenda_cambia", id=1, azione="fatto"), "Segnato come fatto: Dentista privato.")
        self.assertEqual(e("agenda_cambia", id=1, azione="elimina"), "Tolto dall'agenda: Dentista privato.")
        self.assertIn("Errore nello strumento agenda_cambia", e("agenda_cambia", id=1, azione="fatto"))
        self.assertEqual(c.ada._esegui("revisore", "agenda_elenco", {}), "Strumento non consentito.")

    def test_avvisa_utente(self):
        c = self.ctx()
        r = c.ada._esegui("ada", "avvisa_utente", {"titolo": "Bravo!", "testo": "Hai venduto! Parlo con il reparto vendite."})
        self.assertEqual(r, "Notifica inviata.")
        self.assertEqual(self.inviate, [("Bravo!", "Hai venduto! Parlo con il reparto vendite.", "ada-avviso")])
        self.assertIn("Servono un titolo", c.ada._esegui("ada", "avvisa_utente", {"titolo": "x", "testo": " "}))
        for _ in range(5):
            c.ada._esegui("clienti_vendite", "avvisa_utente", {"titolo": "Vendite", "testo": "Aggiornato."})
        self.assertIn("Troppe notifiche", c.ada._esegui("ada", "avvisa_utente", {"titolo": "Ancora", "testo": "Una in più"}))
        self.assertEqual(len(self.inviate), 6)
        c.ada.notifica = None
        c.db.esegui("DELETE FROM attivita")
        self.assertIn("non sono disponibili", c.ada._esegui("ada", "avvisa_utente", {"titolo": "x", "testo": "y"}))

    def test_testi_lunghi_si_accorciano(self):
        c = self.ctx()
        c.ada._esegui("ada", "avvisa_utente", {"titolo": "T" * 100, "testo": "x" * 300})
        self.assertEqual((len(self.inviate[0][0]), len(self.inviate[0][1])), (60, 120))


class TestRoutineAgenda(Base):
    def esegui(self, c, nome):
        return c.pian.esegui(c.db.uno("SELECT id FROM routine WHERE nome=?", (nome,))["id"])

    def test_le_routine_esistono_e_girano_da_sole(self):
        c = self.ctx()
        r = {x["nome"]: (x["ogni_min"], x["ora"], x["attiva"]) for x in c.pian.elenco()}
        self.assertEqual(r["agenda"], (1, None, 1))
        self.assertEqual(r["agenda_mattina"], (None, "07:30", 1))

    def test_avvisa_all_ora_giusta_e_non_due_volte(self):
        c = self.ctx()
        c.ada.agenda.aggiungi("Chiamare Zanetti", "2026-10-24 09:30")
        c.ada.agenda.aggiungi("Riunione", "2026-10-24 11:00", "evento", preavviso=30)
        self.assertEqual(self.esegui(c, "agenda"), "Nessun avviso.")
        self.t = self.quando(c, "2026-10-24", "09:30")
        self.assertEqual(self.esegui(c, "agenda"), "Avvisato: Chiamare Zanetti")
        self.assertEqual(self.inviate, [("Promemoria", "09:30 Chiamare Zanetti", "ada-agenda-1")])
        self.assertEqual(self.esegui(c, "agenda"), "Nessun avviso.")
        self.t = self.quando(c, "2026-10-24", "10:30")
        self.esegui(c, "agenda")
        self.assertEqual(self.inviate[-1], ("Appuntamento", "tra 30 min: Riunione (11:00)", "ada-agenda-2"))
        self.t = self.quando(c, "2026-10-24", "13:30")
        c.db.esegui("INSERT INTO eventi (ts, titolo, giorno, ora) VALUES (1, 'Mancato', '2026-10-24', '12:00')")  # il telefono era spento
        self.esegui(c, "agenda")
        self.assertEqual(self.inviate[-1][1], "12:00 Mancato (in ritardo)")

    def test_senza_notifiche_non_perde_e_registra_solo_i_cambiamenti(self):
        c = self.ctx()
        for _ in range(4):
            self.esegui(c, "agenda")
        self.assertEqual(c.db.uno("SELECT COUNT(*) AS n FROM attivita WHERE azione='agenda'")["n"], 1)  # «Nessun avviso» ripetuto: una riga sola
        c.ada.agenda.aggiungi("Chiamare", "2026-10-24 09:00")
        self.esegui(c, "agenda")
        self.assertEqual(c.db.uno("SELECT COUNT(*) AS n FROM attivita WHERE azione='agenda'")["n"], 2)

    def test_mattina_solo_se_c_e_qualcosa(self):
        c = self.ctx()
        self.assertEqual(self.esegui(c, "agenda_mattina"), "Niente in agenda oggi.")
        self.assertEqual(self.inviate, [])
        c.ada.agenda.aggiungi("Pagare il bollo", "2026-10-24")
        self.assertIn("Avviso del mattino: 1 oggi: tutto il giorno Pagare il bollo", self.esegui(c, "agenda_mattina"))
        self.assertEqual(self.inviate[0][0], "Agenda di oggi")

    def test_non_usa_il_cervello(self):
        c = self.ctx()
        c.ada.agenda.aggiungi("Chiamare", "2026-10-24 09:00")
        self.esegui(c, "agenda")
        self.assertEqual(c.ada.llm.chiamate, [])


class TestVenditeCoda(Base):
    def test_coda_aggiungi_elenco_fatto(self):
        c = self.ctx()
        r = c.ada._esegui("clienti_vendite", "vendite_coda", {"azione": "aggiungi", "frase": "Ho venduto la C3 a Zanetti Emilio, full drive, margine 1800 euro",
                                                               "riassunto": "Vendita a Zanetti Emilio (full drive)"})
        self.assertIn("In coda (id 1)", r)
        self.assertEqual(self.inviate, [("Vendite", "C'è un aggiornamento da riportare nell'app vendite.", "ada-vendite-coda")])  # generica: niente nomi
        self.assertIn("id 1: Vendita a Zanetti Emilio (full drive) | frase: Ho venduto", c.ada._esegui("clienti_vendite", "vendite_coda", {"azione": "elenco"}))
        self.assertEqual(c.ada._esegui("clienti_vendite", "vendite_coda", {"azione": "fatto", "id": 1}), "Segnato come riportato nell'app.")
        self.assertIn("Coda vuota", c.ada._esegui("clienti_vendite", "vendite_coda", {"azione": "elenco"}))
        self.assertEqual(c.ada._esegui("ada", "vendite_coda", {"azione": "elenco"}), "Strumento non consentito.")

    def test_validazioni_e_limite(self):
        c = self.ctx()
        e = lambda **a: c.ada._esegui("clienti_vendite", "vendite_coda", a)
        self.assertIn("Servono la frase", e(azione="aggiungi", frase="corta", riassunto="x"))
        self.assertIn("Servono la frase", e(azione="aggiungi", frase="una frase abbastanza lunga", riassunto=""))
        for i in range(30):
            e(azione="aggiungi", frase=f"frase numero {i} per il coach", riassunto=f"voce {i}")
        self.assertIn("La coda è piena", e(azione="aggiungi", frase="una frase in più", riassunto="x"))

    def test_l_indirizzo_dell_app_arriva_a_chi_deve_usarlo(self):
        c = self.ctx(FinteRisposte(testo("ok"), testo("ok")))
        c.ada.chiacchiera("ciao")
        self.assertIn("APP VENDITE: indirizzo non impostato", c.ada.llm.chiamate[0]["system"])
        c.db.esegui("INSERT INTO kv (chiave, valore) VALUES ('vendite_url', ?)", (json.dumps("https://claude.ai/artifact/ABC123"),))
        c.ada.chiacchiera("ciao")
        self.assertIn("APP VENDITE: indirizzo https://claude.ai/artifact/ABC123", c.ada.llm.chiamate[1]["system"])

    def test_il_reparto_vendite_conosce_il_manuale_e_gli_altri_no(self):
        c = self.ctx(FinteRisposte(testo("ok"), testo("ok")))
        c.ada._delega("clienti_vendite", "ho chiuso la vendita di Zanetti Emilio")
        sistema = c.ada.llm.chiamate[0]["system"]
        self.assertIn("MANUALE DELL'APP «ANDAMENTO VENDITE»", sistema)
        for parola in ("segna venduto (obbligatori formula e margine)", "COME AGGIORNARE L'APP DALLO SCHERMO", "vendite_coda", "v21", "Coach"):
            self.assertIn(parola, sistema)
        c.ada._delega("quotidiano", "cosa ho domani?")
        self.assertNotIn("MANUALE DELL'APP", c.ada.llm.chiamate[1]["system"])

    def test_il_manuale_non_rompe_la_cache(self):
        from src.ada.llm import MARCATORE
        c = self.ctx(FinteRisposte(testo("ok"), testo("ok")))
        c.ada._delega("clienti_vendite", "uno")
        c.ada._delega("clienti_vendite", "due")
        a, b = (x["system"].partition(MARCATORE)[0] for x in c.ada.llm.chiamate)
        self.assertEqual(a, b)
        self.assertIn("MANUALE DELL'APP", a)
        self.assertNotIn("Oggi è", a)

    def test_ada_sa_come_comportarsi_con_le_novita_di_lavoro(self):
        self.assertIn("avvisa_utente", cervello.CAPACITA)
        self.assertIn("delega a clienti_vendite", cervello.CAPACITA)
        self.assertIn("Non dire mai che l'app è aggiornata se lui non lo conferma", cervello.CAPACITA)

    def test_il_manuale_dice_che_non_si_scrivono_password_e_non_si_inventano_dati(self):
        m = cervello.MANUALE_VENDITE
        self.assertIn("non scrivere mai la password", m)
        self.assertIn("Mai ripetere alla cieca", m)
        self.assertIn("senza nomi di clienti né importi", m)
        self.assertIn("tu non muovi mai denaro", m)


class TestFlussoVendite(Base):
    def test_ho_chiuso_la_vendita_senza_schermo_va_in_coda_e_l_utente_viene_avvisato(self):
        llm = FinteRisposte(
            # Ada: avvisa subito, poi passa il compito al reparto vendite
            usa("avvisa_utente", titolo="Bravo!", testo="Hai venduto! Parlo con il reparto vendite e aggiorno tutto subito."),
            usa("delega", agente="clienti_vendite", compito="L'utente dice: ho chiuso la vendita di Zanetti Emilio (full drive, margine 1800)."),
            # reparto vendite: prova lo schermo, non c'è, mette in coda e prepara il richiamo
            usa("telefono_apri", url="https://claude.ai/artifact/ABC123"),
            usa("vendite_coda", azione="aggiungi", frase="Ho venduto a Zanetti Emilio, full drive, margine 1800 euro",
                riassunto="Vendita a Zanetti Emilio (full drive, 1.800 € di margine)"),
            testo("Schermo non collegato: ho messo la vendita in coda, la trovi in Agenda."),
            # Ada: riferisce
            testo("Bravo! Lo schermo non è collegato, quindi la vendita di Zanetti è in coda in Agenda: incolla la frase nel Coach dell'app."))
        c = self.ctx(llm)
        c.ada.mano = None  # nessun telefono
        risposta = c.ada.chiacchiera("ho chiuso la vendita di Zanetti Emilio, full drive, margine 1800")
        self.assertIn("in coda in Agenda", risposta)
        self.assertEqual([t for t, *_ in self.inviate][:1], ["Bravo!"])  # la prima notifica è quella di Ada, subito
        self.assertEqual(self.inviate[0][1], "Hai venduto! Parlo con il reparto vendite e aggiorno tutto subito.")
        (coda,) = c.db.tutti("SELECT * FROM vendite_coda")
        self.assertEqual((coda["stato"], coda["frase"]), ("da_riportare", "Ho venduto a Zanetti Emilio, full drive, margine 1800 euro"))
        # il reparto vendite ha lavorato con i suoi strumenti, non con quelli di Ada
        nomi_vendite = llm.chiamate[2]["strumenti"]
        self.assertIn("vendite_coda", nomi_vendite)
        self.assertNotIn("delega", nomi_vendite)
        self.assertIn("MANUALE DELL'APP", llm.chiamate[2]["system"])
        # e Ada ha mostrato cosa ha fatto
        azioni = json.loads(c.db.uno("SELECT azioni FROM chat WHERE ruolo='ada'")["azioni"])
        self.assertEqual([a["nome"] for a in azioni], ["avvisa_utente", "delega"])

    def test_un_richiamo_entra_anche_nell_agenda_di_ada(self):
        llm = FinteRisposte(
            usa("agenda_aggiungi", titolo="Richiamare Zanetti Emilio", quando="2026-10-26 09:30", preavviso_min=30),
            testo("Fatto: lunedì alle 9:30, con avviso mezz'ora prima."))
        c = self.ctx(llm)
        self.assertIn("lunedì", c.ada._delega("clienti_vendite", "Richiama Zanetti lunedì alle 9:30"))
        (v,) = c.db.tutti("SELECT titolo, giorno, ora, preavviso, origine FROM eventi")
        self.assertEqual((v["giorno"], v["ora"], v["preavviso"], v["origine"]), ("2026-10-26", "09:30", 30, "clienti_vendite"))


class TestPromptDiPartenza(Base):
    def test_i_prompt_vecchi_si_sostituiscono_se_non_toccati(self):
        for nome, vecchio in (("clienti_vendite", PROMPT_VECCHIO_VENDITE), ("quotidiano", PROMPT_VECCHIO_QUOTIDIANO)):
            import hashlib
            self.assertIn(hashlib.sha1(vecchio.encode()).hexdigest(), SEED_PRECEDENTI[nome])  # il testo del test è proprio quello vecchio
        casa = self.home / "casa"
        (casa / "agenti").mkdir(parents=True)
        (casa / "agenti" / "clienti_vendite.md").write_text(PROMPT_VECCHIO_VENDITE, encoding="utf-8")
        (casa / "agenti" / "quotidiano.md").write_text(PROMPT_VECCHIO_QUOTIDIANO + "\n## Regole imparate\n- Una regola che Ada ha aggiunto.\n", encoding="utf-8")
        sq = Squadra(casa)
        self.assertIn("reparto vendite di Ada", sq.prompt("clienti_vendite"))
        self.assertNotIn("Non hai ancora accesso a un archivio clienti", sq.prompt("clienti_vendite"))
        self.assertIn("Una regola che Ada ha aggiunto.", sq.prompt("quotidiano"))  # modificato da Ada: non si tocca
        self.assertNotIn("agenda_aggiungi", sq.prompt("quotidiano"))

    def test_i_prompt_nuovi_non_si_riscrivono_a_ogni_avvio(self):
        casa = self.home / "casa"
        sq = Squadra(casa)
        sq.scrivi("clienti_vendite", sq.prompt("clienti_vendite") + "\n- regola nuova\n")
        self.assertIn("regola nuova", Squadra(casa).prompt("clienti_vendite"))


class TestServerAgenda(Base):
    def avvia(self, token=""):
        c = self.ctx(token=token)
        srv = crea_server(c, "127.0.0.1", 0)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        self.addCleanup(srv.server_close)
        self.base, self.token = f"http://127.0.0.1:{srv.server_address[1]}", token
        return c

    def chiama(self, path, dati=None):
        h = {"Content-Type": "application/json"}
        if self.token:
            h["Authorization"] = "Bearer " + self.token
        req = urllib.request.Request(self.base + path, data=None if dati is None else json.dumps(dati).encode(), headers=h)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)

    def test_aggiungere_leggere_cambiare(self):
        self.avvia()
        codice, v = self.chiama("/api/agenda", {"titolo": "Chiamare Zanetti", "quando": "2026-10-25 09:30", "tipo": "promemoria", "preavviso_min": 15})
        self.assertEqual((codice, v["giorno"], v["preavviso"], v["origine"]), (200, "2026-10-25", 15, "utente"))
        codice, e = self.chiama("/api/agenda?giorni=7")
        self.assertEqual((e["oggi"], [x["titolo"] for x in e["prossimi"]], e["prossimi"][0]["etichetta"]), ("2026-10-24", ["Chiamare Zanetti"], "domani 09:30"))
        self.assertEqual(self.chiama("/api/agenda/1", {"azione": "sposta", "quando": "2026-10-26 10:00"})[1]["messaggio"], "Aggiornato: Chiamare Zanetti, lunedì 26/10 10:00.")
        self.assertIn("Segnato come fatto", self.chiama("/api/agenda/1", {"azione": "fatto"})[1]["messaggio"])
        self.assertEqual(self.chiama("/api/agenda?giorni=7")[1]["fatti"][0]["etichetta"], "lunedì 26/10 10:00")
        self.assertEqual(self.chiama("/api/agenda/1", {"azione": "elimina"})[0], 200)
        self.assertEqual(self.chiama("/api/agenda/1", {"azione": "fatto"})[0], 404)

    def test_dati_sbagliati_sono_400(self):
        self.avvia()
        self.assertEqual(self.chiama("/api/agenda", {"titolo": "x", "quando": "2026-10-25"})[0], 400)
        self.assertEqual(self.chiama("/api/agenda", {"titolo": "Cosa", "quando": "ieri"})[0], 400)
        self.assertEqual(self.chiama("/api/agenda", {"titolo": "Cosa", "quando": "2026-10-20"})[0], 400)

    def test_stato_con_scaduti_e_coda(self):
        c = self.avvia()
        c.db.esegui("INSERT INTO eventi (ts, titolo, giorno, ora) VALUES (1, 'Vecchio', '2026-10-20', '')")
        c.ada.agenda.aggiungi("Oggi", "2026-10-24")
        c.db.esegui("INSERT INTO vendite_coda (ts, frase, riassunto) VALUES (1, 'una frase lunga', 'riassunto')")
        s = self.chiama("/api/stato")[1]
        self.assertEqual(s["agenda"], {"scaduti": 1, "oggi": 1})
        self.assertEqual(s["vendite"], {"url": False, "in_coda": 1})

    def test_indirizzo_dell_app_vendite(self):
        c = self.avvia()
        self.assertEqual(self.chiama("/api/vendite")[1]["url"], "")
        for brutto in ("http://claude.ai/artifact/abc", "https://evil.example.com/artifact/abc", "https://claude.ai.evil.com/x", "https://claude.ai/ a b", "javascript:alert(1)"):
            self.assertEqual(self.chiama("/api/vendite/impostazioni", {"url": brutto})[0], 400, brutto)
        self.assertEqual(self.chiama("/api/vendite/impostazioni", {"url": "https://claude.ai/artifact/1Gb9qxq1uJmv5yEzsq6q8A"})[1]["url"], "https://claude.ai/artifact/1Gb9qxq1uJmv5yEzsq6q8A")
        self.assertEqual(c.ada.vendite_url(), "https://claude.ai/artifact/1Gb9qxq1uJmv5yEzsq6q8A")
        self.assertTrue(self.chiama("/api/stato")[1]["vendite"]["url"])
        self.assertEqual(self.chiama("/api/vendite/impostazioni", {"url": ""})[1]["url"], "")  # si può togliere
        self.assertEqual(c.ada.vendite_url(), "")

    def test_coda_dall_app(self):
        c = self.avvia()
        c.ada._esegui("clienti_vendite", "vendite_coda", {"azione": "aggiungi", "frase": "Ho chiamato Rossi, richiamalo lunedi", "riassunto": "Chiamata a Rossi"})
        c.ada._esegui("clienti_vendite", "vendite_coda", {"azione": "aggiungi", "frase": "Rossi Mario e perso: comprato altrove", "riassunto": "Rossi perso"})
        j = self.chiama("/api/vendite")[1]
        self.assertEqual([x["riassunto"] for x in j["coda"]], ["Chiamata a Rossi", "Rossi perso"])
        self.assertEqual(self.chiama("/api/vendite/coda/1", {"azione": "fatto"})[0], 200)
        self.assertEqual(self.chiama("/api/vendite/coda/2", {"azione": "elimina"})[0], 200)
        j = self.chiama("/api/vendite")[1]
        self.assertEqual(([x["id"] for x in j["coda"]], [x["riassunto"] for x in j["fatte"]]), ([], ["Chiamata a Rossi"]))
        self.assertEqual(self.chiama("/api/vendite/coda/1", {"azione": "boh"})[0], 400)
        self.assertEqual(self.chiama("/api/vendite/coda/99", {"azione": "fatto"})[0], 404)


if __name__ == "__main__":
    unittest.main()
