"""Archivio SQLite dei movimenti e delle notifiche non riconosciute."""
import sqlite3
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS movimenti (
  chiave TEXT PRIMARY KEY, quando INTEGER, importo REAL, controparte TEXT, testo TEXT);
CREATE TABLE IF NOT EXISTS non_riconosciute (
  chiave TEXT PRIMARY KEY, quando INTEGER, titolo TEXT, contenuto TEXT);
CREATE TABLE IF NOT EXISTS letture (
  id INTEGER PRIMARY KEY CHECK (id = 1), quando INTEGER, totale INTEGER, revolut INTEGER, nuovi INTEGER,
  non_riconosciuti INTEGER, errore TEXT);
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


def salva_lettura(db, quando, totale=0, revolut=0, nuovi=0, non_riconosciuti=0, errore=""):
    """Ricorda com'è andata l'ultima lettura delle notifiche: serve a capire se la lettura funziona."""
    db.execute("INSERT INTO letture VALUES (1,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET quando=excluded.quando, "
               "totale=excluded.totale, revolut=excluded.revolut, nuovi=excluded.nuovi, "
               "non_riconosciuti=excluded.non_riconosciuti, errore=excluded.errore",
               (int(quando), totale, revolut, nuovi, non_riconosciuti, errore))
    db.commit()


def riepilogo(db):
    """Totale uscite per controparte, dalla più cara."""
    return db.execute(
        "SELECT controparte, ROUND(-SUM(importo),2) FROM movimenti WHERE importo<0 "
        "GROUP BY controparte ORDER BY 2 DESC").fetchall()
