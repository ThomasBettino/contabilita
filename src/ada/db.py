"""Archivio SQLite di Ada: chat, attività, approvazioni, miglioramenti, segnalazioni."""
import os
import sqlite3
import threading
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS chat (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, ruolo TEXT, testo TEXT);
CREATE TABLE IF NOT EXISTS attivita (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, agente TEXT, azione TEXT, dettaglio TEXT);
CREATE TABLE IF NOT EXISTS approvazioni (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, tipo TEXT, titolo TEXT, dettaglio TEXT,
  stato TEXT DEFAULT 'in_attesa', risolta_ts INTEGER);
CREATE TABLE IF NOT EXISTS miglioramenti (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, agente TEXT, motivo TEXT,
  vecchio TEXT, nuovo TEXT, tipo TEXT, stato TEXT, approvazione_id INTEGER);
CREATE TABLE IF NOT EXISTS routine (
  id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT UNIQUE, descrizione TEXT, tipo TEXT,
  ora TEXT, ogni_min INTEGER, attiva INTEGER DEFAULT 1, prompt TEXT,
  prossima INTEGER, ultima INTEGER, esito TEXT);
CREATE TABLE IF NOT EXISTS consumi (
  giorno TEXT PRIMARY KEY, input INTEGER DEFAULT 0, output INTEGER DEFAULT 0, chiamate INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS idee (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, titolo TEXT, descrizione TEXT, motivo TEXT,
  stato TEXT DEFAULT 'proposta', approvazione_id INTEGER, ts_stato INTEGER);
CREATE TABLE IF NOT EXISTS regole_categoria (parola TEXT PRIMARY KEY, categoria TEXT);
CREATE TABLE IF NOT EXISTS collaudi (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, categoria TEXT, richiesta TEXT, trascrizione TEXT,
  voto INTEGER, problemi TEXT);
CREATE TABLE IF NOT EXISTS appunti (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, tipo TEXT, titolo TEXT, testo TEXT, azioni TEXT);
CREATE TABLE IF NOT EXISTS eventi (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, titolo TEXT, giorno TEXT, ora TEXT DEFAULT '', tipo TEXT DEFAULT 'promemoria',
  note TEXT DEFAULT '', ripeti TEXT DEFAULT '', preavviso INTEGER DEFAULT 0, stato TEXT DEFAULT 'attivo',
  avvisato INTEGER DEFAULT 0, origine TEXT DEFAULT 'utente');
CREATE TABLE IF NOT EXISTS vendite_coda (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, frase TEXT, riassunto TEXT, stato TEXT DEFAULT 'da_riportare', ts_stato INTEGER);
CREATE TABLE IF NOT EXISTS fatture (id TEXT PRIMARY KEY, dati TEXT);
CREATE TABLE IF NOT EXISTS kv (chiave TEXT PRIMARY KEY, valore TEXT);
CREATE TABLE IF NOT EXISTS movimenti_visti (chiave TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS segnalazioni (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, agente TEXT, problema TEXT,
  fonte TEXT, stato TEXT DEFAULT 'aperta', esito TEXT);
"""


def casa() -> Path:
    """Cartella di lavoro di Ada (database e prompt vivi), fuori dal repo."""
    return Path(os.environ.get("ADA_HOME") or Path.home() / "ada")


class DB:
    def __init__(self, percorso):
        self.c = sqlite3.connect(str(percorso), check_same_thread=False)
        self.c.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        self.c.executescript(SCHEMA)
        for colonna, tipo in (("azioni", "TEXT"),):  # database creati prima: si aggiunge la colonna
            if colonna not in [r[1] for r in self.c.execute("PRAGMA table_info(chat)")]:
                self.c.execute(f"ALTER TABLE chat ADD COLUMN {colonna} {tipo}")
        self.c.commit()

    def esegui(self, sql, args=()):
        with self.lock:
            cur = self.c.execute(sql, args)
            self.c.commit()
            return cur

    def tutti(self, sql, args=()):
        with self.lock:
            return [dict(r) for r in self.c.execute(sql, args).fetchall()]

    def uno(self, sql, args=()):
        righe = self.tutti(sql, args)
        return righe[0] if righe else None
