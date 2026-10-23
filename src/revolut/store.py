"""Archivio SQLite dei movimenti e delle notifiche non riconosciute."""
import sqlite3
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS movimenti (
  chiave TEXT PRIMARY KEY, quando INTEGER, importo REAL, controparte TEXT, testo TEXT);
CREATE TABLE IF NOT EXISTS non_riconosciute (
  chiave TEXT PRIMARY KEY, quando INTEGER, titolo TEXT, contenuto TEXT);
"""


def apri(percorso: str) -> sqlite3.Connection:
    db = sqlite3.connect(percorso)
    db.executescript(SCHEMA)
    return db


def salva_movimento(db, chiave, quando, mov) -> bool:
    cur = db.execute("INSERT OR IGNORE INTO movimenti VALUES (?,?,?,?,?)",
                     (chiave, quando, mov.importo, mov.controparte, mov.testo))
    db.commit()
    return cur.rowcount == 1


def salva_non_riconosciuta(db, chiave, quando, titolo, contenuto) -> bool:
    cur = db.execute("INSERT OR IGNORE INTO non_riconosciute VALUES (?,?,?,?)",
                     (chiave, quando, titolo, contenuto))
    db.commit()
    return cur.rowcount == 1


def riepilogo(db):
    """Totale uscite per controparte, dalla più cara."""
    return db.execute(
        "SELECT controparte, ROUND(-SUM(importo),2) FROM movimenti WHERE importo<0 "
        "GROUP BY controparte ORDER BY 2 DESC").fetchall()
