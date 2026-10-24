import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path

from src.ada.estratto import data_ora, leggi_estratto, numero
from src.ada.server import costruisci, crea_server
from src.ada.soldi import Soldi, origine
from src.revolut.ingest import PACCHETTO, leggi_e_salva
from src.revolut.store import apri
from tests.test_ada import FinteRisposte

REVOLUT_EN = """Type,Product,Started Date,Completed Date,Description,Amount,Fee,Currency,State,Balance
CARD_PAYMENT,Current,2026-10-20 09:10:11,2026-10-21 08:00:00,Esselunga,-42.30,0.00,EUR,COMPLETED,957.70
TRANSFER,Current,2026-10-22 10:00:00,2026-10-22 10:00:05,Autoghinzani Srl,1250.00,0.00,EUR,COMPLETED,2207.70
CARD_PAYMENT,Current,2026-10-22 12:00:00,,Bar Roma,-5.80,0.00,EUR,PENDING,
CARD_PAYMENT,Current,2026-10-22 12:30:00,2026-10-22 12:31:00,Uber,-12.00,0.50,EUR,COMPLETED,
EXCHANGE,Current,2026-10-22 13:00:00,2026-10-22 13:00:01,Exchanged to USD,-100.00,0.00,EUR,COMPLETED,
CARD_PAYMENT,Current,2026-10-22 14:00:00,2026-10-22 14:00:01,NYC Deli,-8.00,0.00,USD,COMPLETED,
CARD_PAYMENT,Current,2026-10-23 14:00:00,2026-10-23 14:00:01,Rimborsato,-9.00,0.00,EUR,REVERTED,
"""
BANCA_IT = """Conto 123456;;;;
Data contabile;Data valuta;Descrizione;Dare;Avere
23/10/2026;23/10/2026;PAGAMENTO POS ESSELUNGA;42,30;
24/10/2026;24/10/2026;BONIFICO AUTOGHINZANI SRL;;1.250,00
"""


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.mov = self.home / "movimenti.db"

    def soldi(self):
        return Soldi(self.mov)

    def inserisci(self, chiave, quando, importo, controparte):
        db = apri(str(self.mov))
        db.execute("INSERT INTO movimenti VALUES (?,?,?,?,?)", (chiave, quando, importo, controparte, ""))
        db.commit()
        db.close()


class TestNumeriEDate(unittest.TestCase):
    def test_numeri(self):
        for scritto, atteso in (("1.234,56", 1234.56), ("1,234.56", 1234.56), ("-12.5", -12.5), ("(12,50)", -12.5),
                                ("− 5,80 €", -5.8), ("1.234", 1234.0), ("12,5", 12.5), ("EUR 7", 7.0), ("abc", None), ("", None), (None, None)):
            self.assertEqual(numero(scritto), atteso, scritto)

    def test_date(self):
        self.assertEqual(data_ora("2026-10-21 08:00:00"), ("2026-10-21", "08:00:00"))
        self.assertEqual(data_ora("23/10/2026"), ("2026-10-23", "12:00:00"))
        self.assertEqual(data_ora("23/10/26"), ("2026-10-23", "12:00:00"))
        self.assertIsNone(data_ora("ieri"))


class TestLeggiEstratto(unittest.TestCase):
    def test_revolut_inglese(self):
        r = leggi_estratto(REVOLUT_EN)
        self.assertEqual([(x["data"], x["importo"], x["descrizione"]) for x in r["righe"]],
                         [("2026-10-21", -42.3, "Esselunga"), ("2026-10-22", 1250.0, "Autoghinzani Srl"), ("2026-10-22", -12.5, "Uber")])
        self.assertEqual(r["ignorate"], {"annullati o in attesa": 2, "cambi di valuta tra i tuoi conti": 1, "in altra valuta": 1})

    def test_revolut_italiano(self):
        testo = ("Tipo,Prodotto,Data di inizio,Data di completamento,Descrizione,Importo,Costo,Valuta,State,Saldo\n"
                 "Pagamento con carta,Attuale,2026-10-20 09:10:11,2026-10-21 08:00:00,Bar Roma,-5.80,0.00,EUR,COMPLETATO,10\n")
        self.assertEqual(leggi_estratto(testo)["righe"][0]["importo"], -5.8)

    def test_banca_italiana_con_dare_e_avere_e_riga_di_titolo(self):
        r = leggi_estratto("﻿" + BANCA_IT)
        self.assertEqual([(x["data"], x["importo"]) for x in r["righe"]], [("2026-10-23", -42.3), ("2026-10-24", 1250.0)])

    def test_importo_unico_con_virgola_decimale(self):
        r = leggi_estratto("Data;Descrizione;Importo\n01/10/2026;Affitto;-1.234,56\n02/10/2026;Stipendio;2.000,00\n")
        self.assertEqual([x["importo"] for x in r["righe"]], [-1234.56, 2000.0])

    def test_file_non_leggibili_dicono_perche(self):
        for testo, parte in (("", "vuoto"), ("%PDF-1.4 ...", "PDF"), ("ciao\nmondo\n", "Non riconosco"), ("Nome;Cognome\na;b\n", "Non riconosco")):
            with self.assertRaises(ValueError) as e:
                leggi_estratto(testo)
            self.assertIn(parte, str(e.exception))

    def test_righe_senza_data_o_importo_si_contano_e_non_si_perdono_in_silenzio(self):
        r = leggi_estratto("Data;Descrizione;Importo\nieri;Bar;-5\n01/10/2026;Bar;boh\n01/10/2026;Bar;-5\n;;\n")
        self.assertEqual(len(r["righe"]), 1)
        self.assertEqual(r["ignorate"], {"senza data o importo": 2})

    def test_troppe_righe(self):
        testo = "Data;Descrizione;Importo\n" + "01/10/2026;Bar;-1\n" * 5001
        with self.assertRaises(ValueError):
            leggi_estratto(testo)


class TestAggiungiERimuovi(Base):
    def test_aggiungi_uscita_ed_entrata(self):
        s = self.soldi()
        oggi = date.today().isoformat()
        a = s.aggiungi(oggi, "5,80", "  Bar   Roma ", "uscita")
        b = s.aggiungi("2026-10-01", 1250, "Cliente Rossi", "entrata")
        self.assertEqual((a["importo"], a["controparte"]), (-5.8, "Bar Roma"))
        self.assertEqual(b["importo"], 1250.0)
        self.assertTrue(a["chiave"].startswith("manuale|"))
        el = s.elenco()
        self.assertEqual({x["controparte"]: x["origine"] for x in el}, {"Bar Roma": "manuale", "Cliente Rossi": "manuale"})
        self.assertTrue(b["quando"].endswith("12:00:00"))  # data passata: mezzogiorno
        self.assertEqual(s.riepilogo("sempre")["entrate"], 1250.0)

    def test_dati_sbagliati_si_rifiutano(self):
        s = self.soldi()
        oggi = date.today().isoformat()
        casi = [((oggi, "5", "Bar", "boh"), "uscita o un'entrata"), ((oggi, "0", "Bar", "uscita"), "importo"),
                ((oggi, "-5", "Bar", "uscita"), "importo"), ((oggi, "abc", "Bar", "uscita"), "importo"),
                ((oggi, "2000000", "Bar", "uscita"), "importo"), ((oggi, "5", "   ", "uscita"), "a chi o per cosa"),
                ((oggi, "5", "x" * 81, "uscita"), "a chi o per cosa"), (("31/12/2026", "5", "Bar", "uscita"), "data"),
                (((date.today() + timedelta(days=5)).isoformat(), "5", "Bar", "uscita"), "futuro"), (("1999-01-01", "5", "Bar", "uscita"), "futuro")]
        for args, parte in casi:
            with self.assertRaises(ValueError) as e:
                s.aggiungi(*args)
            self.assertIn(parte, str(e.exception), args)
        self.assertEqual(s.elenco(), [])

    def test_rimuovere_un_movimento(self):
        s = self.soldi()
        a = s.aggiungi(date.today().isoformat(), "5", "Bar", "uscita")
        self.assertTrue(s.rimuovi(a["chiave"]))
        self.assertEqual(s.elenco(), [])
        self.assertFalse(s.rimuovi(a["chiave"]))
        self.assertFalse(Soldi(self.home / "manca.db").rimuovi("x"))

    def test_un_movimento_letto_da_notifica_tolto_non_ritorna(self):
        notifica = {"packageName": PACCHETTO, "title": "Bar Roma", "content": "Hai speso 5,80 €", "when": "2026-10-23 10:00:00", "key": "k1"}
        db = apri(str(self.mov))
        self.addCleanup(db.close)
        leggi_e_salva(db, lambda: [notifica])
        s = self.soldi()
        (m,) = s.elenco()
        self.assertEqual(m["origine"], "notifica")
        s.rimuovi(m["chiave"])
        self.assertEqual(leggi_e_salva(db, lambda: [notifica])["nuovi"], 0)  # la notifica è ancora nella tendina
        self.assertEqual(s.elenco(), [])

    def test_elenco_per_mese(self):
        s = self.soldi()
        s.aggiungi("2026-09-30", "1", "Settembre", "uscita")
        s.aggiungi("2026-10-01", "2", "Ottobre", "uscita")
        self.assertEqual([x["controparte"] for x in s.elenco("2026-10")], ["Ottobre"])
        self.assertEqual(len(s.elenco()), 2)
        with self.assertRaises(ValueError):
            s.elenco("ottobre")
        self.assertEqual(Soldi(self.home / "manca.db").elenco("2026-10"), [])

    def test_origine(self):
        self.assertEqual([origine(c) for c in ("manuale|1", "estratto|2026-10-01|1.00|x|1", "k|when|titolo|testo")],
                         ["manuale", "estratto", "notifica"])


class TestImportaEstratto(Base):
    def test_abbina_aggiunge_e_segnala_da_controllare(self):
        self.inserisci("k1|a", "2026-10-21 08:05:00", -42.30, "Esselunga")  # già letto da notifica
        self.inserisci("k2|b", "2026-10-22 09:00:00", -3.00, "Bar")        # non compare nell'estratto
        self.inserisci("k3|c", "2026-09-01 09:00:00", -9.00, "Vecchio")    # fuori dal periodo: non si tocca
        r = self.soldi().importa_estratto(REVOLUT_EN)
        self.assertEqual((r["righe"], r["presenti"], r["nuovi"]), (3, 1, 2))
        self.assertEqual(r["periodo"], ["2026-10-21", "2026-10-22"])
        self.assertEqual([(d["controparte"], d["origine"]) for d in r["da_controllare"]], [("Bar", "notifica")])
        self.assertEqual(r["totale_da_controllare"], 1)
        self.assertEqual(sorted(x["controparte"] for x in self.soldi().elenco()), ["Autoghinzani Srl", "Bar", "Esselunga", "Uber", "Vecchio"])
        self.assertEqual(len(r["chiavi_nuove"]), 2)

    def test_caricare_due_volte_lo_stesso_file_non_duplica(self):
        s = self.soldi()
        s.importa_estratto(REVOLUT_EN)
        r = s.importa_estratto(REVOLUT_EN)
        self.assertEqual((r["nuovi"], r["presenti"], r["totale_da_controllare"]), (0, 3, 0))
        self.assertEqual(len(s.elenco()), 3)

    def test_due_righe_uguali_lo_stesso_giorno_restano_due_movimenti(self):
        testo = "Data;Descrizione;Importo\n01/10/2026;Caffè;-1,20\n01/10/2026;Caffè;-1,20\n"
        s = self.soldi()
        self.assertEqual(s.importa_estratto(testo)["nuovi"], 2)
        r = s.importa_estratto(testo)
        self.assertEqual((r["nuovi"], r["presenti"]), (0, 2))
        self.assertEqual(len(s.elenco()), 2)

    def test_finestra_di_due_giorni_e_stesso_importo(self):
        self.inserisci("k1", "2026-10-18 10:00:00", -42.30, "Esselunga")  # 3 giorni prima: è un altro pagamento
        self.inserisci("k2", "2026-10-23 10:00:00", -12.50, "Uber")      # 1 giorno dopo: è lo stesso
        r = self.soldi().importa_estratto(REVOLUT_EN)
        self.assertEqual(r["presenti"], 1)
        self.assertEqual(r["nuovi"], 2)

    def test_completa_il_nome_se_il_movimento_non_ce_l_aveva(self):
        self.inserisci("k1", "2026-10-21 08:05:00", -42.30, "")
        self.soldi().importa_estratto(REVOLUT_EN)
        self.assertEqual([x["controparte"] for x in self.soldi().elenco() if x["chiave"] == "k1"], ["Esselunga"])

    def test_estratto_senza_movimenti_utili_dice_cosa_ha_scartato(self):
        with self.assertRaises(ValueError) as e:
            self.soldi().importa_estratto("Data;Descrizione;Importo;Valuta\n01/10/2026;Deli;-5;USD\n")
        self.assertIn("1 in altra valuta", str(e.exception))

    def test_banca_italiana(self):
        r = self.soldi().importa_estratto(BANCA_IT)
        self.assertEqual((r["nuovi"], r["periodo"]), (2, ["2026-10-23", "2026-10-24"]))
        self.assertEqual(self.soldi().riepilogo("sempre")["saldo"], round(1250 - 42.30, 2))


class TestServer(Base):
    def avvia(self, token="abc"):
        c = costruisci(llm=FinteRisposte(), home=self.home, movimenti=self.mov, token=token)
        self.addCleanup(c.db.c.close)
        srv = crea_server(c, "127.0.0.1", 0)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        self.addCleanup(srv.server_close)
        self.base = f"http://127.0.0.1:{srv.server_address[1]}"
        self.token = token
        return c

    def chiama(self, path, dati=None, auth=True):
        h = {"Content-Type": "application/json"}
        if auth and self.token:
            h["Authorization"] = "Bearer " + self.token
        req = urllib.request.Request(self.base + path, data=None if dati is None else json.dumps(dati).encode(), headers=h)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)

    def test_senza_token_non_si_modifica_nulla(self):
        self.avvia(token="")
        oggi = date.today().isoformat()
        self.assertEqual(self.chiama("/api/movimenti", {"data": oggi, "importo": 5, "controparte": "Bar", "tipo": "uscita"})[0], 403)
        self.assertEqual(self.chiama("/api/movimenti/rimuovi", {"chiave": "x"})[0], 403)
        self.assertEqual(self.chiama("/api/estratto", {"testo": BANCA_IT})[0], 403)
        self.assertEqual(self.chiama("/api/movimenti")[0], 200)  # leggere si può

    def test_aggiungere_elencare_rimuovere(self):
        c = self.avvia()
        oggi = date.today().isoformat()
        codice, m = self.chiama("/api/movimenti", {"data": oggi, "importo": "5,80", "controparte": "Bar Roma", "tipo": "uscita"})
        self.assertEqual((codice, m["importo"]), (200, -5.8))
        codice, el = self.chiama("/api/movimenti?mese=" + oggi[:7])
        self.assertEqual([x["controparte"] for x in el["movimenti"]], ["Bar Roma"])
        self.assertEqual(self.chiama("/api/movimenti", {"data": oggi, "importo": "x", "controparte": "Bar", "tipo": "uscita"})[0], 400)
        self.assertEqual(self.chiama("/api/movimenti?mese=boh")[0], 400)
        self.assertEqual(self.chiama("/api/movimenti/rimuovi", {"chiave": m["chiave"]}), (200, {"ok": True}))
        self.assertEqual(self.chiama("/api/movimenti/rimuovi", {"chiave": m["chiave"]})[0], 404)
        azioni = [a["azione"] for a in c.db.tutti("SELECT azione FROM attivita")]
        self.assertIn("movimento aggiunto", azioni)
        self.assertIn("movimento rimosso", azioni)

    def test_estratto_e_senza_avvisi_sulle_fatture(self):
        c = self.avvia()
        codice, r = self.chiama("/api/estratto", {"nome": "ottobre.csv", "testo": REVOLUT_EN})
        self.assertEqual((codice, r["nuovi"], r["presenti"]), (200, 3, 0))
        self.assertNotIn("chiavi_nuove", r)
        visti = {x["chiave"] for x in c.db.tutti("SELECT chiave FROM movimenti_visti")}
        self.assertEqual(visti, {m["chiave"] for m in self.soldi().elenco()})  # storici: niente abbinamenti né notifiche
        self.assertEqual(self.chiama("/api/estratto", {"testo": "ciao"})[0], 400)

    def test_un_file_troppo_grande_si_rifiuta(self):
        self.avvia()
        codice, r = self.chiama("/api/estratto", {"testo": "x" * 3_100_000})
        self.assertEqual(codice, 400)
        self.assertIn("troppo grande", r["errore"])
        self.assertEqual(self.chiama("/api/movimenti", {"data": "x" * 70000})[0], 400)  # le altre richieste restano piccole


if __name__ == "__main__":
    unittest.main()
