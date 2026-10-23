import os
import unittest
import urllib.request

from src.ada.fatture import ClienteScript
from src.ada.github import ClienteGitHub
from src.ada.llm import Claude


class TestIgiene(unittest.TestCase):
    def test_nessuna_impostazione_vera_nell_ambiente(self):
        sporche = [k for k in os.environ if k.startswith("ADA_") or k in ("ANTHROPIC_API_KEY", "GITHUB_TOKEN", "GH_TOKEN")]
        self.assertEqual(sporche, [])

    def test_i_collegamenti_di_default_non_escono_su_internet(self):
        with self.assertRaises(AssertionError) as e:
            ClienteGitHub("proprietario/app", "token").crea_issue("t", "c")
        self.assertIn("rete vera", str(e.exception))
        with self.assertRaises(AssertionError):
            Claude(chiave="k")("p", [{"role": "user", "content": "x"}])
        with self.assertRaises(AssertionError):
            ClienteScript("https://script.google.com/macros/s/X/exec", "t").chiama(action="list")

    def test_il_server_locale_resta_raggiungibile(self):
        with self.assertRaises(OSError):  # connessione rifiutata sulla porta 1: è la rete locale, non la guardia
            urllib.request.urlopen("http://127.0.0.1:1/")


if __name__ == "__main__":
    unittest.main()
