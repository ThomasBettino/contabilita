"""Aggiornamento con un tocco: scarica la versione nuova, la collauda e, se non va, torna indietro."""
import os
import subprocess
import sys
import threading
from pathlib import Path

RADICE = Path(__file__).resolve().parents[2]


def _git(args, run=subprocess.run, timeout=90):
    r = run(["git", "-C", str(RADICE), *args], capture_output=True, text=True, timeout=timeout)
    return r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()


def versione(run=subprocess.run) -> dict:
    try:
        rc, out = _git(["log", "-1", "--format=%h|%cd|%s", "--date=format:%d/%m %H:%M"], run, 10)
        _, ramo = _git(["rev-parse", "--abbrev-ref", "HEAD"], run, 10)
        if rc == 0 and out.count("|") >= 2:
            id_, data, titolo = out.split("|", 2)
            return {"id": id_, "data": data, "titolo": titolo[:90], "ramo": ramo}
    except (OSError, subprocess.SubprocessError):
        pass
    return {"id": "?", "data": "", "titolo": "versione non leggibile", "ramo": ""}


def _ambiente_pulito():
    """Per i test: niente chiavi né impostazioni vere, così non possono dipendere dal telefono."""
    return {k: v for k, v in os.environ.items() if not k.startswith("ADA_") and k != "ANTHROPIC_API_KEY"}


def aggiorna(run=subprocess.run) -> dict:
    """Solo avanzamento semplice (fast-forward). Se i test della versione nuova non passano, annulla."""
    try:
        rc, out = _git(["pull", "--ff-only"], run)
        if rc != 0:
            return {"ok": False, "cambiato": False, "messaggio": f"Aggiornamento non riuscito: {out[-200:]}"}
        if "Already up to date" in out or "Già aggiornato" in out:
            return {"ok": True, "cambiato": False, "messaggio": "Ada è già all'ultima versione."}
        prova = run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."], capture_output=True,
                    text=True, timeout=300, cwd=str(RADICE), env=_ambiente_pulito())
        if prova.returncode != 0:
            _git(["reset", "--hard", "ORIG_HEAD"], run)
            coda = ((prova.stderr or "") + (prova.stdout or "")).strip().splitlines()[-1:]
            return {"ok": False, "cambiato": False,
                    "messaggio": "La versione nuova non ha superato i test: sono tornata a quella di prima. " + " ".join(coda)[:150]}
        return {"ok": True, "cambiato": True, "messaggio": "Aggiornata: Ada si riavvia."}
    except (OSError, subprocess.SubprocessError) as e:
        return {"ok": False, "cambiato": False, "messaggio": f"Aggiornamento non riuscito ({type(e).__name__})."}


def riavvia_tra(secondi=2):
    """Riparte con lo stesso programma, le stesse chiavi e lo stesso file di log."""
    def vai():
        os.chdir(RADICE)
        os.execv(sys.executable, [sys.executable, "-u", "-m", "src.ada.server"])
    t = threading.Timer(secondi, vai)
    t.daemon = True
    t.start()
