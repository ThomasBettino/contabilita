import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from src.ada.appvendite import MESSAGGIO, componi, firma
from src.ada.server import costruisci, crea_server
from tests.test_agenda import ClienteHTTP
from tests.test_ada import FinteRisposte
from tests.test_notifiche import revolut

SEGRETO = "codice-di-prova"
# vettore di riferimento: lo stesso identico valore esce dal codice JavaScript dell'app (HMAC-SHA256, primi 10 caratteri)
VETTORE = ["v1", "preventivo", "Rossi Mario", "Peugeot 208", "2026-10-24", "", "tabc123xyz", "k3f9a2zz"]
FIRMA_VETTORE = "f6ae826059"


def gmail(testo, **altro):
    return {"packageName": "com.google.android.gm", "title": "Thomas Bettino", "content": testo, "when": "2026-10-24 10:00:00", "key": "g1", **altro}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)

    def ctx(self, segreto=SEGRETO, token=""):
        c = costruisci(llm=FinteRisposte(), home=self.home, movimenti=self.home / "n.db", token=token)
        self.addCleanup(c.db.c.close)
        self.t = c.ada.agenda._epoca("2026-10-24", "10:00")  # sabato 24 ottobre 2026, ore 10
        c.ada.agenda.adesso = c.pian.adesso = lambda: self.t
        self.inviate = []
        c.ada.notifica = lambda titolo, testo, id_: self.inviate.append((titolo, testo, id_))
        if segreto:
            c.db.esegui("INSERT INTO kv (chiave, valore) VALUES ('vendite_segreto', ?)", (json.dumps(segreto),))
        return c

    def msg(self, tipo, cliente="", dettaglio="", data="", ora="", chiave="", id_=None, segreto=SEGRETO):
        self.n = getattr(self, "n", 0) + 1
        return componi(segreto, tipo, cliente, dettaglio, data, ora, chiave, id_ or f"i{self.n:04d}")

    def chat(self, c):
        return [m["testo"] for m in c.db.tutti("SELECT testo FROM chat WHERE ruolo='ada' ORDER BY id")]


class TestFirma(unittest.TestCase):
    def test_vettore_di_riferimento(self):
        self.assertEqual(firma(SEGRETO, VETTORE), FIRMA_VETTORE)
        self.assertEqual(componi(SEGRETO, "preventivo", "Rossi Mario", "Peugeot 208", "2026-10-24", "", "tabc123xyz", "k3f9a2zz"),
                         "[ADA] v1|preventivo|Rossi Mario|Peugeot 208|2026-10-24||tabc123xyz|k3f9a2zz|" + FIRMA_VETTORE)

    def test_il_messaggio_si_riconosce_nel_testo_di_una_notifica(self):
        testo = "Re: " + componi(SEGRETO, "vendita", "Zanetti Emilio", "full drive", "2026-10-24", "", "t1", "i1") + " — Messaggio automatico"
        (m,) = MESSAGGIO.finditer(testo)
        self.assertEqual(m.group(1).split("|")[1:3], ["vendita", "Zanetti Emilio"])


class TestLeggi(Base):
    def leggi(self, c, *notifiche):
        return c.ada.app_vendite.leggi(list(notifiche))

    def test_messaggio_valido_in_qualsiasi_campo_si_conta_una_volta(self):
        c = self.ctx()
        m = self.msg("preventivo", "Rossi Mario", "Peugeot 208", "2026-10-24", chiave="tabc")
        validi, rotti = self.leggi(c, gmail(m, bigText=m, summary="altro"))
        self.assertEqual((len(validi), rotti), (1, 0))
        self.assertEqual((validi[0]["tipo"], validi[0]["cliente"]), ("preventivo", "Rossi Mario"))
        self.assertEqual(self.leggi(c, gmail(m)), ([], 0))  # la notifica resta nella tendina: la seconda volta non conta

    def test_firma_sbagliata_o_codice_diverso_si_scarta(self):
        c = self.ctx()
        falso = self.msg("vendita", "Truffa", segreto="altro-codice")
        rotto = self.msg("vendita", "Rossi").replace("Rossi", "Rossa")  # contenuto cambiato dopo la firma
        validi, rotti = self.leggi(c, gmail(falso), gmail(rotto))
        self.assertEqual((validi, rotti), ([], 2))
        self.assertEqual(c.db.tutti("SELECT * FROM vendite_registro"), [])

    def test_messaggio_tagliato_si_conta_ma_non_si_ripete(self):
        c = self.ctx()
        tagliato = self.msg("preventivo", "Rossi Mario", "Peugeot 208", "2026-10-24")[:-14] + "…"
        self.assertEqual(self.leggi(c, gmail(tagliato))[1], 1)
        self.assertEqual(self.leggi(c, gmail(tagliato))[1], 0)

    def test_tipi_date_e_ore_strani_si_scartano(self):
        c = self.ctx()
        for brutto in (self.msg("regalo", "X"), self.msg("vendita", "X", data="ieri"), self.msg("vendita", "X", ora="9"),
                       componi(SEGRETO, "vendita", "X", "", "", "", "", "")):
            validi, _ = self.leggi(c, gmail(brutto))
            self.assertEqual(validi, [], brutto)

    def test_notifiche_normali_non_danno_fastidio(self):
        c = self.ctx()
        self.assertEqual(self.leggi(c, gmail("Offerta speciale"), revolut("Bar Roma", "Hai speso 5,80 €"), {"packageName": "x", "title": None, "content": 5}), ([], 0))

    def test_senza_codice_non_si_fa_niente(self):
        c = self.ctx(segreto="")
        self.assertEqual(c.ada.app_vendite.elabora([gmail(self.msg("vendita", "Rossi"))]), "")
        self.assertEqual(c.db.tutti("SELECT * FROM vendite_registro"), [])
        self.assertEqual(c.ada.app_vendite.stato(), {"attivo": False, "ultimo": None, "ricevuti": 0, "non_leggibili": 0})


class TestEventi(Base):
    def test_un_preventivo_va_nel_diario_e_l_utente_viene_avvisato(self):
        c = self.ctx()
        esito = c.ada.app_vendite.elabora([gmail(self.msg("preventivo", "Rossi Mario", "Peugeot 208", "2026-10-24", chiave="t1"))])
        self.assertEqual(esito, "1 novità dall'app")
        (v,) = c.db.tutti("SELECT tipo, cliente, dettaglio, giorno, in_app, origine FROM vendite_registro")
        self.assertEqual((v["tipo"], v["cliente"], v["dettaglio"], v["giorno"], v["in_app"], v["origine"]), ("preventivo", "Rossi Mario", "Peugeot 208", "2026-10-24", 1, "app"))
        self.assertEqual(self.inviate, [("Ada ha visto una novità", "Hei Thomas, ho visto che hai aggiunto un preventivo: l'ho segnato.", "ada-app-vendite")])
        self.assertEqual(self.chat(c), ["Ho visto che nell'app vendite hai aggiunto:\n• preventivo di Rossi Mario (Peugeot 208): segnato nel diario"])
        self.assertEqual(c.ada.diario.conteggi(), {"preventivo": 1})  # e finisce nel riepilogo delle 18:55
        self.assertIn("• Preventivi fatti: 1", c.ada.diario.riepilogo_sera()[0])

    def test_una_vendita_si_festeggia(self):
        c = self.ctx()
        c.ada.app_vendite.elabora([gmail(self.msg("vendita", "Zanetti Emilio", "full drive", "2026-10-24", chiave="t2"))])
        self.assertEqual(self.inviate[0][1], "Hei Thomas, bravo! Ho visto che hai aggiunto una vendita: l'ho segnata.")

    def test_piu_novita_insieme_fanno_una_sola_notifica(self):
        c = self.ctx()
        c.ada.app_vendite.elabora([gmail(self.msg("preventivo", "Rossi", "208", "2026-10-24", chiave="a")),
                                   gmail(self.msg("appuntamento", "Bianchi", "Consegna", "2026-10-25", "15:00", chiave="b")),
                                   gmail(self.msg("preventivo", "Verdi", "C3", "2026-10-24", chiave="c"))])
        self.assertEqual(len(self.inviate), 1)
        self.assertEqual(self.inviate[0][1], "Hei Thomas, ho visto che hai aggiunto 2 preventivi e un appuntamento: li ho segnati.")
        self.assertEqual(len(self.chat(c)), 1)
        self.assertEqual(self.chat(c)[0].count("•"), 3)

    def test_un_appuntamento_entra_nell_agenda_con_avviso_e_si_sposta_senza_doppioni(self):
        c = self.ctx()
        c.ada.app_vendite.elabora([gmail(self.msg("appuntamento", "Bianchi", "Consegna", "2026-10-25", "15:00", chiave="tapp1"))])
        (v,) = c.db.tutti("SELECT titolo, giorno, ora, tipo, preavviso, origine FROM eventi")
        self.assertEqual((v["titolo"], v["giorno"], v["ora"], v["tipo"], v["preavviso"], v["origine"]), ("Consegna: Bianchi", "2026-10-25", "15:00", "evento", 30, "app"))
        self.assertIn("messo in agenda", self.chat(c)[0])
        self.inviate.clear()
        c.ada.app_vendite.elabora([gmail(self.msg("appuntamento", "Bianchi", "Consegna", "2026-10-27", "10:00", chiave="tapp1"))])  # l'utente lo sposta nell'app
        (v,) = c.db.tutti("SELECT giorno, ora FROM eventi WHERE stato='attivo'")
        self.assertEqual((v["giorno"], v["ora"]), ("2026-10-27", "10:00"))
        self.assertIn("spostato in agenda", self.chat(c)[1])

    def test_un_richiamo_diventa_un_promemoria_di_tutto_il_giorno(self):
        c = self.ctx()
        c.ada.app_vendite.elabora([gmail(self.msg("richiamo", "Zanetti Emilio", "", "2026-10-26", chiave="rz"))])
        (v,) = c.db.tutti("SELECT titolo, giorno, ora, tipo, preavviso FROM eventi")
        self.assertEqual((v["titolo"], v["giorno"], v["ora"], v["tipo"], v["preavviso"]), ("Richiamare Zanetti Emilio", "2026-10-26", "", "promemoria", 0))
        self.assertEqual(self.inviate[0][1], "Hei Thomas, ho visto che hai aggiunto un richiamo: l'ho segnato.")

    def test_una_data_passata_non_crea_ricordi_inutili(self):
        c = self.ctx()
        self.assertEqual(c.ada.app_vendite.elabora([gmail(self.msg("richiamo", "Rossi", "", "2026-10-01", chiave="x")),
                                                    gmail(self.msg("appuntamento", "Rossi", "Visita", "2026-10-20", "10:00", chiave="y"))]), "")
        self.assertEqual((c.db.tutti("SELECT * FROM eventi"), self.inviate), ([], []))

    def test_se_ada_lo_sapeva_gia_non_lo_dice_due_volte(self):
        c = self.ctx()
        c.ada.diario.aggiungi("vendita", "Zanetti Emilio", "full drive", in_app=False)  # l'aveva raccontata l'utente ad Ada
        esito = c.ada.app_vendite.elabora([gmail(self.msg("vendita", "Zanetti Emilio", "full drive", "2026-10-24", chiave="t"))])
        self.assertEqual((esito, self.inviate, self.chat(c)), ("", [], []))
        self.assertEqual(c.db.uno("SELECT in_app FROM vendite_registro")["in_app"], 1)  # ma ora risulta anche nell'app
        self.assertEqual(c.ada.diario.conteggi(), {"vendita": 1})  # e non è contata due volte

    def test_chiamate_doppie_dopo_ada_no_ma_una_seconda_chiamata_vera_si(self):
        c = self.ctx()
        c.ada.diario.aggiungi("chiamata", "Rossi", "vuole pensarci")  # appena scritta dal reparto vendite
        c.ada.app_vendite.elabora([gmail(self.msg("chiamata", "Rossi", "Ci pensa", "2026-10-24", chiave="t"))])
        self.assertEqual(c.ada.diario.conteggi(), {"chiamata": 1})  # è l'eco di quella
        self.t += 3600  # un'ora dopo: un'altra chiamata, fatta dall'app
        c.ada.app_vendite.elabora([gmail(self.msg("chiamata", "Rossi", "Non risponde", "2026-10-24", chiave="t"))])
        self.assertEqual(c.ada.diario.conteggi(), {"chiamata": 2})

    def test_la_prova_del_collegamento(self):
        c = self.ctx()
        esito = c.ada.app_vendite.elabora([gmail(self.msg("ping", "prova"))])
        self.assertEqual(esito, "collegamento provato")
        self.assertEqual(self.inviate, [("App vendite", "Hei Thomas, il collegamento con l'app vendite funziona!", "ada-app-vendite")])
        self.assertIn("funziona", self.chat(c)[0])
        self.assertEqual(c.ada.app_vendite.stato()["ricevuti"], 1)

    def test_cambiando_il_codice_i_vecchi_messaggi_non_valgono(self):
        c = self.ctx()
        vecchio = self.msg("vendita", "Rossi", "", "2026-10-24")
        c.db.esegui("UPDATE kv SET valore=? WHERE chiave='vendite_segreto'", (json.dumps("nuovo-codice"),))
        self.assertEqual(c.ada.app_vendite.elabora([gmail(vecchio)]), "1 messaggi non leggibili")
        self.assertEqual(c.db.tutti("SELECT * FROM vendite_registro"), [])
        self.assertEqual(c.ada.app_vendite.stato()["non_leggibili"], 1)


class TestRoutine(Base):
    def esegui(self, c):
        return c.pian.esegui(c.db.uno("SELECT id FROM routine WHERE nome='notifiche'")["id"])

    def test_revolut_e_app_vendite_nella_stessa_lettura(self):
        c = self.ctx()
        lista = [revolut("Bar Roma", "Hai speso 5,80 €"), gmail(self.msg("preventivo", "Rossi", "208", "2026-10-24", chiave="a"))]
        letture = []
        c.ada.lettore_notifiche = lambda: letture.append(1) or lista
        esito = self.esegui(c)
        self.assertEqual(esito, "1 nuovi movimenti letti. 1 novità dall'app.")
        self.assertEqual((len(letture), len(c.ada.soldi.elenco()), c.ada.diario.conteggi()), (1, 1, {"preventivo": 1}))  # una sola lettura per tutti e due
        self.assertEqual(self.esegui(c), "Nessuna novità.")  # le notifiche restano nella tendina ma non si contano due volte
        self.assertEqual(c.ada.diario.conteggi(), {"preventivo": 1})

    def test_un_guasto_dell_app_vendite_non_ferma_revolut(self):
        c = self.ctx()
        c.ada.lettore_notifiche = lambda: [revolut("Bar Roma", "Hai speso 5,80 €")]

        def rotto(_):
            raise RuntimeError("boom")
        c.ada.app_vendite.elabora = rotto
        self.assertEqual(self.esegui(c), "1 nuovi movimenti letti.")
        self.assertIn("errore app vendite", [a["azione"] for a in c.db.tutti("SELECT azione FROM attivita")])

    def test_senza_codice_tutto_come_prima(self):
        c = self.ctx(segreto="")
        c.ada.lettore_notifiche = lambda: [gmail(self.msg("vendita", "Rossi"))]
        self.assertEqual(self.esegui(c), "Nessuna novità.")
        self.assertEqual(c.db.tutti("SELECT * FROM vendite_registro"), [])


class TestServerMessaggero(ClienteHTTP):
    def test_il_codice_si_vede_solo_con_il_token_ed_e_stabile(self):
        self.avvia(token="")
        codice, r = self.chiama("/api/vendite/messaggero", {})
        self.assertEqual(codice, 403)
        self.assertIn("ADA_TOKEN", r["errore"])
        c = self.avvia(token="abc")
        self.assertEqual(self.chiama("/api/vendite")[1]["messaggero"], {"attivo": False, "ultimo": None, "ricevuti": 0, "non_leggibili": 0})
        primo = self.chiama("/api/vendite/messaggero", {})[1]["codice"]
        self.assertGreaterEqual(len(primo), 12)
        self.assertEqual(self.chiama("/api/vendite/messaggero", {})[1]["codice"], primo)  # stesso codice: l'app lo ha già
        self.assertNotIn(primo, json.dumps(self.chiama("/api/vendite")[1]))  # lo stato non lo rivela
        self.assertNotIn(primo, json.dumps(self.chiama("/api/stato")[1]))
        nuovo = self.chiama("/api/vendite/messaggero", {"azione": "rigenera"})[1]["codice"]
        self.assertNotEqual(nuovo, primo)
        self.assertTrue(self.chiama("/api/vendite")[1]["messaggero"]["attivo"])
        self.assertEqual(c.ada.app_vendite.segreto(), nuovo)

    def test_lo_stato_conta_i_messaggi(self):
        c = self.avvia(token="abc")
        codice = c.ada.app_vendite.crea_segreto()
        c.ada.app_vendite.elabora([gmail(componi(codice, "preventivo", "Rossi", "208", "2026-10-24", "", "a", "i1")), gmail("[ADA] v1|rotto")])
        s = self.chiama("/api/vendite")[1]["messaggero"]
        self.assertEqual((s["attivo"], s["ricevuti"], s["non_leggibili"]), (True, 1, 1))
        self.assertIsNotNone(s["ultimo"])
