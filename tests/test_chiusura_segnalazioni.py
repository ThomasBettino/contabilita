import json
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

from src.ada.server import costruisci, crea_server
from tests.test_ada import FinteRisposte, testo, usa


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def ctx(self, llm=None):
        c = costruisci(llm=llm or FinteRisposte(), home=Path(self.tmp.name), movimenti=Path(self.tmp.name) / "n.db", token="")
        self.addCleanup(c.db.c.close)
        return c

    def righe(self, c, azione="segnalazione chiusa"):
        return c.db.tutti("SELECT agente, azione, dettaglio FROM attivita WHERE azione=? ORDER BY id", (azione,))


class TestChiusuraSegnalazioni(Base):
    def test_la_chiusura_lascia_una_riga_con_chi_numero_agente_ed_esito(self):
        c = self.ctx()
        c.ada.segnala("revisore", "ha sbagliato un totale", "utente")
        self.assertEqual(c.ada._esegui("ada", "chiudi_segnalazione", {"id": 1, "esito": "regola aggiunta al prompt"}),
                         "Segnalazione #1 chiusa.")
        riga = self.righe(c)
        self.assertEqual(len(riga), 1)
        self.assertEqual(riga[0]["agente"], "ada")  # chi l'ha chiusa
        self.assertEqual(riga[0]["dettaglio"], "#1 (revisore): regola aggiunta al prompt")
        s = c.db.uno("SELECT stato, esito FROM segnalazioni")
        self.assertEqual((s["stato"], s["esito"]), ("chiusa", "regola aggiunta al prompt"))

    def test_numero_inesistente_non_dice_chiusa_e_non_scrive_nulla(self):
        c = self.ctx()
        self.assertEqual(c.ada._esegui("ada", "chiudi_segnalazione", {"id": 99, "esito": "x"}), "Segnalazione #99 non trovata.")
        self.assertEqual(c.ada._esegui("ada", "chiudi_segnalazione", {"id": "abc", "esito": "x"}), "Numero di segnalazione non valido.")
        self.assertEqual(self.righe(c), [])

    def test_gia_chiusa_non_si_registra_due_volte(self):
        c = self.ctx()
        c.ada.segnala("revisore", "problema", "utente")
        c.ada._esegui("ada", "chiudi_segnalazione", {"id": 1, "esito": "fatto"})
        self.assertIn("era già chiusa", c.ada._esegui("ada", "chiudi_segnalazione", {"id": 1, "esito": "ancora"}))
        self.assertEqual(len(self.righe(c)), 1)
        self.assertEqual(c.db.uno("SELECT esito FROM segnalazioni")["esito"], "fatto")  # l'esito originale resta

    def test_senza_nota_lo_dice(self):
        c = self.ctx()
        c.ada.segnala("revisore", "problema", "utente")
        c.ada._esegui("ada", "chiudi_segnalazione", {"id": 1})
        self.assertEqual(self.righe(c)[0]["dettaglio"], "#1 (revisore): senza nota")

    def test_si_vede_in_stato_sistema_e_nel_popup(self):
        c = self.ctx()
        c.ada.segnala("revisore", "problema", "utente")
        c.ada._esegui("ada", "chiudi_segnalazione", {"id": 1, "esito": "sistemato"})
        out = c.ada._esegui("ada", "stato_sistema", {})
        self.assertIn("SEGNALAZIONI APERTE: 0", out)
        self.assertIn("ada: segnalazione chiusa #1 (revisore): sistemato", out)  # la chiusura non va più dedotta dal conteggio
        srv = crea_server(c, "127.0.0.1", 0)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        self.addCleanup(srv.server_close)
        d = json.load(urllib.request.urlopen(f"http://127.0.0.1:{srv.server_address[1]}/api/agenti/ada"))
        self.assertEqual(d["attivita"][0]["azione"], "segnalazione chiusa")

    def test_chi_non_e_ada_non_puo_chiudere(self):
        c = self.ctx()
        c.ada.segnala("revisore", "problema", "utente")
        self.assertEqual(c.ada._esegui("revisore", "chiudi_segnalazione", {"id": 1, "esito": "x"}), "Strumento non consentito.")
        self.assertEqual(c.db.uno("SELECT stato FROM segnalazioni")["stato"], "aperta")
        self.assertEqual(self.righe(c), [])

    def test_dal_ciclo_di_miglioramento_la_chiusura_resta_tracciata(self):
        llm = FinteRisposte(usa("aggiungi_regola_prompt", agente="revisore", regola="Controlla sempre gli arrotondamenti a due decimali.", motivo="#1"),
                            usa("chiudi_segnalazione", id=1, esito="regola aggiunta"), testo("Sistemato: regola aggiunta e segnalazione chiusa."))
        c = self.ctx(llm)
        c.ada.segnala("revisore", "arrotondamenti sbagliati", "utente")
        c.ada.ciclo_miglioramento()
        self.assertEqual(self.righe(c)[0]["dettaglio"], "#1 (revisore): regola aggiunta")
        self.assertEqual(len(self.righe(c, "prompt migliorato")), 1)  # accanto alla modifica al prompt
        self.assertEqual(c.db.uno("SELECT COUNT(*) AS n FROM segnalazioni WHERE stato='aperta'")["n"], 0)


if __name__ == "__main__":
    unittest.main()
