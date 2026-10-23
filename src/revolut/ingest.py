"""Legge le notifiche Android (Termux:API) e aggiorna i movimenti.

Uso sul telefono:  python -m src.revolut.ingest [--db movimenti.db]
Per i test si può passare l'elenco JSON da stdin:  --stdin
"""
import argparse
import json
import subprocess
import sys

from .parser import parse
from .store import apri, riepilogo, salva_movimento, salva_non_riconosciuta

PACCHETTO = "com.revolut.revolut"


def leggi_notifiche(da_stdin: bool):
    if da_stdin:
        return json.load(sys.stdin)
    out = subprocess.run(["termux-notification-list"], capture_output=True, text=True, check=True)
    return json.loads(out.stdout or "[]")


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="movimenti.db")
    ap.add_argument("--stdin", action="store_true")
    a = ap.parse_args()
    db = apri(a.db)
    print(elabora(db, leggi_notifiche(a.stdin)))
    for controparte, tot in riepilogo(db)[:10]:
        print(f"{tot:>10.2f}  {controparte or '(senza nome)'}")


if __name__ == "__main__":
    main()
