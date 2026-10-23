"""La "mano" di Ada: guarda e usa lo schermo, sempre attraverso il guardiano."""
import re
import time

from .adb import Adb, ErroreAdb
from .guardiano import app_protetta, valuta_digitazione, valuta_tocco
from .schermo import parse, render

APP = {
    "amazon": "com.amazon.mShop.android.shopping", "chrome": "com.android.chrome",
    "whatsapp": "com.whatsapp", "gmail": "com.google.android.gm",
    "calendario": "com.google.android.calendar", "impostazioni": "com.android.settings",
}


class Mano:
    def __init__(self, adb=None, autorizzato=lambda: False, log=lambda *a: None, pausa=1.2, dormi=time.sleep):
        self.adb, self.autorizzato, self.log, self.pausa, self.dormi = adb or Adb(), autorizzato, log, pausa, dormi
        self.fermo, self.elementi, self.pacchetto = False, [], ""

    def disponibile(self) -> bool:
        return not self.fermo and self.adb.collegato()

    def stato(self) -> dict:
        return {"collegato": self.adb.collegato(), "fermo": self.fermo}

    def _via_libera(self):
        if self.fermo:
            return "FERMO: l'utente ha fermato il controllo del telefono. Non fare altro e avvisalo."
        return None

    def collega(self, porta=None) -> str:
        if (m := self._via_libera()):
            return m
        try:
            return self.adb.collega(porta)
        except (ErroreAdb, ValueError) as e:
            return f"Collegamento non riuscito: {e}"

    def guarda(self) -> str:
        if (m := self._via_libera()):
            return m
        if not self.adb.collegato():  # una prova automatica prima di arrendersi
            try:
                self.adb.collega()
            except (ErroreAdb, ValueError) as e:
                return (f"Telefono non collegato ({e}). Chiedi all'utente di accendere il Debug wireless "
                        "con il wifi e di toccare Collega in Ada, oppure di dirti la porta.")
        try:
            self.pacchetto, self.elementi = parse(self.adb.dump())
        except Exception as e:  # adb assente o XML illeggibile
            return f"Non riesco a leggere lo schermo: {e}"
        if app_protetta(self.pacchetto):
            self.elementi = []
            return (f"App protetta ({self.pacchetto}): non leggo né tocco questa schermata. "
                    "Torna indietro o vai alla home.")
        return render(self.pacchetto, self.elementi)

    def _dopo(self, descrizione: str) -> str:
        self.log("telefono", descrizione)
        self.dormi(self.pausa)
        return self.guarda()

    def _esegui(self, descrizione, azione) -> str:
        if (m := self._via_libera()):
            return m
        try:
            azione()
        except ErroreAdb as e:
            return f"Azione fallita: {e}"
        return self._dopo(descrizione)

    def _trova(self, id_):
        for e in self.elementi:
            if e.id == int(id_):
                return e
        return None

    def tocca(self, id_) -> str:
        if (m := self._via_libera()):
            return m
        if app_protetta(self.pacchetto):
            return "BLOCCATO: app protetta, non la tocco."
        e = self._trova(id_)
        if not e:
            return "Elemento non trovato: guarda lo schermo e usa un numero valido."
        motivo = valuta_tocco(e, self.elementi, self.autorizzato())
        if motivo:
            self.log("telefono", f"tocco bloccato su «{e.etichetta[:40]}»: {motivo[:80]}")
            return "BLOCCATO: " + motivo
        return self._esegui(f"tocco su «{e.etichetta[:40]}»", lambda: self.adb.tap(*e.centro))

    def scrivi(self, id_, testo) -> str:
        if (m := self._via_libera()):
            return m
        e = self._trova(id_)
        if not e or not e.modificabile:
            return "Questo elemento non è un campo di testo."
        motivo = valuta_digitazione(e, str(testo))
        if motivo:
            return "BLOCCATO: " + motivo

        def fai():
            self.adb.tap(*e.centro)
            self.dormi(0.4)
            self.adb.scrivi(str(testo))
        return self._esegui("scrittura in un campo di testo", fai)

    def scorri(self, direzione) -> str:
        return self._esegui(f"scorrimento {direzione}", lambda: self.adb.scorri("giu" if direzione == "giu" else "su"))

    def vai(self, azione) -> str:
        if azione not in ("indietro", "home"):
            return "Azione sconosciuta."
        return self._esegui(azione, lambda: self.adb.tasto(azione))

    def apri(self, app="", url="") -> str:
        if url:
            if not re.fullmatch(r"https://[^\s'\"`$;&|<>]+", url):
                return "BLOCCATO: apro solo indirizzi https semplici."
            return self._esegui(f"apertura di {url[:60]}", lambda: self.adb.apri_url(url))
        pacchetto = APP.get(app.lower().strip(), app.strip())
        if app_protetta(pacchetto):
            return "BLOCCATO: app protetta, non la apro."
        return self._esegui(f"apertura app {pacchetto}", lambda: self.adb.apri_app(pacchetto))
