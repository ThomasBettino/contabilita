import json
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.ada.server import costruisci
from src.revolut.ingest import PACCHETTO, ErroreLettura, leggi_e_salva, leggi_notifiche_termux
from src.revolut.store import apri
from tests.test_ada import FinteRisposte, testo, usa


def revolut(titolo, contenuto, quando="2026-10-24 08:41:00", key="k1"):
    return {"packageName": PACCHETTO, "title": titolo, "content": contenuto, "when": quando, "key": key}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.db_mov = self.home / "movimenti.db"

    def ctx(self, notifiche=None, llm=None):
        c = costruisci(llm=llm or FinteRisposte(), home=self.home, movimenti=self.db_mov, token="")
        self.addCleanup(c.db.c.close)
        c.ada.lettore_notifiche = (lambda: notifiche) if notifiche is not None else None
        return c

    def lettura(self):
        k = sqlite3.connect(self.db_mov)
        r = k.execute("SELECT quando, totale, revolut, nuovi, non_riconosciuti, errore FROM letture").fetchall()
        k.close()
        return r


class TestLetturaTermux(unittest.TestCase):
    def run_con(self, **k):
        return mock.patch("src.revolut.ingest.subprocess.run", **k)

    def test_ok(self):
        with self.run_con(return_value=mock.Mock(stdout='[{"title": "x"}]')):
            self.assertEqual(leggi_notifiche_termux(), [{"title": "x"}])
        with self.run_con(return_value=mock.Mock(stdout="")):
            self.assertEqual(leggi_notifiche_termux(), [])

    def test_ogni_errore_ha_un_messaggio_chiaro(self):
        casi = [(FileNotFoundError(), "manca Termux:API"),
                (subprocess.TimeoutExpired("termux-notification-list", 20), "non risponde"),
                (subprocess.CalledProcessError(1, "x", stderr="boom"), "boom")]
        for errore, atteso in casi:
            with self.run_con(side_effect=errore), self.assertRaises(ErroreLettura) as e:
                leggi_notifiche_termux()
            self.assertIn(atteso, str(e.exception))
        for uscita in ("non è json", '{"a": 1}'):
            with self.run_con(return_value=mock.Mock(stdout=uscita)), self.assertRaises(ErroreLettura):
                leggi_notifiche_termux()


class TestLeggiESalva(Base):
    def test_salva_movimenti_e_com_e_andata(self):
        db = apri(str(self.db_mov))
        self.addCleanup(db.close)
        esito = leggi_e_salva(db, lambda: [revolut("Bar Roma", "Hai speso 5,80 €\nSaldo di EUR: 59,90 €"),
                                           revolut("Offerta", "Scopri la nuova carta", key="k2"),
                                           {"packageName": "com.altra.app", "title": "x", "content": "y"}], adesso=lambda: 1000)
        self.assertEqual(esito, {"nuovi": 1, "non_riconosciuti": 1, "ignorati": 1, "revolut": 2})
        self.assertEqual(self.lettura(), [(1000, 3, 2, 1, 1, "")])
        leggi_e_salva(db, lambda: [], adesso=lambda: 2000)  # una riga sola, sempre l'ultima
        self.assertEqual(self.lettura(), [(2000, 0, 0, 0, 0, "")])

    def test_un_errore_viene_annotato_non_perso(self):
        db = apri(str(self.db_mov))
        self.addCleanup(db.close)

        def rotto():
            raise ErroreLettura("Termux:API non risponde")
        self.assertEqual(leggi_e_salva(db, rotto, adesso=lambda: 3000), {"errore": "Termux:API non risponde"})
        self.assertEqual(self.lettura(), [(3000, 0, 0, 0, 0, "Termux:API non risponde")])


class TestRoutineNotifiche(Base):
    def esegui(self, c):
        return c.pian.esegui(c.db.uno("SELECT id FROM routine WHERE nome='notifiche'")["id"])

    def test_gira_ogni_due_minuti_da_sola(self):
        c = self.ctx([])
        r = c.db.uno("SELECT ogni_min, attiva, tipo FROM routine WHERE nome='notifiche'")
        self.assertEqual((r["ogni_min"], r["attiva"], r["tipo"]), (2, 1, "codice"))

    def test_legge_i_movimenti_senza_schermo_e_senza_chiedere(self):
        c = self.ctx([revolut("Bar Roma", "Hai speso 5,80 €\nSaldo di EUR: 59,90 €")])
        self.assertEqual(self.esegui(c), "1 nuovi movimenti letti.")
        self.assertEqual(c.soldi.riepilogo("sempre")["movimenti"], 1)
        self.assertEqual(self.esegui(c), "Nessuna novità.")  # la stessa notifica non si conta due volte
        self.assertEqual(c.ada.llm.chiamate, [])  # niente cervello: non costa token

    def test_un_bonifico_in_arrivo_fa_partire_subito_il_controllo_delle_fatture(self):
        c = self.ctx([revolut("Revolut", "Hai ricevuto 1.250,00 € da Autoghinzani Srl")])
        c.db.esegui("UPDATE routine SET prossima=9999999999 WHERE nome='fatture'")
        self.esegui(c)
        self.assertIsNotNone(c.db.uno("SELECT ultima FROM routine WHERE nome='fatture'")["ultima"])  # eseguita subito
        c.db.esegui("UPDATE routine SET ultima=NULL, attiva=0 WHERE nome='fatture'")
        c.ada.lettore_notifiche = lambda: [revolut("Revolut", "Hai ricevuto 80,00 € da Mario", key="k9")]
        self.esegui(c)
        self.assertIsNone(c.db.uno("SELECT ultima FROM routine WHERE nome='fatture'")["ultima"])  # spenta: non la riaccende

    def test_senza_termux_api_lo_dice_e_non_crea_file(self):
        c = self.ctx(None)
        self.assertIn("Termux:API non trovato", self.esegui(c))
        self.assertFalse(self.db_mov.exists())

    def test_un_errore_resta_visibile_ma_non_riempie_il_registro(self):
        def rotto():
            raise ErroreLettura("Termux:API non risponde")
        c = self.ctx(None)
        c.ada.lettore_notifiche = rotto
        for _ in range(5):
            self.assertIn("lettura notifiche non riuscita", self.esegui(c))
        self.assertEqual(c.db.uno("SELECT COUNT(*) AS n FROM attivita WHERE azione='notifiche'")["n"], 1)
        c.ada.lettore_notifiche = lambda: []
        self.esegui(c)
        self.assertEqual(c.db.uno("SELECT COUNT(*) AS n FROM attivita WHERE azione='notifiche'")["n"], 2)  # cambia: si registra

    def test_il_controllo_non_blocca_il_riavvio_dopo_un_errore_dell_archivio(self):
        c = self.ctx([revolut("Revolut", "Hai ricevuto 5,00 € da Mario")])
        with mock.patch.object(c.pian, "esegui", wraps=c.pian.esegui) as e:
            self.esegui(c)
        self.assertEqual(e.call_count, 2)  # notifiche, poi fatture


class TestAdaVedeLaLettura(Base):
    def test_riepilogo_e_stato_dicono_se_la_lettura_funziona(self):
        c = self.ctx([revolut("Bar Roma", "Hai speso 5,80 €"), revolut("Promo", "Scopri", key="k2")])
        self.assertIn("nessuna lettura registrata", c.ada._esegui("ada", "riepilogo_spese", {}))
        c.pian.esegui(c.db.uno("SELECT id FROM routine WHERE nome='notifiche'")["id"])
        r = c.ada._esegui("ada", "riepilogo_spese", {"periodo": "sempre"})
        self.assertIn("ultima 0 min fa, funziona", r)
        self.assertIn("2 notifiche Revolut (1 movimenti nuovi, 1 non riconosciute)", r)
        self.assertIn("Promo: Scopri", r)  # Ada vede cosa non sa leggere
        self.assertIn("Lettura notifiche Revolut: ultima", c.ada._esegui("ada", "stato_sistema", {}))

    def test_errore_di_lettura_arriva_ad_ada_con_la_causa(self):
        c = self.ctx(None)

        def rotto():
            raise ErroreLettura("risposta illeggibile: forse a Termux:API manca l'accesso alle notifiche")
        c.ada.lettore_notifiche = rotto
        c.pian.esegui(c.db.uno("SELECT id FROM routine WHERE nome='notifiche'")["id"])
        self.assertIn("FALLITA: risposta illeggibile", c.ada._esegui("ada", "stato_sistema", {}))

    def test_ada_sa_che_non_deve_chiedere_all_utente_prima_di_guardare(self):
        from src.ada.cervello import CAPACITA
        self.assertIn("routine «notifiche» ogni 2 minuti", CAPACITA)
        self.assertIn("chiedi all'utente di controllare il telefono solo se la lettura funziona", CAPACITA)

    def test_la_riga_arriva_all_app(self):
        c = self.ctx([revolut("Bar Roma", "Hai speso 5,80 €")])
        c.pian.esegui(c.db.uno("SELECT id FROM routine WHERE nome='notifiche'")["id"])
        self.assertIn("funziona", c.stato()["lettura"])


if __name__ == "__main__":
    unittest.main()
