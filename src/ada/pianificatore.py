"""Routine di Ada: lavori che partono da soli a orari fissi, con un tetto di consumo."""
import json
import os
import threading
import time
from datetime import datetime, timedelta

try:
    from zoneinfo import ZoneInfo
except ImportError:  # Python senza zoneinfo
    ZoneInfo = None

PENDENTI = "('in_attesa','scelta','autorizzata','pronto')"

# Quanto lavora Ada da sola: ogni valore è ogni quanti minuti parte il lavoro (None = spento).
# Il moltiplicatore allarga il tetto giornaliero di token per i lavori automatici: più lavoro, più spesa.
RITMI = {
    "spento": {"etichetta": "Spento", "moltiplicatore": 1, "collaudo": None, "studio": None, "lettura": None, "miglioramento": 720,
               "descrizione": "Niente collaudi, studio e letture: restano solo le routine fisse."},
    "leggero": {"etichetta": "Leggero", "moltiplicatore": 1, "collaudo": 240, "studio": 720, "lettura": 720, "miglioramento": 360,
                "descrizione": "Un collaudo ogni 4 ore, uno studio e una lettura ogni 12."},
    "normale": {"etichetta": "Normale", "moltiplicatore": 2, "collaudo": 180, "studio": 420, "lettura": 240, "miglioramento": 180,
                "descrizione": "Un collaudo ogni 3 ore, uno studio ogni 7, una lettura ogni 4."},
    "intenso": {"etichetta": "Intenso", "moltiplicatore": 5, "collaudo": 30, "studio": 120, "lettura": 60, "miglioramento": 60,
                "descrizione": "Un collaudo ogni mezz'ora, studio ogni 2 ore, lettura ogni ora. Consuma molto."},
}
RITMO_PREDEFINITO = "normale"
SILENZIOSE = {"notifiche", "agenda"}

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
    {"nome": "collaudo", "descrizione": "Un collaudatore esigente mette Ada alla prova in una simulazione e segnala i punti deboli.",
     "tipo": "codice", "ora": None, "ogni_min": 120, "prompt": None},
    {"nome": "studio", "descrizione": "Ada studia un grande pensatore (scienziato, matematico, venditore) e ne ricava una regola utile.",
     "tipo": "codice", "ora": None, "ogni_min": 360, "prompt": None},
    {"nome": "lettura", "descrizione": "Ada legge a pezzi i libri che metti nella cartella ~/ada/libri e ne ricava appunti.",
     "tipo": "codice", "ora": None, "ogni_min": 240, "prompt": None},
    {"nome": "notifiche", "descrizione": "Legge le notifiche di Revolut dal telefono ogni 2 minuti: non serve lo schermo né l'utente.",
     "tipo": "codice", "ora": None, "ogni_min": 2, "prompt": None},
    {"nome": "agenda", "descrizione": "Controlla l'agenda ogni minuto e avvisa sul telefono all'ora di promemoria ed eventi.",
     "tipo": "codice", "ora": None, "ogni_min": 1, "prompt": None},
    {"nome": "agenda_mattina", "descrizione": "Ogni mattina avvisa con un riepilogo di ciò che c'è in agenda oggi (se non c'è niente, non fa niente).",
     "tipo": "codice", "ora": "07:30", "ogni_min": None, "prompt": None},
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

        if self.ritmo() is None:
            self.imposta_ritmo(RITMO_PREDEFINITO)
        else:
            self._allinea_ritmo()

    def _allinea_ritmo(self):
        """Il ritmo scelto decide la cadenza di queste routine: dopo un aggiornamento del codice si riallinea."""
        adesso, ritmo = int(self.adesso()), RITMI.get(self.ritmo())
        for chiave in ("collaudo", "studio", "lettura", "miglioramento"):
            ogni = ritmo and ritmo[chiave]
            r = self.db.uno("SELECT ogni_min, prossima FROM routine WHERE nome=?", (chiave,))
            if ogni and r and r["ogni_min"] != ogni:
                self.db.esegui("UPDATE routine SET ogni_min=?, prossima=? WHERE nome=?",
                               (ogni, min(r["prossima"], adesso + ogni * 60), chiave))

    def ritmo(self):
        r = self.db.uno("SELECT valore FROM kv WHERE chiave='ritmo'")
        return json.loads(r["valore"]) if r else None

    def imposta_ritmo(self, nome):
        """Applica il ritmo scelto alle routine che lavorano da sole, sfalsandone le partenze."""
        if nome not in RITMI:
            raise ValueError("Ritmo sconosciuto.")
        adesso = int(self.adesso())
        for i, chiave in enumerate(("collaudo", "studio", "lettura", "miglioramento")):
            ogni = RITMI[nome][chiave]
            if ogni is None:
                self.db.esegui("UPDATE routine SET attiva=0 WHERE nome=?", (chiave,))
                continue
            attiva = "" if chiave == "miglioramento" else ", attiva=1"  # quella di sistema la accende e spegne l'utente
            self.db.esegui(f"UPDATE routine SET ogni_min=?, prossima=?{attiva} WHERE nome=?",
                           (ogni, adesso + (i + 1) * 120 + min(ogni, 60) * 60, chiave))
        self.db.esegui("INSERT INTO kv (chiave, valore) VALUES ('ritmo', ?) "
                       "ON CONFLICT(chiave) DO UPDATE SET valore=excluded.valore", (json.dumps(nome),))
        self.ada.log("utente", "ritmo di lavoro", nome)

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
        if not (r["nome"] in SILENZIOSE and str(esito)[:300] == r["esito"]):  # girano ogni minuto: si registra solo se cambia qualcosa
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

    def _notifiche(self, manuale):
        from ..revolut.ingest import leggi_e_salva
        from ..revolut.store import apri
        lettore = getattr(self.ada, "lettore_notifiche", None)
        if not lettore:
            return "Non disponibile: Termux:API non trovato su questo telefono."
        db = apri(str(self.ada.soldi.percorso))
        try:
            esito = leggi_e_salva(db, lettore, self.adesso)
        finally:
            db.close()
        if "errore" in esito:
            return f"Errore: lettura notifiche non riuscita: {esito['errore']}"[:250]
        if esito["nuovi"]:
            fatture = self.db.uno("SELECT id FROM routine WHERE nome='fatture' AND attiva=1")
            if fatture:  # subito: così l'avviso di un bonifico arriva in pochi minuti e non al giro successivo
                self.esegui(fatture["id"])
            return f"{esito['nuovi']} nuovi movimenti letti."
        return "Nessuna novità."

    def _agenda(self, manuale):
        ag, adesso = self.ada.agenda, self.adesso()
        avvisati = []
        for v in ag.da_avvisare(adesso):
            titolo = "Promemoria" if v["tipo"] == "promemoria" else "Appuntamento"
            quando = f"{v['ora']} " if v["ora"] else ""
            testo = f"{quando}{v['titolo']}" + (" (in ritardo)" if v.get("in_ritardo") else "")
            if v["preavviso"] and not v.get("in_ritardo"):
                testo = f"tra {v['preavviso']} min: {v['titolo']}" + (f" ({v['ora']})" if v["ora"] else "")
            self.ada.avvisa(titolo, testo[:120], f"ada-agenda-{v['id']}")
            ag.segna_avvisato(v["id"], adesso)
            avvisati.append(v["titolo"])
        return ("Avvisato: " + ", ".join(avvisati))[:250] if avvisati else "Nessun avviso."

    def _agenda_mattina(self, manuale):
        r = self.ada.agenda.riepilogo_mattina()
        if not r:
            return "Niente in agenda oggi."
        self.ada.avvisa(r[0], r[1], "ada-agenda-mattina")
        return f"Avviso del mattino: {r[1]}"[:250]

    def _senza_limite(self, manuale):
        return None if manuale or not self.ada.sopra_limite() else "Saltata: limite di consumo di oggi raggiunto."

    def _collaudo(self, manuale):
        c = getattr(self.ada, "collaudo", None)
        if not c or not self.ada.llm.disponibile:
            return "Saltata: cervello non collegato."
        return self._senza_limite(manuale) or c.esegui()

    def _studio(self, manuale):
        s = getattr(self.ada, "studio", None)
        if not s or not self.ada.llm.disponibile:
            return "Saltata: cervello non collegato."
        return self._senza_limite(manuale) or s.lezione()

    def _lettura(self, manuale):
        s = getattr(self.ada, "studio", None)
        if not s or not self.ada.llm.disponibile:
            return "Saltata: cervello non collegato."
        return self._senza_limite(manuale) or s.lettura()

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
