"""Legge le notifiche Android (Termux:API) e aggiorna i movimenti.

Uso sul telefono:  python -m src.revolut.ingest [--db movimenti.db]
Per i test si può passare l'elenco JSON da stdin:  --stdin
"""
import argparse
import json
import subprocess
import sys
import time

from .parser import parse
from .store import apri, riepilogo, salva_lettura, salva_movimento, salva_non_riconosciuta

PACCHETTO = "com.revolut.revolut"


class ErroreLettura(Exception):
    """La lettura delle notifiche non è riuscita: il messaggio dice perché, in parole semplici."""


def leggi_notifiche_termux(timeout=20):
    try:
        out = subprocess.run(["termux-notification-list"], capture_output=True, text=True, check=True, timeout=timeout)
    except FileNotFoundError:
        raise ErroreLettura("manca Termux:API (in Termux: pkg install termux-api)") from None
    except subprocess.TimeoutExpired:
        raise ErroreLettura("Termux:API non risponde") from None
    except subprocess.CalledProcessError as e:
        raise ErroreLettura(f"termux-notification-list ha dato errore ({(e.stderr or '').strip()[:100] or e.returncode})") from None
    try:
        notifiche = json.loads(out.stdout or "[]")
    except ValueError:
        raise ErroreLettura("risposta illeggibile: forse a Termux:API manca l'accesso alle notifiche") from None
    if not isinstance(notifiche, list):
        raise ErroreLettura("risposta inattesa da Termux:API")
    return notifiche


def leggi_notifiche(da_stdin: bool):
    if da_stdin:
        return json.load(sys.stdin)
    return leggi_notifiche_termux()


def elabora(db, notifiche) -> dict:
    esito = {"nuovi": 0, "non_riconosciuti": 0, "ignorati": 0}
    for n in notifiche:
        if n.get("packageName") != PACCHETTO:
            esito["ignorati"] += 1
            continue
        titolo, contenuto = n.get("title") or "", n.get("content") or ""
        chiave = f'{n.get("key") or n.get("id")}|{n.get("when")}|{titolo}|{contenuto}'
        mov = parse(titolo, contenuto)
        if mov:
            esito["nuovi"] += salva_movimento(db, chiave, n.get("when"), mov)
        else:
            esito["non_riconosciuti"] += salva_non_riconosciuta(db, chiave, n.get("when"), titolo, contenuto)
    return esito


def leggi_e_salva(db, leggi=leggi_notifiche_termux, adesso=time.time) -> dict:
    """Una lettura completa: notifiche -> movimenti, e si annota com'è andata (anche se è fallita)."""
    try:
        notifiche = leggi()
    except ErroreLettura as e:
        salva_lettura(db, adesso(), errore=str(e)[:200])
        return {"errore": str(e)}
    esito = elabora(db, notifiche)
    revolut = sum(1 for n in notifiche if n.get("packageName") == PACCHETTO)
    salva_lettura(db, adesso(), len(notifiche), revolut, esito["nuovi"], esito["non_riconosciuti"])
    return {**esito, "revolut": revolut}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="movimenti.db")
    ap.add_argument("--stdin", action="store_true")
    a = ap.parse_args()
    db = apri(a.db)
    esito = leggi_e_salva(db, lambda: leggi_notifiche(a.stdin))
    print(esito)
    if "errore" in esito:
        sys.exit(1)
    for controparte, tot in riepilogo(db)[:10]:
        print(f"{tot:>10.2f}  {controparte or '(senza nome)'}")


if __name__ == "__main__":
    main()
