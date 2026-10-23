"""Notifiche sul telefono tramite Termux:API. Testi generici: niente cifre sul blocco schermo."""
import subprocess


class Notifica:
    def __init__(self, esegui=subprocess.run, url="http://localhost:8765"):
        self._run, self.url = esegui, url

    def invia(self, titolo: str, testo: str, id_: str = "ada") -> bool:
        """Con lo stesso id la notifica nuova sostituisce la vecchia: niente raffiche."""
        try:
            self._run(["termux-notification", "--id", id_, "--title", titolo[:60], "--content", testo[:120],
                       "--action", f"termux-open-url {self.url}"], capture_output=True, timeout=10)
            return True
        except Exception:  # Termux:API assente o telefono occupato: la notifica è un extra
            return False
