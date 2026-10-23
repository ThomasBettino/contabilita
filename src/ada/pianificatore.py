"""Routine di Ada: lavori che partono da soli a orari fissi, con un tetto di consumo."""
import os
import threading
import time
from datetime import datetime, timedelta

try:
    from zoneinfo import ZoneInfo
except ImportError:  # Python senza zoneinfo
    ZoneInfo = None

PENDENTI = "('in_attesa','scelta','autorizzata','pronto')"

PREDEFINITE = [
    {"nome": "riepilogo_sera", "descrizione": "Riepilogo della giornata: spese, cose da decidere, miglioramenti.",
     "tipo": "ada", "ora": "21:00", "ogni_min": None,
     "prompt": ("Prepara il riepilogo della giornata per l'utente. Usa riepilogo_spese per i dati reali (indica anche "
                "l'ora dell'ultimo movimento letto), riepilogo_fatture per fatture e tasse da accantonare e stato_sistema per sapere cosa aspetta una sua decisione e quali "
                "segnalazioni sono aperte. Massimo 6 righe, numeri veri, al massimo una cosa da fare. Non parlare del "
                "collegamento dello schermo del telefono: è normale che sia spento e non riguarda i movimenti. Se non c'è "
                "niente di rilevante, dillo in una riga.")},
    {"nome": "miglioria_quotidiana", "descrizione": "Ogni giorno una miglioria concreta all'app o al team.",
     "tipo": "ada", "ora": "06:30", "ogni_min": None,
     "prompt": ("Routine di miglioramento quotidiano: oggi l'app e il team devono migliorare di una cosa concreta. "
                "1) Guarda stato_sistema (attività, errori, segnalazioni, idee già proposte) e riepilogo_spese (esercenti rimasti "
                "senza categoria). 2) Scegli la miglioria più utile e a basso rischio. 3) Se è alla portata dei tuoi strumenti "
                "(migliora_prompt, regola_categoria, gestisci_routine, chiudi_segnalazione) falla subito. 4) Se serve codice nuovo "
                "e non hai già proposto un'idea oggi, usa proponi_idea con un motivo basato su un fatto osservato. 5) Non toccare "
                "soldi, schermo o regole di sicurezza. Chiudi con 3-4 righe: cosa hai migliorato oggi e perché. Se davvero non "
                "c'è nulla da migliorare, dillo in una riga senza inventare.")},
    {"nome": "fatture", "descrizione": "Aggiorna l'archivio fatture e riconosce i bonifici in arrivo sul conto.",
     "tipo": "codice", "ora": None, "ogni_min": 10, "prompt": None},
    {"nome": "miglioramento", "descrizione": "Rivede le segnalazioni aperte e migliora i prompt (solo se ce ne sono).",
     "tipo": "codice", "ora": None, "ogni_min": 360, "prompt": None},
    {"nome": "promemoria_approvazioni", "descrizione": "Ti ricorda con una notifica le cose ferme in attesa di te.",
     "tipo": "codice", "ora": None, "ogni_min": 120, "prompt": None},
]


def _fuso():
    try:
        return ZoneInfo(os.environ.get("ADA_FUSO", "Europe/Rome")) if ZoneInfo else None
    except Exception:  # database dei fusi orari assente: si usa l'ora del telefono
        return None


def prossima_esecuzione(ora, ogni_min, adesso) -> int:
    if ogni_min:
        return int(adesso + ogni_min * 60)
    h, m = map(int, ora.split(":"))
    dt = datetime.fromtimestamp(adesso, _fuso())
    cand = dt.replace(hour=h, minute=m, second=0, microsecond=0)
    if cand <= dt:
        cand += timedelta(days=1)
    return int(cand.timestamp())


class Pianificatore:
    def __init__(self, ada, adesso=time.time, ogni=30):
        self.ada, self.db, self.adesso, self.ogni = ada, ada.db, adesso, ogni
        self._stop = threading.Event()
        for r in PREDEFINITE:
            self.db.esegui("INSERT OR IGNORE INTO routine (nome, descrizione, tipo, ora, ogni_min, prompt, prossima) "
                           "VALUES (?,?,?,?,?,?,?)",
                           (r["nome"], r["descrizione"], r["tipo"], r["ora"], r["ogni_min"], r["prompt"],
                            prossima_esecuzione(r["ora"], r["ogni_min"], self.adesso())))
            # le routine di sistema non le modifica Ada: si tengono allineate al codice a ogni avvio
            self.db.esegui("UPDATE routine SET descrizione=?, tipo=?, prompt=? WHERE nome=?",
                           (r["descrizione"], r["tipo"], r["prompt"], r["nome"]))

    def elenco(self):
        return self.db.tutti("SELECT id, nome, descrizione, tipo, ora, ogni_min, attiva, prossima, ultima, esito "
                             "FROM routine ORDER BY id")

    def tick(self):
        for r in self.db.tutti("SELECT id FROM routine WHERE attiva=1 AND prossima<=?", (int(self.adesso()),)):
            self.esegui(r["id"])

    def esegui(self, id_, manuale=False) -> str:
        r = self.db.uno("SELECT * FROM routine WHERE id=?", (id_,))
        if not r:
            raise LookupError("Routine sconosciuta.")
        # Si riprogramma prima di partire: se il lavoro dura o fallisce non si ripete a raffica.
        adesso = int(self.adesso())
        self.db.esegui("UPDATE routine SET prossima=? WHERE id=?",
                       (prossima_esecuzione(r["ora"], r["ogni_min"], adesso), id_))
        try:
            esito = self._lavoro(r, manuale)
        except Exception as e:
            esito = f"Errore: {type(e).__name__}"
            self.ada.log("sistema", "errore routine", f"{r['nome']}: {e}")
        self.db.esegui("UPDATE routine SET ultima=?, esito=? WHERE id=?", (adesso, str(esito)[:300], id_))
        self.ada.log("routine", r["nome"], str(esito)[:200])
        return str(esito)

    def _lavoro(self, r, manuale):
        if r["tipo"] == "codice":
            return getattr(self, "_" + r["nome"])(manuale)
        if self.ada.sopra_limite() and not manuale:
            return "Saltata: limite di consumo di oggi raggiunto."
        return self.ada.lavoro_proattivo(r["prompt"], r["nome"])

    def _fatture(self, manuale):
        from .fatture import ErroreFatture
        a = getattr(self.ada, "archivio", None)
        if not a or not a.configurato:
            return "Non configurato: mancano ADA_FATTURE_URL e ADA_FATTURE_TOKEN."
        try:
            with self.ada._lavora("contabilita_piva", "Aggiorno l'archivio fatture e cerco i bonifici in arrivo"):
                s = a.sincronizza()
                inc = a.elabora_incassi()
        except ErroreFatture as e:
            return f"Non riesco a leggere l'archivio: {e}"
        return f"Archivio: {s['totale']} fatture ({s['nuove']} nuove). {inc}"[:250]

    def _miglioramento(self, manuale):
        if not self.db.uno("SELECT 1 AS x FROM segnalazioni WHERE stato='aperta'"):
            return "Nessuna segnalazione aperta: niente da fare."
        if self.ada.sopra_limite() and not manuale:
            return "Saltata: limite di consumo di oggi raggiunto."
        return self.ada.ciclo_miglioramento(automatico=not manuale)[:250]

    def _promemoria_approvazioni(self, manuale):
        ferme = self.db.uno(f"SELECT COUNT(*) AS n FROM approvazioni WHERE stato IN {PENDENTI} AND ts<?",
                            (int(self.adesso()) - 7200,))["n"]
        if not ferme:
            return "Niente fermo in attesa."
        self.ada.avvisa("Ada ti aspetta", f"{ferme} {'cosa aspetta' if ferme == 1 else 'cose aspettano'} una tua decisione.",
                        "ada-promemoria")
        return f"Promemoria inviato: {ferme} in attesa."

    def avvia(self):
        def giro():
            while not self._stop.wait(self.ogni):
                try:
                    self.tick()
                except Exception as e:
                    self.ada.log("sistema", "errore pianificatore", e)
        threading.Thread(target=giro, daemon=True, name="pianificatore").start()

    def ferma(self):
        self._stop.set()
