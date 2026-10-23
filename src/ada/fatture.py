"""Archivio fatture P.IVA: si collega allo script Google dell'app Contabilità Smart.

Lo script archivia da solo le fatture che mandi a Giulia (file Word, PDF su Drive, stato).
Qui Ada le porta nell'hub, riconosce il bonifico del pagatore e segna la fattura giusta come incassata.
I calcoli sono gli stessi dell'app: bonifico = imponibile + bollo - Enasarco.
"""
import json
import math
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

SOGLIA_BOLLO = 77.47
HOST_SCRIPT = "https://script.google.com/"


class ErroreFatture(Exception):
    pass


def eur(x) -> str:
    """741.3 -> '741,30 €' (formato italiano, con il punto per le migliaia)."""
    return f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " €"


@dataclass
class Config:
    url: str = field(default_factory=lambda: os.environ.get("ADA_FATTURE_URL", ""))
    token: str = field(default_factory=lambda: os.environ.get("ADA_FATTURE_TOKEN", ""))
    ena: float = field(default_factory=lambda: float(os.environ.get("ADA_ENASARCO", "8.5").replace(",", ".")))
    tasse: float = field(default_factory=lambda: float(os.environ.get("ADA_TASSE", "30").replace(",", ".")))
    giorni: int = field(default_factory=lambda: int(os.environ.get("ADA_GIORNI", "30")))
    pagatore: str = field(default_factory=lambda: os.environ.get("ADA_PAGATORE", "autoghinzani").lower())


def num(v) -> float:
    if isinstance(v, (int, float)):
        return float(v)
    s = re.sub(r"[^\d,.\-]", "", str(v or ""))
    s = re.sub(r"\.(?=\d{3}(\D|$))", "", s).replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _tonda(x: float) -> int:
    return math.floor(x + 0.5)  # come Math.round di JavaScript


def calcola(f: dict, cfg: Config) -> dict:
    lordo = num(f.get("lordo"))
    bollo = num(f["bollo"]) if f.get("bollo") not in (None, "") else (2.0 if lordo > SOGLIA_BOLLO else 0.0)
    ena = _tonda(lordo * cfg.ena) / 100
    netto = lordo - ena
    tasse = _tonda(netto * cfg.tasse) / 100
    return {"lordo": round(lordo, 2), "bollo": bollo, "ena": ena, "netto": round(netto, 2), "tasse": tasse,
            "bonifico": round(lordo + bollo - ena, 2)}


class ClienteScript:
    """Parla con lo script Google come l'app (POST di testo con il token dentro)."""

    def __init__(self, url, token, apri=urllib.request.urlopen):
        self.url, self.token, self.apri = url, token, apri

    @property
    def configurato(self) -> bool:
        return bool(self.url and self.token)

    def chiama(self, **corpo) -> dict:
        if not self.configurato:
            raise ErroreFatture("script non configurato (ADA_FATTURE_URL e ADA_FATTURE_TOKEN)")
        if not self.url.startswith(HOST_SCRIPT):  # il token non deve mai finire su un altro sito
            raise ErroreFatture("l'indirizzo dello script deve iniziare con https://script.google.com/")
        req = urllib.request.Request(self.url, data=json.dumps({**corpo, "token": self.token}).encode(),
                                     method="POST", headers={"Content-Type": "text/plain;charset=utf-8"})
        try:
            with self.apri(req, timeout=40) as r:
                j = json.load(r)
        except urllib.error.HTTPError as e:
            raise ErroreFatture(f"HTTP {e.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
            raise ErroreFatture(f"script non raggiungibile ({type(e).__name__})") from None
        if not j.get("ok"):
            raise ErroreFatture(str(j.get("error") or "errore dello script")[:150])
        return j


class Archivio:
    def __init__(self, ada, cliente, cfg=None):
        self.ada, self.db, self.cliente, self.cfg = ada, ada.db, cliente, cfg or Config()

    @property
    def configurato(self) -> bool:
        return self.cliente.configurato

    # ---------- dati ----------
    def _kv(self, chiave, default=None):
        r = self.db.uno("SELECT valore FROM kv WHERE chiave=?", (chiave,))
        return json.loads(r["valore"]) if r else default

    def _imposta(self, chiave, valore):
        self.db.esegui("INSERT INTO kv (chiave, valore) VALUES (?,?) ON CONFLICT(chiave) DO UPDATE SET valore=excluded.valore",
                       (chiave, json.dumps(valore, ensure_ascii=False)))

    def _fatture(self):
        return [json.loads(r["dati"]) for r in self.db.tutti("SELECT dati FROM fatture")]

    def _trova(self, id_):
        r = self.db.uno("SELECT dati FROM fatture WHERE id=?", (str(id_),))
        return json.loads(r["dati"]) if r else None

    def _salva(self, f):
        self.db.esegui("INSERT OR REPLACE INTO fatture (id, dati) VALUES (?,?)", (str(f["id"]), json.dumps(f, ensure_ascii=False)))

    def _scritta(self, f):
        return f"{f.get('numero') or 'senza numero'}" + (f" ({f['descrizione']})" if f.get("descrizione") else "")

    def _messaggio(self, testo):
        self.db.esegui("INSERT INTO chat (ts, ruolo, testo) VALUES (?,?,?)", (int(time.time()), "ada", testo))

    # ---------- sincronizzazione ----------
    def sincronizza(self) -> dict:
        j = self.cliente.chiama(action="list")
        remote = [f for f in (j.get("fatture") or []) if f.get("id")]
        primo = not self._kv("fatture_avviato", False)
        gia = {r["id"] for r in self.db.tutti("SELECT id FROM fatture")}
        nuove = [f for f in remote if str(f["id"]) not in gia]
        for f in remote:
            self._salva(f)
        ids = [str(f["id"]) for f in remote]
        if ids:
            marche = ",".join("?" * len(ids))
            self.db.esegui(f"DELETE FROM fatture WHERE id NOT IN ({marche})", ids)
        self._imposta("accantonamenti", j.get("accantonamenti") or {})
        self._imposta("fatture_avviato", True)
        if not primo:  # al primo giro si importa lo storico senza fare rumore
            for f in nuove:
                self.ada.log("contabilita_piva", "fattura archiviata", self._scritta(f))
            if nuove:
                self.ada.avvisa("Fattura archiviata", f"{len(nuove)} {'nuova fattura' if len(nuove) == 1 else 'nuove fatture'} nell'archivio.",
                                "ada-fattura")
        return {"nuove": 0 if primo else len(nuove), "totale": len(remote)}

    def elenco(self):
        oggi = time.strftime("%Y-%m-%d")
        out = []
        for f in self._fatture():
            c = calcola(f, self.cfg)
            giorni = 0
            if f.get("data"):
                try:
                    giorni = int((time.mktime(time.strptime(oggi, "%Y-%m-%d")) - time.mktime(time.strptime(f["data"][:10], "%Y-%m-%d"))) // 86400)
                except ValueError:
                    pass
            scaduta = f.get("stato") != "incassata" and giorni > self.cfg.giorni
            out.append({**f, "calc": c, "scaduta": scaduta, "giorni_scaduta": max(0, giorni - self.cfg.giorni) if scaduta else 0})
        return sorted(out, key=lambda x: x.get("data") or "", reverse=True)

    def riepilogo(self, mese=None) -> dict:
        mese = mese or time.strftime("%Y-%m")
        mensili = [f for f in self.elenco() if (f.get("data") or "")[:7] == mese]
        incassato = round(sum(f["calc"]["bonifico"] for f in mensili if f.get("stato") == "incassata"), 2)
        da_incassare = round(sum(f["calc"]["bonifico"] for f in mensili if f.get("stato") != "incassata"), 2)
        dovute = round(sum(f["calc"]["tasse"] for f in mensili), 2)
        accantonato = num((self._kv("accantonamenti", {}) or {}).get(mese, 0))
        return {"mese": mese, "fatture": len(mensili), "imponibile": round(sum(f["calc"]["lordo"] for f in mensili), 2),
                "incassato": incassato, "da_incassare": da_incassare, "tasse_dovute": dovute,
                "accantonato": accantonato, "mancano": round(max(0.0, dovute - accantonato), 2),
                "scadute": sum(1 for f in mensili if f["scaduta"])}

    def testo(self, mese=None) -> str:
        if not self.configurato:
            return "Archivio fatture non configurato (mancano ADA_FATTURE_URL e ADA_FATTURE_TOKEN, vedi docs/FATTURE.md)."
        r = self.riepilogo(mese)
        if not r["fatture"]:
            return f"Nessuna fattura nel mese {r['mese']}."
        righe = [f"Mese {r['mese']}: {r['fatture']} fatture, imponibile {eur(r['imponibile'])}.",
                 f"Bonifici arrivati {eur(r['incassato'])}, ancora attesi {eur(r['da_incassare'])}.",
                 f"Tasse da accantonare {eur(r['tasse_dovute'])} ({self.cfg.tasse:g}% del netto dopo Enasarco {self.cfg.ena:g}%), "
                 f"già accantonate {eur(r['accantonato'])}, mancano {eur(r['mancano'])}."]
        if r["scadute"]:
            righe.append(f"Fatture con bonifico in ritardo (oltre {self.cfg.giorni} giorni): {r['scadute']}.")
        for f in self.elenco():
            if (f.get("data") or "")[:7] == r["mese"]:
                righe.append(f"- id {f['id']}: {self._scritta(f)}, {f.get('stato')}, bonifico atteso {eur(f['calc']['bonifico'])}")
        return "\n".join(righe)

    # ---------- incassi ----------
    def segna_incassata(self, id_, data=None, da="ada") -> str:
        f = self._trova(id_)
        if not f:
            return "Fattura non trovata."
        if f.get("stato") == "incassata":
            return "Era già segnata come incassata."
        data = data or time.strftime("%Y-%m-%d")
        self.cliente.chiama(action="update", id=f["id"], fields={"stato": "incassata", "dataIncasso": data})
        self._imposta(f"prima:{f['id']}", f.get("stato") or "fatturata")
        f["stato"], f["dataIncasso"] = "incassata", data
        self._salva(f)
        self.ada.log(da, "fattura incassata", self._scritta(f))
        return f"Fattura {self._scritta(f)} segnata come incassata."

    def segna_non_incassata(self, id_) -> str:
        f = self._trova(id_)
        if not f or f.get("stato") != "incassata":
            return "Fattura non trovata o non incassata."
        prima = self._kv(f"prima:{f['id']}", "fatturata")
        self.cliente.chiama(action="update", id=f["id"], fields={"stato": prima, "dataIncasso": ""})
        f["stato"], f["dataIncasso"] = prima, ""
        self._salva(f)
        self.ada.log("utente", "incasso annullato", self._scritta(f))
        return f"Fattura {self._scritta(f)} tornata allo stato «{prima}»."

    def elabora_incassi(self) -> str:
        """Guarda i nuovi accrediti sul conto e li abbina alle fatture ancora da incassare."""
        righe = self.ada.soldi.tutti()
        visti = {r["chiave"] for r in self.db.tutti("SELECT chiave FROM movimenti_visti")}
        if not self._kv("incassi_avviato", False):
            for r in righe:
                self.db.esegui("INSERT OR IGNORE INTO movimenti_visti VALUES (?)", (r["chiave"],))
            self._imposta("incassi_avviato", True)
            return f"Avviato: {len(righe)} movimenti già presenti non vengono riesaminati."
        esiti = []
        for r in righe:
            if r["chiave"] in visti:
                continue
            try:
                esiti.append(self._abbina(r) if r["importo"] > 0 else "")
            except ErroreFatture as e:  # script giù: il bonifico resta da esaminare al prossimo giro
                esiti.append(f"rinviato ({e})")
                continue
            self.db.esegui("INSERT OR IGNORE INTO movimenti_visti VALUES (?)", (r["chiave"],))
        return "; ".join(e for e in esiti if e) or "Nessun nuovo bonifico."

    def _abbina(self, r) -> str:
        importo = round(float(r["importo"]), 2)
        testo = f"{r.get('controparte') or ''} {r.get('testo') or ''}".lower()
        pagatore = self.cfg.pagatore in testo
        aperte = [f for f in self.elenco() if f.get("stato") != "incassata" and abs(f["calc"]["bonifico"] - importo) < 0.005]
        nome = self.cfg.pagatore.capitalize()
        if pagatore and len(aperte) == 1:
            f = aperte[0]
            esito = self.segna_incassata(f["id"], (r.get("quando") or "")[:10] or None)  # se fallisce, nulla viene perso
            self.ada.avvisa("Bonifico arrivato", f"È arrivato un bonifico da {nome}.", "ada-bonifico")
            self._messaggio(f"È arrivato il bonifico di {nome}: {eur(importo)}. {esito}")
            return "bonifico abbinato"
        if pagatore and len(aperte) > 1:
            self.ada.avvisa("Bonifico arrivato", f"È arrivato un bonifico da {nome}: serve capire a quale fattura.", "ada-bonifico")
            elenco = ", ".join(f"id {f['id']} ({self._scritta(f)})" for f in aperte)
            self._messaggio(f"È arrivato un bonifico di {nome} di {eur(importo)}, ma corrisponde a più fatture: {elenco}. Dimmi quale devo segnare.")
            return "bonifico ambiguo"
        if pagatore:
            self.ada.avvisa("Bonifico arrivato", f"È arrivato un bonifico da {nome}, ma nessuna fattura corrisponde.", "ada-bonifico")
            attese = ", ".join(f"{self._scritta(f)} {eur(f['calc']['bonifico'])}" for f in self.elenco() if f.get("stato") != "incassata")
            self._messaggio(f"È arrivato un bonifico di {nome} di {eur(importo)}, ma nessuna fattura da incassare ha questo importo."
                            + (f" Bonifici attesi: {attese}." if attese else " Non ci sono fatture da incassare."))
            return "bonifico senza fattura"
        if len(aperte) == 1:  # importo identico ma pagatore non riconosciuto: chiedo conferma
            f = aperte[0]
            det = json.dumps({"fattura_id": f["id"], "importo": importo, "testo": f"Un bonifico di {eur(importo)} ha lo stesso importo "
                              f"della fattura {self._scritta(f)}. È il pagamento di quella fattura?"}, ensure_ascii=False)
            self.db.esegui("INSERT INTO approvazioni (ts, tipo, titolo, dettaglio) VALUES (?,?,?,?)",
                           (int(time.time()), "incasso", "Segno la fattura come incassata?", det))
            self.ada.avvisa("Ada ha bisogno di te", "Un bonifico potrebbe essere il pagamento di una fattura.", "ada-attesa")
            return "bonifico da confermare"
        return ""
