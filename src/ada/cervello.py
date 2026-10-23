"""Ada: orchestratore. Delega agli assistenti, segue gli errori e migliora i loro prompt.

I confini (soldi, modifiche grandi, deriva dei prompt) sono imposti qui nel codice,
non nei prompt: quello che Ada può riscrivere non include mai queste regole.
"""
import contextlib
import difflib
import json
import os
import re
import threading
import time

from .agenti import AGENTI
from .soldi import NOMI_CATEGORIE
from .llm import ErroreLLM
from .pianificatore import PREDEFINITE, prossima_esecuzione

MAX_PROMPT = 8000
SOGLIA_SIMILARITA = 0.85   # sotto questa, la modifica è "grande"
MAX_AGGIUNTA = 600         # caratteri aggiunti oltre i quali è "grande"
MAX_PICCOLE_24H = 3        # oltre, serve l'ok: argine contro la deriva dei prompt
MAX_ROUTINE = 8            # routine create da Ada
MIN_INTERVALLO = 30        # minuti: argine ai costi
LIMITE_TOKEN = int(os.environ.get("ADA_LIMITE_TOKEN", "400000"))  # tetto giornaliero per i lavori automatici
PENDENTI = "('in_attesa','scelta','autorizzata','pronto')"
MAX_TOKEN = 4096          # spazio per ogni risposta: i prompt interi nelle chiamate agli strumenti sono lunghi
MAX_TOKEN_RIPROVA = 8192  # se una risposta viene tagliata si riprova una volta con più spazio
# «lo faccio adesso» senza aver chiamato nessuno strumento: l'errore da intercettare
PROMESSA = re.compile(r"\b(?:lo|la|li|le)\s+(?:faccio|applico|salvo|scrivo|invio)\s+(?:ora|adesso|subito|partire)\b"
                      r"|\b(?:faccio|applico|procedo|parto)\s+(?:ora|adesso|subito)\b|\badesso\s+(?:lo|la)\s+(?:faccio|applico)\b"
                      r"|\bmi metto al lavoro\b|\b(?:la|lo)\s+faccio\s+partire\b", re.I)
MAX_REGOLE = 80
MAX_IDEE_APERTE = 6
IDEE_APERTE = "('proposta','approvata')"

# Fissato nel codice (non in un prompt che Ada può riscrivere): il capo decide e agisce.
MANDATO = """COME LAVORI: sei il capo e decidi tu. Non chiedere «quale vuoi che faccia partire»: scegli la cosa più utile entro i tuoi poteri, falla, poi riferisci in poche righe cosa hai fatto e perché. Chiedi all'utente solo ciò che solo lui può fare (collegare lo schermo, darti un dato che manca), le decisioni sui soldi e le modifiche grandi. Se vedi un problema o un miglioramento alla portata dei tuoi strumenti (prompt, routine, regole di categoria, segnalazioni), applicalo senza aspettare. Per correggere un prompt usa aggiungi_regola_prompt, una regola breve alla volta: è il modo più semplice e sicuro; migliora_prompt (riscrittura intera) solo se serve davvero. Se una funzione nuova richiede codice, usa proponi_idea: è una proposta che l'utente approva. Se dici che fai qualcosa, chiama subito lo strumento: non promettere e basta. Il tetto di consumo riguarda solo le routine automatiche: non limitare mai per quel motivo il lavoro che ti chiede l'utente. Se una opzione è chiaramente la migliore, non elencarne tre."""

CAPACITA = """CAPACITÀ COLLEGATE OGGI: archivio fatture P.IVA collegato allo script Google (riepilogo_fatture; l'archiviazione dei Word mandati a Giulia la fa già lo script); leggere i movimenti Revolut letti dalle notifiche del telefono (riepilogo_spese; la lettura delle notifiche non dipende dal collegamento dello schermo); vedere cosa aspetta l'utente, le segnalazioni, le routine e i consumi (stato_sistema); delegare agli assistenti; annotare e chiudere segnalazioni; migliorare i prompt; chiedere approvazioni.
NON COLLEGATI COME STRUMENTI: Gmail, Calendario, WhatsApp, documenti e fatture (si possono usare solo attraverso lo schermo del telefono, se è collegato). Non fingere di usarli."""
TELEFONO_SI = "TELEFONO: collegato. Puoi guardare e usare lo schermo con gli strumenti telefono_*. Le app finanziarie sono protette e il tasto finale di acquisto/pagamento lo preme sempre l'utente."
TELEFONO_NO = "TELEFONO: NON collegato (manca il debug wireless, vedi docs/TELEFONO.md). Non puoi usare lo schermo: dillo all'utente se serve."


def _tool(nome, descrizione, proprieta, obbligatori):
    return {"name": nome, "description": descrizione,
            "input_schema": {"type": "object", "properties": proprieta, "required": obbligatori}}


_S = {"type": "string"}
T_RIEPILOGO = _tool("riepilogo_spese", "Riepilogo di entrate, uscite e categorie dai movimenti Revolut.",
                    {"periodo": {"type": "string", "enum": ["mese", "sempre"]}}, [])
T_FATTURE = _tool("riepilogo_fatture", "Riepilogo delle fatture P.IVA del mese (archivio): incassato, da incassare, tasse da accantonare.",
                  {"mese": {"type": "string", "description": "AAAA-MM, default il mese corrente"}}, [])
T_INCASSATA = _tool("fattura_incassata", "Segna una fattura come incassata nell'archivio (usa l'id mostrato da riepilogo_fatture).",
                    {"id": _S, "data": {"type": "string", "description": "AAAA-MM-GG, default oggi"}}, ["id"])
T_REGOLA_PROMPT = _tool("aggiungi_regola_prompt",
                        "Aggiunge UNA regola breve in fondo al prompt di un agente (sezione «Regole imparate»). È il modo più semplice e sicuro di correggerlo: preferiscilo a migliora_prompt, che richiede di riscrivere tutto il prompt.",
                        {"agente": {"type": "string", "enum": list(AGENTI)}, "regola": _S, "motivo": _S},
                        ["agente", "regola", "motivo"])
T_IDEA = _tool("proponi_idea", "Proponi una funzione nuova per l'app che richiede codice. L'utente approva o rifiuta. Una sola idea nuova al giorno.",
               {"titolo": _S, "descrizione": {"type": "string", "description": "Cosa farebbe, come lo vedrebbe l'utente (30-800 caratteri)"},
                "motivo": {"type": "string", "description": "Perché serve, con un fatto osservato"}}, ["titolo", "descrizione", "motivo"])
T_REGOLA = _tool("regola_categoria", "Insegna o toglie una regola: gli esercenti con questa parola vanno in quella categoria di spesa.",
                 {"azione": {"type": "string", "enum": ["aggiungi", "rimuovi"]}, "parola": _S,
                  "categoria": {"type": "string", "enum": NOMI_CATEGORIE}}, ["azione", "parola"])
T_STATO = _tool("stato_sistema", "Cosa aspetta una decisione dell'utente, segnalazioni aperte, routine, ultime attività e consumo di oggi.", {}, [])
T_SEGNALA = _tool("annota_segnalazione", "Annota un problema o una mancanza osservata in un assistente.",
                  {"agente": _S, "problema": _S}, ["agente", "problema"])
T_APPROVAZIONE = _tool("richiedi_approvazione",
                       "Chiede il via libera dell'utente (obbligatorio per ogni pagamento o movimento di denaro). Non esegue nulla.",
                       {"tipo": {"type": "string", "enum": ["pagamento", "altro"]}, "titolo": _S,
                        "dettaglio": _S, "importo": {"type": "number"}}, ["tipo", "titolo", "dettaglio"])
T_DELEGA = _tool("delega", "Affida un compito a un assistente e ne restituisce la risposta.",
                 {"agente": {"type": "string", "enum": [a for a in AGENTI if a != "ada"]}, "compito": _S},
                 ["agente", "compito"])
T_MIGLIORA = _tool("migliora_prompt",
                   "Sostituisce il prompt di un agente con una versione migliore. Le modifiche piccole si applicano subito, quelle grandi chiedono l'ok dell'utente. Passa il prompt completo.",
                   {"agente": {"type": "string", "enum": list(AGENTI)}, "nuovo_prompt": _S, "motivo": _S},
                   ["agente", "nuovo_prompt", "motivo"])
T_CHIUDI = _tool("chiudi_segnalazione", "Chiude una segnalazione dopo averla gestita.",
                 {"id": {"type": "integer"}, "esito": _S}, ["id", "esito"])

_N = {"type": "integer"}
T_SCHERMO = _tool("telefono_schermo", "Guarda lo schermo del telefono: elenco numerato degli elementi visibili.", {}, [])
T_TOCCA = _tool("telefono_tocca", "Tocca un elemento dello schermo (numero preso da telefono_schermo). Restituisce la nuova schermata.",
                {"id": _N}, ["id"])
T_SCRIVI = _tool("telefono_scrivi", "Scrive in un campo di testo (solo caratteri senza accenti).", {"id": _N, "testo": _S}, ["id", "testo"])
T_SCORRI = _tool("telefono_scorri", "Scorre la pagina.", {"direzione": {"type": "string", "enum": ["giu", "su"]}}, ["direzione"])
T_VAI = _tool("telefono_vai", "Tasto indietro o home.", {"azione": {"type": "string", "enum": ["indietro", "home"]}}, ["azione"])
T_APRI = _tool("telefono_apri", "Apre un'app (amazon, chrome, whatsapp, gmail, calendario o nome pacchetto) oppure un indirizzo https.",
               {"app": _S, "url": _S}, [])
T_COLLEGA = _tool("telefono_collega", "Ricollega lo schermo del telefono (cerca da sola la porta del Debug wireless, oppure usa quella indicata dall'utente).",
                  {"porta": _N}, [])
T_PROPONI = _tool("proponi_acquisto",
                  "Mostra all'utente fino a 5 opzioni d'acquisto da confrontare. Usa solo dati letti davvero sullo schermo.",
                  {"richiesta": _S, "opzioni": {"type": "array", "items": {"type": "object", "properties": {
                      "nome": _S, "prezzo_totale": {"type": "number"}, "stelle": {"type": "number"},
                      "recensioni": _N, "venditore": _S, "motivo": _S,
                      "etichetta": {"type": "string", "enum": ["economica", "meglio_recensita", "consigliata", "altra"]}},
                      "required": ["nome", "prezzo_totale"]}}}, ["richiesta", "opzioni"])
T_ROUTINE = _tool("gestisci_routine",
                  "Crea, modifica, attiva o disattiva una tua routine automatica (ogni giorno a un'ora, oppure ogni N minuti, minimo 30). Le routine automatiche non usano mai lo schermo del telefono.",
                  {"azione": {"type": "string", "enum": ["crea", "modifica", "attiva", "disattiva"]}, "nome": _S,
                   "descrizione": _S, "prompt": _S, "ora": _S, "ogni_min": _N}, ["azione", "nome"])
T_PRONTO = _tool("acquisto_pronto", "Segnala che l'ordine è alla schermata finale e ora tocca all'utente premere il tasto.",
                 {"id": _N, "nota": _S}, ["id", "nota"])

STRUMENTI_TELEFONO = [T_COLLEGA, T_SCHERMO, T_TOCCA, T_SCRIVI, T_SCORRI, T_VAI, T_APRI, T_PROPONI, T_PRONTO]
STRUMENTI_ASSISTENTI = [T_RIEPILOGO, T_FATTURE, T_SEGNALA, T_APPROVAZIONE]
STRUMENTI_ACQUISTI = STRUMENTI_ASSISTENTI + STRUMENTI_TELEFONO
STRUMENTI_ADA = STRUMENTI_ASSISTENTI + STRUMENTI_TELEFONO + [T_DELEGA, T_MIGLIORA, T_REGOLA_PROMPT, T_CHIUDI, T_ROUTINE, T_STATO, T_INCASSATA, T_IDEA, T_REGOLA]
GIRI = {"ada": 12, "acquisti": 30}  # il telefono richiede molti passaggi


def strumenti_di(chi):
    return {"ada": STRUMENTI_ADA, "acquisti": STRUMENTI_ACQUISTI}.get(chi, STRUMENTI_ASSISTENTI)


def classifica(vecchio: str, nuovo: str) -> str:
    rapporto = difflib.SequenceMatcher(None, vecchio, nuovo).ratio()
    piccola = rapporto >= SOGLIA_SIMILARITA and len(nuovo) - len(vecchio) <= MAX_AGGIUNTA
    return "piccola" if piccola else "grande"


class Ada:
    def __init__(self, db, squadra, soldi, llm, mano=None, max_giri=6):
        self.db, self.squadra, self.soldi, self.llm, self.mano, self.max_giri = db, squadra, soldi, llm, mano, max_giri
        self.lock = threading.Lock()
        self._azioni_ciclo = []   # cosa ha fatto l'ultimo ciclo di strumenti (mostrato sotto il messaggio)
        self.lavori = {}          # agente -> {"cosa", "da"}: chi sta lavorando adesso e a cosa (per il popup)
        self.automatico = False   # vero durante una routine: niente schermo senza l'utente
        self.notifica = None      # funzione(titolo, testo, id) impostata dal server
        self.archivio = None      # archivio fatture P.IVA (src/ada/fatture.py)
        self.soldi.regole = {r["parola"]: r["categoria"] for r in self.db.tutti("SELECT parola, categoria FROM regole_categoria")}

    # ---------- utilità ----------
    @contextlib.contextmanager
    def _lavora(self, chi, cosa):
        """Segna che `chi` sta lavorando a `cosa`: serve a mostrare l'attività vera, non quella recente."""
        self.lavori[chi] = {"cosa": str(cosa)[:140], "da": int(time.time())}
        try:
            yield
        finally:
            self.lavori.pop(chi, None)

    def avvisa(self, titolo, testo, id_="ada"):
        if self.notifica:
            try:
                self.notifica(titolo, testo, id_)
            except Exception as e:  # la notifica è un extra: non deve rompere il lavoro
                self.log("sistema", "errore notifica", e)

    def _conta(self, risposta):
        """Token pesati come costo: la parte letta dalla cache vale un decimo."""
        u = risposta.get("usage") or {}
        inp = int(u.get("input_tokens") or 0) + int(u.get("cache_creation_input_tokens") or 0) \
            + int((u.get("cache_read_input_tokens") or 0) / 10)
        out = int(u.get("output_tokens") or 0)
        oggi = time.strftime("%Y-%m-%d")
        for chiave in (oggi, "auto:" + oggi) if self.automatico else (oggi,):
            self.db.esegui("INSERT INTO consumi (giorno, input, output, chiamate) VALUES (?,?,?,1) "
                           "ON CONFLICT(giorno) DO UPDATE SET input=input+excluded.input, output=output+excluded.output, "
                           "chiamate=chiamate+1", (chiave, inp, out))

    def _consumo(self, chiave):
        r = self.db.uno("SELECT input, output, chiamate FROM consumi WHERE giorno=?", (chiave,)) \
            or {"input": 0, "output": 0, "chiamate": 0}
        return {**r, "totale": r["input"] + r["output"]}

    def consumo_oggi(self):
        oggi = time.strftime("%Y-%m-%d")
        return {**self._consumo(oggi), "automatici": self._consumo("auto:" + oggi)["totale"], "limite": LIMITE_TOKEN}

    def sopra_limite(self):
        """Il tetto riguarda solo i lavori automatici: la tua chat non lo consuma."""
        return self.consumo_oggi()["automatici"] >= LIMITE_TOKEN

    def log(self, agente, azione, dettaglio=""):
        self.db.esegui("INSERT INTO attivita (ts, agente, azione, dettaglio) VALUES (?,?,?,?)",
                       (int(time.time()), agente, azione, str(dettaglio)[:500]))

    def _contesto(self, chi):
        aperte = self.db.tutti("SELECT id, agente, problema FROM segnalazioni WHERE stato='aperta' ORDER BY id LIMIT 10")
        stabili = [MANDATO if chi == "ada" else "", CAPACITA]  # uguali a ogni richiesta: finiscono in cache
        righe = [f"Oggi è {time.strftime('%Y-%m-%d %H:%M')}.",
                 TELEFONO_SI if self.mano and self.mano.disponibile() else TELEFONO_NO]
        if chi == "ada":
            routine = self.db.tutti("SELECT nome, ora, ogni_min, attiva FROM routine ORDER BY id")
            if routine:
                righe.append("ROUTINE: " + "; ".join(
                    f"{x['nome']} ({'ogni giorno alle ' + x['ora'] if x['ora'] else 'ogni ' + str(x['ogni_min']) + ' min'}"
                    f"{'' if x['attiva'] else ', disattivata'})" for x in routine))
            righe.append("TEAM: " + "; ".join(f"{k} ({v[1]})" for k, v in AGENTI.items() if k != "ada"))
            if aperte:
                righe.append("SEGNALAZIONI APERTE: " + " | ".join(f"#{s['id']} {s['agente']}: {s['problema']}" for s in aperte))
        return "\n".join(x for x in stabili if x), "\n".join(righe)

    # ---------- ciclo con strumenti ----------
    def _ciclo(self, chi, messaggi, strumenti):
        azioni = []
        try:
            return self._ciclo_base(chi, messaggi, strumenti, azioni)
        finally:
            self._azioni_ciclo = azioni  # per mostrarle sotto la risposta (le chiamate annidate finiscono prima)

    def _ciclo_base(self, chi, messaggi, strumenti, azioni):
        system = self.squadra.system(chi, *self._contesto(chi))
        testo, spinte, spazio = "", 0, MAX_TOKEN
        for _ in range(GIRI.get(chi, self.max_giri)):
            r = self.llm(system, messaggi, strumenti, max_tokens=spazio)
            self._conta(r)
            blocchi = r.get("content", [])
            testo = "".join(b.get("text", "") for b in blocchi if b.get("type") == "text").strip()
            fine = r.get("stop_reason")
            if fine == "max_tokens":
                # la risposta (spesso un prompt intero dentro la chiamata a uno strumento) è stata tagliata
                if spazio < MAX_TOKEN_RIPROVA:
                    spazio = MAX_TOKEN_RIPROVA
                    self.log(chi, "errore", "risposta troppo lunga: riprovo con più spazio")
                    continue
                self.log(chi, "errore", "risposta troppo lunga anche con più spazio")
                return ((testo + "\n\n") if testo else "") + (
                    "La mia risposta si è interrotta perché troppo lunga e non ho potuto completare l'azione: "
                    "riprovo con una modifica più piccola se me lo chiedi.")
            if fine != "tool_use":
                if strumenti and spinte < 1 and PROMESSA.search(testo):
                    spinte += 1  # ha promesso di agire senza farlo: la si rimanda a farlo, una volta sola
                    messaggi.append({"role": "assistant", "content": blocchi})
                    messaggi.append({"role": "user", "content": "Hai scritto che lo fai adesso ma non hai chiamato nessuno "
                                     "strumento. Chiamalo ora; se non puoi farlo, dillo chiaramente senza promettere."})
                    continue
                return testo or self._riassunto(azioni)
            messaggi.append({"role": "assistant", "content": blocchi})
            esiti = []
            for b in blocchi:
                if b.get("type") == "tool_use":
                    esito = self._esegui(chi, b["name"], b.get("input") or {})
                    azioni.append({"nome": b["name"], "esito": str(esito)[:140]})
                    esiti.append({"type": "tool_result", "tool_use_id": b["id"], "content": esito})
            messaggi.append({"role": "user", "content": esiti})
        return testo or self._riassunto(azioni, limite=True)

    @staticmethod
    def _riassunto(azioni, limite=False):
        """Una risposta non è mai vuota: se manca il testo si racconta cosa è stato fatto."""
        if azioni:
            return "Ho eseguito: " + "; ".join(f"{a['nome']}: {a['esito'][:80]}" for a in azioni[-4:])
        return "Ho raggiunto il limite di passaggi per questa richiesta." if limite else "Ho finito, ma non ho nulla da riferire."

    def _esegui(self, chi, nome, args):
        if nome not in [t["name"] for t in strumenti_di(chi)]:
            return "Strumento non consentito."
        if chi in self.lavori:
            self.lavori[chi]["passo"] = nome  # si vede dal popup e dalla chat cosa sta usando
        try:
            if nome == "riepilogo_spese":
                return self.soldi.testo(args.get("periodo", "mese"))
            if nome == "annota_segnalazione":
                return self.segnala(args["agente"], args["problema"], f"agente:{chi}")
            if nome == "richiedi_approvazione":
                return self._richiedi(chi, args)
            if nome == "delega":
                return self._delega(args["agente"], args["compito"])
            if nome == "migliora_prompt":
                return self._migliora(args["agente"], args["nuovo_prompt"], args["motivo"])
            if nome == "aggiungi_regola_prompt":
                return self._aggiungi_regola(args["agente"], args["regola"], args["motivo"])
            if nome.startswith("telefono_"):
                return self._telefono(nome, args)
            if nome == "proponi_acquisto":
                return self._proponi_acquisto(chi, args)
            if nome == "acquisto_pronto":
                return self._pronto(int(args["id"]), str(args.get("nota", ""))[:300])
            if nome == "gestisci_routine":
                return self._routine(args)
            if nome == "stato_sistema":
                return self._stato_sistema()
            if nome == "proponi_idea":
                return self._proponi_idea(args)
            if nome == "regola_categoria":
                return self._regola_categoria(args)
            if nome == "riepilogo_fatture":
                return self.archivio.testo(args.get("mese")) if self.archivio else "Archivio fatture non configurato."
            if nome == "fattura_incassata":
                if not self.archivio:
                    return "Archivio fatture non configurato."
                return self.archivio.segna_incassata(args["id"], args.get("data"), da=chi)
            if nome == "chiudi_segnalazione":
                self.db.esegui("UPDATE segnalazioni SET stato='chiusa', esito=? WHERE id=?",
                               (str(args["esito"])[:300], int(args["id"])))
                return "Segnalazione chiusa."
        except Exception as e:  # lo strumento fallito non deve far cadere la conversazione
            self.log(chi, "errore", f"{nome}: {type(e).__name__} {e}")
            return f"Errore nello strumento {nome}: {e}"
        return "Strumento sconosciuto."

    # ---------- segnalazioni e approvazioni ----------
    def segnala(self, agente, problema, fonte):
        if agente not in AGENTI:
            return "Agente sconosciuto."
        self.db.esegui("INSERT INTO segnalazioni (ts, agente, problema, fonte) VALUES (?,?,?,?)",
                       (int(time.time()), agente, str(problema)[:500], fonte))
        self.log(agente, "segnalazione", problema)
        return "Segnalazione annotata."

    def _richiedi(self, chi, args):
        dettaglio = json.dumps({"testo": args["dettaglio"], "importo": args.get("importo"), "richiesto_da": chi},
                               ensure_ascii=False)
        cur = self.db.esegui("INSERT INTO approvazioni (ts, tipo, titolo, dettaglio) VALUES (?,?,?,?)",
                             (int(time.time()), args["tipo"], str(args["titolo"])[:200], dettaglio))
        self.log(chi, "richiesta approvazione", args["titolo"])
        self._avvisa_attesa()
        return f"Richiesta #{cur.lastrowid} registrata: in attesa del via libera dell'utente. Non è stato eseguito nulla."

    def risolvi(self, id_, esito, opzione=None):
        a = self.db.uno("SELECT * FROM approvazioni WHERE id=? AND stato='in_attesa'", (id_,))
        if not a:
            raise ValueError("Approvazione non trovata o già risolta.")
        ok = esito == "approva"
        if a["tipo"] == "acquisto" and ok:
            return self._scegli(a, opzione)
        self.db.esegui("UPDATE approvazioni SET stato=?, risolta_ts=? WHERE id=?",
                       ("approvata" if ok else "rifiutata", int(time.time()), id_))
        if a["tipo"] == "prompt":
            mid = json.loads(a["dettaglio"])["miglioramento_id"]
            if ok:
                self._applica(mid)
            else:
                self.db.esegui("UPDATE miglioramenti SET stato='rifiutato' WHERE id=?", (mid,))
        elif a["tipo"] == "idea":
            idea_id = json.loads(a["dettaglio"])["idea_id"]
            self.db.esegui("UPDATE idee SET stato=?, ts_stato=? WHERE id=?",
                           ("approvata" if ok else "rifiutata", int(time.time()), idea_id))
        elif a["tipo"] == "incasso":
            if ok and self.archivio:
                self.archivio.segna_incassata(json.loads(a["dettaglio"])["fattura_id"], da="utente")
        elif a["tipo"] == "pagamento":
            # Nessun pagamento parte da qui: si registra l'ok e il pagamento resta a mano.
            self.log("ada", "pagamento approvato", f"{a['titolo']} (da eseguire a mano: Ada non muove denaro)")
        self.log("utente", "approvata" if ok else "rifiutata", a["titolo"])
        return self.db.uno("SELECT * FROM approvazioni WHERE id=?", (id_,))

    # ---------- acquisti: scelta, autorizzazione, pronto, chiuso ----------
    def _avvisa_attesa(self):
        n = self.db.uno(f"SELECT COUNT(*) AS n FROM approvazioni WHERE stato IN {PENDENTI}")["n"]
        self.avvisa("Ada ha bisogno di te", f"{n} {'cosa aspetta' if n == 1 else 'cose aspettano'} la tua decisione.",
                    "ada-attesa")

    def _proponi_acquisto(self, chi, args):
        opzioni = args.get("opzioni")
        if not isinstance(opzioni, list) or not 1 <= len(opzioni) <= 5:
            return "Servono da 1 a 5 opzioni."
        pulite = []
        for o in opzioni:
            if not str(o.get("nome", "")).strip() or not isinstance(o.get("prezzo_totale"), (int, float)) or o["prezzo_totale"] < 0:
                return "Ogni opzione richiede nome e prezzo_totale reale."
            pulite.append({"nome": str(o["nome"])[:160], "prezzo_totale": round(float(o["prezzo_totale"]), 2),
                           "stelle": o.get("stelle"), "recensioni": o.get("recensioni"),
                           "venditore": str(o.get("venditore", ""))[:80], "motivo": str(o.get("motivo", ""))[:200],
                           "etichetta": o.get("etichetta", "altra")})
        det = json.dumps({"richiesta": str(args.get("richiesta", ""))[:200], "opzioni": pulite, "scelta": None,
                          "richiesto_da": chi}, ensure_ascii=False)
        cur = self.db.esegui("INSERT INTO approvazioni (ts, tipo, titolo, dettaglio) VALUES (?,?,?,?)",
                             (int(time.time()), "acquisto", str(args.get("richiesta", "Acquisto"))[:200], det))
        self.log(chi, "proposta acquisto", args.get("richiesta", ""))
        self._avvisa_attesa()
        return (f"Proposta #{cur.lastrowid} mostrata all'utente. Non toccare carrello o cassa: "
                "aspetta che scelga un'opzione e ti autorizzi.")

    def _scegli(self, a, opzione):
        det = json.loads(a["dettaglio"])
        if not isinstance(opzione, int) or not 0 <= opzione < len(det["opzioni"]):
            raise ValueError("Scegli una delle opzioni proposte.")
        det["scelta"] = opzione
        self.db.esegui("UPDATE approvazioni SET stato='scelta', dettaglio=?, risolta_ts=? WHERE id=?",
                       (json.dumps(det, ensure_ascii=False), int(time.time()), a["id"]))
        self.log("utente", "scelta opzione", det["opzioni"][opzione]["nome"])
        return self.db.uno("SELECT * FROM approvazioni WHERE id=?", (a["id"],))

    def autorizza(self, id_):
        """L'utente autorizza Ada a portare l'ordine alla schermata finale. Il tasto finale resta suo."""
        a = self.db.uno("SELECT * FROM approvazioni WHERE id=? AND tipo='acquisto' AND stato='scelta'", (id_,))
        if not a:
            raise ValueError("Prima scegli un'opzione.")
        self.db.esegui("UPDATE approvazioni SET stato='autorizzata', risolta_ts=? WHERE id=?", (int(time.time()), id_))
        self.log("utente", "acquisto autorizzato", a["titolo"])
        return self.db.uno("SELECT * FROM approvazioni WHERE id=?", (id_,))

    def autorizzazione_attiva(self) -> bool:
        return self.db.uno("SELECT 1 AS x FROM approvazioni WHERE tipo='acquisto' AND stato='autorizzata' "
                           "AND risolta_ts>?", (int(time.time()) - 1800,)) is not None

    def prepara_acquisto(self, id_):
        a = self.db.uno("SELECT * FROM approvazioni WHERE id=? AND stato='autorizzata'", (id_,))
        if not a:
            return
        det = json.loads(a["dettaglio"])
        o = det["opzioni"][det["scelta"]]
        compito = (f"L'utente ha scelto «{o['nome']}» ({o['prezzo_totale']:.2f} €, venditore {o['venditore'] or 'non indicato'}) "
                   f"per la richiesta «{det['richiesta']}» e ti ha autorizzato a portare l'ordine alla schermata finale. "
                   f"Apri il prodotto, aggiungilo al carrello, procedi fino alla schermata finale, controlla prezzo totale, "
                   f"indirizzo e pagamento, poi FERMATI senza toccare il tasto finale e chiama acquisto_pronto con id {id_}.")
        with self.lock:
            risposta = self._delega("acquisti", compito)
            self.db.esegui("INSERT INTO chat (ts, ruolo, testo) VALUES (?,?,?)",
                           (int(time.time()), "ada", f"Acquisto «{o['nome']}»: {risposta}"))

    def _pronto(self, id_, nota):
        a = self.db.uno("SELECT * FROM approvazioni WHERE id=? AND stato='autorizzata'", (id_,))
        if not a:
            return "Acquisto non autorizzato o già pronto."
        det = json.loads(a["dettaglio"])
        det["nota"] = nota
        self.db.esegui("UPDATE approvazioni SET stato='pronto', dettaglio=? WHERE id=?",
                       (json.dumps(det, ensure_ascii=False), id_))
        self.log("acquisti", "ordine pronto", "aspetta l'utente per il tasto finale")
        self.avvisa("Ordine pronto", "Apri il telefono: il tasto finale lo premi tu.", "ada-ordine")
        return "Registrato: ora tocca all'utente premere il tasto finale. Non toccare nient'altro."

    def chiudi_acquisto(self, id_, esito):
        a = self.db.uno("SELECT * FROM approvazioni WHERE id=? AND tipo='acquisto' "
                        "AND stato IN ('scelta','autorizzata','pronto')", (id_,))
        if not a or esito not in ("comprato", "annullato"):
            raise ValueError("Acquisto non trovato o esito non valido.")
        self.db.esegui("UPDATE approvazioni SET stato=?, risolta_ts=? WHERE id=?",
                       ("chiusa" if esito == "comprato" else "annullata", int(time.time()), id_))
        self.log("utente", f"acquisto {esito}", a["titolo"])

    def _telefono(self, nome, args):
        if self.automatico:
            return "Routine automatica: non uso lo schermo senza che l'utente sia presente."
        if not self.mano:
            return TELEFONO_NO
        m = self.mano
        if nome == "telefono_collega":
            return m.collega(args.get("porta"))
        if nome == "telefono_schermo":
            return m.guarda()
        if nome == "telefono_tocca":
            return m.tocca(args["id"])
        if nome == "telefono_scrivi":
            return m.scrivi(args["id"], args["testo"])
        if nome == "telefono_scorri":
            return m.scorri(args["direzione"])
        if nome == "telefono_vai":
            return m.vai(args["azione"])
        if nome == "telefono_apri":
            return m.apri(args.get("app", ""), args.get("url", ""))
        return "Strumento sconosciuto."

    # ---------- miglioramento dei prompt ----------
    def _migliora(self, agente, nuovo, motivo):
        if agente not in AGENTI:
            return "Agente sconosciuto."
        nuovo = (nuovo or "").strip()
        if not 40 <= len(nuovo) <= MAX_PROMPT:
            return f"Prompt rifiutato: deve avere tra 40 e {MAX_PROMPT} caratteri."
        vecchio = self.squadra.prompt(agente).strip()
        if nuovo == vecchio:
            return "Nessuna differenza dal prompt attuale."
        tipo = classifica(vecchio, nuovo)
        recenti = self.db.uno("SELECT COUNT(*) AS n FROM miglioramenti WHERE agente=? AND tipo='piccola' "
                              "AND stato='applicato' AND ts>?", (agente, int(time.time()) - 86400))["n"]
        if tipo == "piccola" and recenti >= MAX_PICCOLE_24H:
            tipo = "grande"
        cur = self.db.esegui("INSERT INTO miglioramenti (ts, agente, motivo, vecchio, nuovo, tipo, stato) "
                             "VALUES (?,?,?,?,?,?,'in_attesa')",
                             (int(time.time()), agente, str(motivo)[:400], vecchio, nuovo, tipo))
        mid = cur.lastrowid
        if tipo == "piccola":
            self._applica(mid)
            return f"Modifica piccola applicata subito (#{mid})."
        det = json.dumps({"miglioramento_id": mid, "agente": agente, "motivo": motivo}, ensure_ascii=False)
        cur = self.db.esegui("INSERT INTO approvazioni (ts, tipo, titolo, dettaglio) VALUES (?,?,?,?)",
                             (int(time.time()), "prompt", f"Modifica grande al prompt di {AGENTI[agente][0]}", det))
        self.db.esegui("UPDATE miglioramenti SET approvazione_id=? WHERE id=?", (cur.lastrowid, mid))
        self.log("ada", "proposta modifica grande", f"{agente}: {motivo}")
        self._avvisa_attesa()
        return f"Modifica grande (#{mid}): non applicata, serve l'ok dell'utente (richiesta #{cur.lastrowid})."

    def _aggiungi_regola(self, agente, regola, motivo):
        """Una regola breve in fondo al prompt: cambio piccolo, senza riscrivere tutto."""
        if agente not in AGENTI:
            return "Agente sconosciuto."
        regola = " ".join(str(regola).split())
        if not 15 <= len(regola) <= 300:
            return "La regola deve avere tra 15 e 300 caratteri."
        vecchio = self.squadra.prompt(agente).rstrip()
        if regola in vecchio:
            return "Questa regola c'è già."
        titolo = "## Regole imparate"
        if titolo in vecchio:
            i = vecchio.index(titolo)
            j = vecchio.find("\n## ", i + len(titolo))
            nuovo = vecchio + f"\n- {regola}" if j == -1 else vecchio[:j].rstrip() + f"\n- {regola}" + vecchio[j:]
        else:
            nuovo = vecchio + f"\n\n{titolo}\n- {regola}"
        return self._migliora(agente, nuovo, motivo)

    def _applica(self, mid):
        m = self.db.uno("SELECT * FROM miglioramenti WHERE id=?", (mid,))
        self.squadra.scrivi(m["agente"], m["nuovo"])
        self.db.esegui("UPDATE miglioramenti SET stato='applicato' WHERE id=?", (mid,))
        self.log("ada", "prompt migliorato", f"{m['agente']} ({m['tipo']}): {m['motivo']}")

    def annulla(self, mid):
        m = self.db.uno("SELECT * FROM miglioramenti WHERE id=? AND stato='applicato'", (mid,))
        if not m:
            raise ValueError("Miglioramento non trovato o non applicato.")
        self.squadra.scrivi(m["agente"], m["vecchio"])
        self.db.esegui("UPDATE miglioramenti SET stato='annullato' WHERE id=?", (mid,))
        self.log("utente", "miglioramento annullato", f"{m['agente']} #{mid}")

    # ---------- assistenti ----------
    def _delega(self, agente, compito):
        if agente not in AGENTI or agente == "ada":
            return "Agente sconosciuto."
        self.log(agente, "lavoro", compito)
        try:
            with self._lavora(agente, compito):
                risposta = self._ciclo(agente, [{"role": "user", "content": compito}], strumenti_di(agente))
        except ErroreLLM as e:
            self.log(agente, "errore", e)
            return f"L'assistente non ha risposto: {e}"
        self.log(agente, "risposta", risposta)
        return risposta

    # ---------- conversazione ----------
    def _storia(self):
        righe = self.db.tutti("SELECT ruolo, testo FROM chat ORDER BY id DESC LIMIT 12")[::-1]
        msgs = []
        for i, r in enumerate(righe):
            t = r["testo"]
            if i < len(righe) - 2 and len(t) > 500:  # i messaggi vecchi e lunghi si accorciano: costano ogni volta
                t = t[:500] + "…"
            ruolo = "user" if r["ruolo"] == "utente" else "assistant"
            if msgs and msgs[-1]["role"] == ruolo:
                msgs[-1]["content"] += "\n" + t
            elif msgs or ruolo == "user":
                msgs.append({"role": ruolo, "content": t})
        return msgs

    def _dici(self, testo, azioni=None):
        """Un messaggio di Ada in chat, con sotto le azioni che ha compiuto per arrivarci."""
        self.db.esegui("INSERT INTO chat (ts, ruolo, testo, azioni) VALUES (?,?,?,?)",
                       (int(time.time()), "ada", testo, json.dumps(azioni, ensure_ascii=False) if azioni else None))

    def _senza_cervello(self, testo):
        base = ("Sono Ada, ma il mio cervello non è ancora collegato: manca la chiave ANTHROPIC_API_KEY "
                "(vedi docs/AVVIO.md). Intanto l'hub funziona e i dati sono qui.")
        if "spes" in testo.lower() or "sold" in testo.lower():
            return base + "\n\n" + self.soldi.testo()
        return base

    def chiacchiera(self, testo):
        testo = (testo or "").strip()[:4000]
        if not testo:
            raise ValueError("Messaggio vuoto.")
        with self.lock:
            self.db.esegui("INSERT INTO chat (ts, ruolo, testo) VALUES (?,?,?)", (int(time.time()), "utente", testo))
            azioni = []
            if not self.llm.disponibile:
                risposta = self._senza_cervello(testo)
            else:
                try:
                    with self._lavora("ada", "Sto rispondendo alla tua chat"):
                        risposta = self._ciclo("ada", self._storia(), STRUMENTI_ADA) or "…"
                    azioni = self._azioni_ciclo
                except ErroreLLM as e:
                    self.log("ada", "errore", e)
                    risposta = f"Non riesco a collegarmi al mio cervello in questo momento ({str(e)[:160]}). Riprova tra poco."
            self._dici(risposta, azioni)
        return risposta

    def ciclo_miglioramento(self, automatico=False):
        aperte = self.db.tutti("SELECT * FROM segnalazioni WHERE stato='aperta' ORDER BY id")
        if not aperte:
            return "Nessuna segnalazione aperta: per ora non c'è niente da migliorare."
        if not self.llm.disponibile:
            return "Per il ciclo di miglioramento serve il cervello collegato (ANTHROPIC_API_KEY)."
        elenco = "\n".join(f"#{s['id']} [{s['agente']}] ({s['fonte']}): {s['problema']}" for s in aperte)
        richiesta = ("Ciclo di miglioramento. Segnalazioni aperte:\n" + elenco +
                     "\nPer ognuna valuta se la causa è nel prompt dell'agente. Se sì, usa migliora_prompt (prompt completo). "
                     "Poi chiudi la segnalazione con chiudi_segnalazione e riassumi cosa hai fatto in poche righe.")
        with self.lock:
            self.automatico = automatico
            try:
                with self._lavora("ada", "Rivedo le segnalazioni e miglioro i prompt"):
                    risposta = self._ciclo("ada", [{"role": "user", "content": richiesta}], STRUMENTI_ADA)
            except ErroreLLM as e:
                self.log("ada", "errore", e)
                return f"Ciclo interrotto: {str(e)[:160]}"
            finally:
                self.automatico = False
            self._dici("Ciclo di miglioramento:\n" + risposta, self._azioni_ciclo)
        return risposta

    # ---------- lavoro automatico ----------
    def lavoro_proattivo(self, prompt, nome):
        """Esegue una routine: Ada lavora da sola, senza schermo, e lascia il risultato in chat."""
        if not self.llm.disponibile:
            return "Saltata: cervello non collegato."
        with self.lock:
            self.automatico = True
            try:
                with self._lavora("ada", f"Routine: {nome.replace('_', ' ')}"):
                    risposta = self._ciclo("ada", [{"role": "user", "content": f"[ROUTINE AUTOMATICA {nome}] {prompt}"}],
                                           STRUMENTI_ADA)
            except ErroreLLM as e:
                self.log("ada", "errore", e)
                return f"Errore: {str(e)[:150]}"
            finally:
                self.automatico = False
            if risposta:
                titolo = nome.replace("_", " ").capitalize()
                self._dici(f"{titolo}:\n{risposta}", self._azioni_ciclo)
        if risposta:
            self.avvisa("Ada", f"{nome.replace('_', ' ').capitalize()}: pronto, aprila per leggerlo.", "ada-routine")
        return risposta[:300] or "Nessun risultato."

    def _stato_sistema(self):
        ora = int(time.time())
        att = self.db.tutti(f"SELECT tipo, titolo, stato, ts FROM approvazioni WHERE stato IN {PENDENTI} ORDER BY id")
        seg = self.db.tutti("SELECT id, agente, problema FROM segnalazioni WHERE stato='aperta' ORDER BY id")
        rou = self.db.tutti("SELECT nome, attiva, ultima, esito FROM routine ORDER BY id")
        c = self.consumo_oggi()
        righe = [f"IN ATTESA DELL'UTENTE: {len(att)}"] + [
            f"- [{a['tipo']}/{a['stato']}] {a['titolo']} (da {max(0, (ora - a['ts']) // 60)} min)" for a in att]
        righe += [f"SEGNALAZIONI APERTE: {len(seg)}"] + [f"- #{s['id']} {s['agente']}: {s['problema']}" for s in seg]
        righe += ["ROUTINE:"] + [f"- {r['nome']} ({'attiva' if r['attiva'] else 'spenta'}), ultima: {r['esito'] or 'mai eseguita'}"
                                 for r in rou]
        idee = self.db.tutti(f"SELECT titolo, stato FROM idee WHERE ts>? OR stato IN {IDEE_APERTE} ORDER BY id DESC LIMIT 12",
                             (ora - 30 * 86400,))
        righe += ["IDEE (ultimi 30 giorni e aperte):"] + [f"- {i['titolo']} [{i['stato']}]" for i in idee]
        attivita = self.db.tutti("SELECT ts, agente, azione, dettaglio FROM attivita ORDER BY id DESC LIMIT 15")
        righe += ["ATTIVITÀ RECENTI (errori compresi):"] + [
            f"- {time.strftime('%d/%m %H:%M', time.localtime(a['ts']))} {a['agente']}: {a['azione']} {a['dettaglio'] or ''}"[:140]
            for a in attivita]
        righe.append(f"CONSUMO OGGI: {c['totale']} token in totale (la chat con l'utente non ha tetto e non va mai limitata); "
                     f"lavori automatici {c['automatici']} su un tetto di {c['limite']}")
        return "\n".join(righe)

    def _proponi_idea(self, args):
        titolo, desc, motivo = (str(args.get(k, "")).strip() for k in ("titolo", "descrizione", "motivo"))
        if not 8 <= len(titolo) <= 100 or not 30 <= len(desc) <= 800 or len(motivo) < 10:
            return "Servono titolo (8-100 caratteri), descrizione (30-800) e un motivo concreto."
        ora = int(time.time())
        lt = time.localtime(ora)
        inizio_giorno = int(time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1)))
        oggi = self.db.uno("SELECT titolo FROM idee WHERE ts>=?", (inizio_giorno,))
        if oggi:
            return f"Una idea nuova al giorno: oggi hai già proposto «{oggi['titolo']}»."
        if self.db.uno(f"SELECT COUNT(*) AS n FROM idee WHERE stato IN {IDEE_APERTE}")["n"] >= MAX_IDEE_APERTE:
            return "Ci sono già troppe idee aperte: aspetta che l'utente ne chiuda qualcuna."
        for i in self.db.tutti("SELECT titolo FROM idee WHERE ts>?", (ora - 60 * 86400,)):
            if difflib.SequenceMatcher(None, i["titolo"].lower(), titolo.lower()).ratio() > 0.8:
                return f"Idea già proposta: «{i['titolo']}»."
        cur = self.db.esegui("INSERT INTO idee (ts, titolo, descrizione, motivo, ts_stato) VALUES (?,?,?,?,?)",
                             (ora, titolo, desc, motivo[:300], ora))
        det = json.dumps({"idea_id": cur.lastrowid, "testo": desc, "motivo": motivo[:300]}, ensure_ascii=False)
        ap = self.db.esegui("INSERT INTO approvazioni (ts, tipo, titolo, dettaglio) VALUES (?,?,?,?)",
                            (ora, "idea", f"Idea: {titolo}", det))
        self.db.esegui("UPDATE idee SET approvazione_id=? WHERE id=?", (ap.lastrowid, cur.lastrowid))
        self.log("ada", "idea proposta", titolo)
        self._avvisa_attesa()
        return f"Idea #{cur.lastrowid} proposta all'utente."

    def idea_fatta(self, id_):
        r = self.db.uno("SELECT titolo FROM idee WHERE id=? AND stato='approvata'", (id_,))
        if not r:
            raise ValueError("Idea non trovata o non approvata.")
        self.db.esegui("UPDATE idee SET stato='fatta', ts_stato=? WHERE id=?", (int(time.time()), id_))
        self.log("utente", "idea realizzata", r["titolo"])

    def _regola_categoria(self, args):
        parola = str(args.get("parola", "")).strip().lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9 .&'-]{2,39}", parola):
            return "Parola non valida (3-40 caratteri: lettere, numeri, spazi)."
        if args.get("azione") == "rimuovi":
            self.db.esegui("DELETE FROM regole_categoria WHERE parola=?", (parola,))
            self.soldi.regole.pop(parola, None)
            self.log("ada", "regola categoria rimossa", parola)
            return f"Regola «{parola}» rimossa."
        cat = args.get("categoria")
        if cat not in NOMI_CATEGORIE:
            return "Categoria non valida."
        if parola not in self.soldi.regole and len(self.soldi.regole) >= MAX_REGOLE:
            return f"Massimo {MAX_REGOLE} regole."
        self.db.esegui("INSERT INTO regole_categoria (parola, categoria) VALUES (?,?) "
                       "ON CONFLICT(parola) DO UPDATE SET categoria=excluded.categoria", (parola, cat))
        self.soldi.regole[parola] = cat
        self.log("ada", "regola categoria", f"{parola} → {cat}")
        return f"D'ora in poi «{parola}» va in {cat}."

    def _routine(self, args):
        azione = args.get("azione")
        nome = re.sub(r"[^a-z0-9_]", "", str(args.get("nome", "")).lower())[:40]
        if not nome:
            return "Serve un nome (lettere minuscole, numeri e _)."
        r = self.db.uno("SELECT * FROM routine WHERE nome=?", (nome,))
        if azione in ("attiva", "disattiva"):
            if not r:
                return "Routine inesistente."
            self.db.esegui("UPDATE routine SET attiva=? WHERE nome=?", (1 if azione == "attiva" else 0, nome))
            self.log("ada", f"routine {azione}ta", nome)
            return f"Routine {nome} {'attivata' if azione == 'attiva' else 'disattivata'}."
        if azione not in ("crea", "modifica"):
            return "Azione sconosciuta."
        if azione == "modifica" and (not r or r["tipo"] != "ada"):
            return "Si possono modificare solo le routine create da Ada; quelle di sistema solo attivare o disattivare."
        if azione == "crea" and r:
            return "Esiste già una routine con questo nome: usa modifica."
        prompt, ora, ogni = str(args.get("prompt", "")).strip()[:1500], args.get("ora"), args.get("ogni_min")
        if len(prompt) < 20:
            return "Serve un prompt di almeno 20 caratteri."
        if bool(ora) == bool(ogni):
            return "Indica solo uno tra ora (HH:MM, ogni giorno) e ogni_min (ogni N minuti)."
        if ora and not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", str(ora)):
            return "Ora non valida: usa HH:MM."
        if ogni and (not isinstance(ogni, int) or ogni < MIN_INTERVALLO):
            return f"Intervallo minimo: {MIN_INTERVALLO} minuti."
        di_sistema = [r["nome"] for r in PREDEFINITE]
        if azione == "crea" and self.db.uno(
                f"SELECT COUNT(*) AS n FROM routine WHERE tipo='ada' AND nome NOT IN ({','.join('?' * len(di_sistema))})",
                di_sistema)["n"] >= MAX_ROUTINE:
            return f"Massimo {MAX_ROUTINE} routine create da te: disattivane una."
        prossima = prossima_esecuzione(ora, ogni, time.time())
        if azione == "crea":
            self.db.esegui("INSERT INTO routine (nome, descrizione, tipo, ora, ogni_min, prompt, prossima) "
                           "VALUES (?,?,?,?,?,?,?)", (nome, str(args.get("descrizione", ""))[:160], "ada",
                                                      ora or None, ogni or None, prompt, prossima))
        else:
            self.db.esegui("UPDATE routine SET descrizione=?, ora=?, ogni_min=?, prompt=?, prossima=? WHERE nome=?",
                           (str(args.get("descrizione", r["descrizione"]))[:160], ora or None, ogni or None, prompt,
                            prossima, nome))
        self.log("ada", f"routine {'creata' if azione == 'crea' else 'modificata'}", nome)
        return f"Routine {nome} {'creata' if azione == 'crea' else 'modificata'}."
