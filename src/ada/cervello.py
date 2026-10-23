"""Ada: orchestratore. Delega agli assistenti, segue gli errori e migliora i loro prompt.

I confini (soldi, modifiche grandi, deriva dei prompt) sono imposti qui nel codice,
non nei prompt: quello che Ada può riscrivere non include mai queste regole.
"""
import difflib
import json
import threading
import time

from .agenti import AGENTI
from .llm import ErroreLLM

MAX_PROMPT = 8000
SOGLIA_SIMILARITA = 0.85   # sotto questa, la modifica è "grande"
MAX_AGGIUNTA = 600         # caratteri aggiunti oltre i quali è "grande"
MAX_PICCOLE_24H = 3        # oltre, serve l'ok: argine contro la deriva dei prompt

CAPACITA = """CAPACITÀ COLLEGATE OGGI: leggere i movimenti Revolut letti dalle notifiche del telefono (riepilogo_spese); delegare agli assistenti; annotare e chiudere segnalazioni; migliorare i prompt; chiedere approvazioni.
NON COLLEGATI COME STRUMENTI: Gmail, Calendario, WhatsApp, documenti e fatture (si possono usare solo attraverso lo schermo del telefono, se è collegato). Non fingere di usarli."""
TELEFONO_SI = "TELEFONO: collegato. Puoi guardare e usare lo schermo con gli strumenti telefono_*. Le app finanziarie sono protette e il tasto finale di acquisto/pagamento lo preme sempre l'utente."
TELEFONO_NO = "TELEFONO: NON collegato (manca il debug wireless, vedi docs/TELEFONO.md). Non puoi usare lo schermo: dillo all'utente se serve."


def _tool(nome, descrizione, proprieta, obbligatori):
    return {"name": nome, "description": descrizione,
            "input_schema": {"type": "object", "properties": proprieta, "required": obbligatori}}


_S = {"type": "string"}
T_RIEPILOGO = _tool("riepilogo_spese", "Riepilogo di entrate, uscite e categorie dai movimenti Revolut.",
                    {"periodo": {"type": "string", "enum": ["mese", "sempre"]}}, [])
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
T_PRONTO = _tool("acquisto_pronto", "Segnala che l'ordine è alla schermata finale e ora tocca all'utente premere il tasto.",
                 {"id": _N, "nota": _S}, ["id", "nota"])

STRUMENTI_TELEFONO = [T_COLLEGA, T_SCHERMO, T_TOCCA, T_SCRIVI, T_SCORRI, T_VAI, T_APRI, T_PROPONI, T_PRONTO]
STRUMENTI_ASSISTENTI = [T_RIEPILOGO, T_SEGNALA, T_APPROVAZIONE]
STRUMENTI_ACQUISTI = STRUMENTI_ASSISTENTI + STRUMENTI_TELEFONO
STRUMENTI_ADA = STRUMENTI_ASSISTENTI + STRUMENTI_TELEFONO + [T_DELEGA, T_MIGLIORA, T_CHIUDI]
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

    # ---------- utilità ----------
    def log(self, agente, azione, dettaglio=""):
        self.db.esegui("INSERT INTO attivita (ts, agente, azione, dettaglio) VALUES (?,?,?,?)",
                       (int(time.time()), agente, azione, str(dettaglio)[:500]))

    def _contesto(self, chi):
        aperte = self.db.tutti("SELECT id, agente, problema FROM segnalazioni WHERE stato='aperta' ORDER BY id LIMIT 10")
        righe = [f"Oggi è {time.strftime('%Y-%m-%d %H:%M')}.", CAPACITA,
                 TELEFONO_SI if self.mano and self.mano.disponibile() else TELEFONO_NO]
        if chi == "ada":
            righe.append("TEAM: " + "; ".join(f"{k} ({v[1]})" for k, v in AGENTI.items() if k != "ada"))
            if aperte:
                righe.append("SEGNALAZIONI APERTE: " + " | ".join(f"#{s['id']} {s['agente']}: {s['problema']}" for s in aperte))
        return "\n".join(righe)

    # ---------- ciclo con strumenti ----------
    def _ciclo(self, chi, messaggi, strumenti):
        system = self.squadra.system(chi, self._contesto(chi))
        testo = ""
        for _ in range(GIRI.get(chi, self.max_giri)):
            r = self.llm(system, messaggi, strumenti)
            blocchi = r.get("content", [])
            testo = "".join(b.get("text", "") for b in blocchi if b.get("type") == "text").strip()
            if r.get("stop_reason") != "tool_use":
                return testo
            messaggi.append({"role": "assistant", "content": blocchi})
            esiti = [{"type": "tool_result", "tool_use_id": b["id"],
                      "content": self._esegui(chi, b["name"], b.get("input") or {})}
                     for b in blocchi if b.get("type") == "tool_use"]
            messaggi.append({"role": "user", "content": esiti})
        return testo or "Ho raggiunto il limite di passaggi per questa richiesta."

    def _esegui(self, chi, nome, args):
        if nome not in [t["name"] for t in strumenti_di(chi)]:
            return "Strumento non consentito."
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
            if nome.startswith("telefono_"):
                return self._telefono(nome, args)
            if nome == "proponi_acquisto":
                return self._proponi_acquisto(chi, args)
            if nome == "acquisto_pronto":
                return self._pronto(int(args["id"]), str(args.get("nota", ""))[:300])
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
        elif a["tipo"] == "pagamento":
            # Nessun pagamento parte da qui: si registra l'ok e il pagamento resta a mano.
            self.log("ada", "pagamento approvato", f"{a['titolo']} (da eseguire a mano: Ada non muove denaro)")
        self.log("utente", "approvata" if ok else "rifiutata", a["titolo"])
        return self.db.uno("SELECT * FROM approvazioni WHERE id=?", (id_,))

    # ---------- acquisti: scelta, autorizzazione, pronto, chiuso ----------
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
        return f"Modifica grande (#{mid}): non applicata, serve l'ok dell'utente (richiesta #{cur.lastrowid})."

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
            risposta = self._ciclo(agente, [{"role": "user", "content": compito}], strumenti_di(agente))
        except ErroreLLM as e:
            self.log(agente, "errore", e)
            return f"L'assistente non ha risposto: {e}"
        self.log(agente, "risposta", risposta)
        return risposta

    # ---------- conversazione ----------
    def _storia(self):
        righe = self.db.tutti("SELECT ruolo, testo FROM chat ORDER BY id DESC LIMIT 20")[::-1]
        msgs = []
        for r in righe:
            ruolo = "user" if r["ruolo"] == "utente" else "assistant"
            if msgs and msgs[-1]["role"] == ruolo:
                msgs[-1]["content"] += "\n" + r["testo"]
            elif msgs or ruolo == "user":
                msgs.append({"role": ruolo, "content": r["testo"]})
        return msgs

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
            if not self.llm.disponibile:
                risposta = self._senza_cervello(testo)
            else:
                try:
                    risposta = self._ciclo("ada", self._storia(), STRUMENTI_ADA) or "…"
                except ErroreLLM as e:
                    self.log("ada", "errore", e)
                    risposta = f"Non riesco a collegarmi al mio cervello in questo momento ({str(e)[:160]}). Riprova tra poco."
            self.db.esegui("INSERT INTO chat (ts, ruolo, testo) VALUES (?,?,?)", (int(time.time()), "ada", risposta))
        return risposta

    def ciclo_miglioramento(self):
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
            try:
                risposta = self._ciclo("ada", [{"role": "user", "content": richiesta}], STRUMENTI_ADA)
            except ErroreLLM as e:
                self.log("ada", "errore", e)
                return f"Ciclo interrotto: {str(e)[:160]}"
            self.db.esegui("INSERT INTO chat (ts, ruolo, testo) VALUES (?,?,?)",
                           (int(time.time()), "ada", "Ciclo di miglioramento:\n" + risposta))
        return risposta
