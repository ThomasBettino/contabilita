import unittest

from src.revolut.ingest import elabora
from src.revolut.parser import parse
from src.revolut.store import apri, riepilogo


class TestParser(unittest.TestCase):
    def test_pagamento(self):
        m = parse("Revolut", "Pagamento di 12,50 € a Esselunga")
        self.assertEqual((m.importo, m.controparte), (-12.5, "Esselunga"))

    def test_entrata_migliaia(self):
        m = parse("Hai ricevuto", "€1.250,00 da Mario Rossi")
        self.assertEqual((m.importo, m.controparte), (1250.0, "Mario Rossi"))

    def test_non_riconosciuta(self):
        self.assertIsNone(parse("Revolut", "Nuove funzioni disponibili"))


class TestIngest(unittest.TestCase):
    def test_deduplica_e_riepilogo(self):
        db = apri(":memory:")
        notifiche = [
            {"packageName": "com.revolut.revolut", "key": "1", "when": 1, "title": "Revolut",
             "content": "Pagamento di 10,00 € a Bar Roma"},
            {"packageName": "com.whatsapp", "key": "2", "when": 2, "title": "x", "content": "ciao"},
            {"packageName": "com.revolut.revolut", "key": "3", "when": 3, "title": "Revolut",
             "content": "Novità"},
        ]
        self.assertEqual(elabora(db, notifiche), {"nuovi": 1, "non_riconosciuti": 1, "ignorati": 1})
        self.assertEqual(elabora(db, notifiche)["nuovi"], 0)
        self.assertEqual(riepilogo(db), [("Bar Roma", 10.0)])


if __name__ == "__main__":
    unittest.main()
