"""Comandi ADB (Termux, debug wireless). L'esecutore è iniettabile per i test."""
import re
import shlex
import subprocess
import time
import unicodedata


class ErroreAdb(Exception):
    pass


class Adb:
    def __init__(self, esegui=None, seriale=None, timeout=20, dormi=time.sleep):
        self._run, self.seriale, self.timeout, self.dormi = esegui or subprocess.run, seriale, timeout, dormi
        self._dim = None

    def _cmd(self, *args, con_seriale=True) -> str:
        cmd = ["adb"] + (["-s", self.seriale] if self.seriale and con_seriale else []) + list(args)
        try:
            r = self._run(cmd, capture_output=True, timeout=self.timeout)
        except FileNotFoundError:
            raise ErroreAdb("adb non installato (pkg install android-tools)") from None
        except subprocess.TimeoutExpired:
            raise ErroreAdb("adb non risponde") from None
        if r.returncode != 0:
            raise ErroreAdb((r.stderr or b"").decode("utf-8", "replace").strip()[:200] or "adb ha dato errore")
        return (r.stdout or b"").decode("utf-8", "replace")

    def scopri(self):
        """Cerca la porta del Debug wireless annunciata sulla rete (mDNS). Restituisce (host, porta) o None."""
        try:
            out = self._cmd("mdns", "services", con_seriale=False)
        except ErroreAdb:
            return None
        for riga in out.splitlines():
            m = re.search(r"_adb-tls-connect.*?\s(\S+):(\d{4,5})\s*$", riga)
            if m:
                return m.group(1), int(m.group(2))
        return None

    def collega(self, porta=None) -> str:
        """Collega ADB al telefono e fissa la porta 5555. Con porta=None la cerca da sola."""
        trovato = self.scopri()
        if porta is None:
            if not trovato:
                raise ErroreAdb("non trovo la porta da sola: leggila in Debug wireless e inseriscila")
            porta = trovato[1]
        porta = int(porta)
        if not 1024 <= porta <= 65535:
            raise ErroreAdb("porta non valida")
        hosts = ["localhost"] + ([trovato[0]] if trovato and trovato[0] != "localhost" else [])
        bersaglio = None
        for host in hosts:
            out = self._cmd("connect", f"{host}:{porta}", con_seriale=False)
            if "connected" in out.lower() and "cannot" not in out.lower():
                bersaglio = f"{host}:{porta}"
                break
        if not bersaglio:
            raise ErroreAdb(f"collegamento rifiutato sulla porta {porta}: la porta è cambiata o il Debug wireless è spento")
        self.seriale = bersaglio
        try:  # porta fissa: sopravvive finché il wifi resta acceso
            self._cmd("-s", bersaglio, "tcpip", "5555", con_seriale=False)
            self.dormi(3)
            out = self._cmd("connect", "localhost:5555", con_seriale=False)
            if "connected" in out.lower():
                self.seriale = "localhost:5555"
        except ErroreAdb:
            pass
        self._dim = None
        return f"Telefono collegato ({self.seriale})."

    def collegato(self) -> bool:
        try:
            return self._cmd("get-state").strip() == "device"
        except ErroreAdb:
            return False

    def dump(self) -> str:
        out = self._cmd("exec-out", "uiautomator", "dump", "/dev/tty")
        a, b = out.find("<?xml"), out.rfind("</hierarchy>")
        if a < 0 or b < 0:
            raise ErroreAdb("schermata non leggibile")
        return out[a:b + len("</hierarchy>")]

    def tap(self, x, y):
        self._cmd("shell", "input", "tap", str(int(x)), str(int(y)))

    def scrivi(self, testo: str):
        pulito = unicodedata.normalize("NFKD", testo).encode("ascii", "ignore").decode()
        pulito = re.sub(r"[^A-Za-z0-9 .,_@:/?=&+-]", "", pulito)[:200]
        if not pulito:
            raise ErroreAdb("testo vuoto dopo la pulizia (solo caratteri ASCII)")
        self._cmd("shell", "input", "text", shlex.quote(pulito.replace(" ", "%s")))

    def _dimensioni(self):
        if not self._dim:
            m = re.search(r"(\d+)x(\d+)", self._cmd("shell", "wm", "size"))
            self._dim = (int(m.group(1)), int(m.group(2))) if m else (1080, 2340)
        return self._dim

    def scorri(self, direzione: str):
        w, h = self._dimensioni()
        a, b = (0.72, 0.28) if direzione == "giu" else (0.28, 0.72)
        self._cmd("shell", "input", "swipe", str(w // 2), str(int(h * a)), str(w // 2), str(int(h * b)), "300")

    def tasto(self, nome: str):
        self._cmd("shell", "input", "keyevent", {"indietro": "4", "home": "3"}[nome])

    def apri_app(self, pacchetto: str):
        if not re.fullmatch(r"[A-Za-z0-9_.]+", pacchetto):
            raise ErroreAdb("nome app non valido")
        self._cmd("shell", "monkey", "-p", pacchetto, "-c", "android.intent.category.LAUNCHER", "1")

    def apri_url(self, url: str):
        self._cmd("shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", shlex.quote(url))
