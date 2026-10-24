"""Lettura di un estratto conto in CSV (Revolut e banche italiane) e abbinamento con i movimenti già noti.

Il file arriva come testo dall'app. I PDF non si leggono: serve il CSV (in Revolut: Conti, tre puntini, Estratto, formato
Excel o CSV). Ciò che non quadra non viene scartato in silenzio: finisce nei conteggi «ignorate» o nell'elenco «da controllare».
"""
import csv
import io
import re
from datetime import date, datetime

MAX_RIGHE = 5000
FORMATI_DATA = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%d/%m/%Y %H:%M:%S",
                "%d/%m/%Y %H:%M", "%d/%m/%Y", "%d-%m-%Y %H:%M:%S", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y")
# intestazioni, dalla più adatta alla meno: la prima colonna che combacia vince
INTESTAZIONI = {
    "data": ("data di completamento", "completed date", "data completamento", "data contabile", "data operazione",
             "data di inizio", "started date", "data valuta", "data", "date"),
    "descrizione": ("descrizione", "description", "causale", "dettagli", "dettaglio", "beneficiario", "controparte", "payee"),
    "importo": ("importo", "amount", "valore"),
    "costo": ("costo", "fee", "commissioni"),
    "dare": ("dare", "addebiti", "addebito", "uscite", "debit", "withdrawal"),
    "avere": ("avere", "accrediti", "accredito", "entrate", "credit", "deposit"),
    "valuta": ("valuta", "currency"),
    "stato": ("stato", "state", "status"),
    "tipo": ("tipo", "type"),
}
NON_COMPLETATI = ("revert", "declin", "fail", "annull", "rifiut", "pending", "attesa", "sospeso", "cancel")


def numero(testo):
    """«1.234,56», «1,234.56», «-12.5», «(12,50)», «− 5,80 €» -> float; None se non è un numero."""
    s = re.sub(r"[€$£\sA-Za-z]", "", str(testo or "")).replace("−", "-").replace(" ", "")
    if not s:
        return None
    negativo = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    if "," in s and "." in s:
        decimale = "," if s.rfind(",") > s.rfind(".") else "."
        s = s.replace("." if decimale == "," else ",", "").replace(decimale, ".")
    elif "," in s:
        s = s.replace(",", ".")
    elif re.fullmatch(r"-?\d{1,3}(\.\d{3})+", s):  # 1.234 = milleduecentotrentaquattro
        s = s.replace(".", "")
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if negativo else v


def data_ora(testo):
    t = str(testo or "").strip()
    for f in FORMATI_DATA:
        try:
            d = datetime.strptime(t, f)
        except ValueError:
            continue
        return d.strftime("%Y-%m-%d"), (d.strftime("%H:%M:%S") if "%H" in f else "12:00:00")
    return None


def _delimitatore(testo):
    prima = testo[:4000]
    return max(",;\t", key=lambda d: prima.count(d))


def _colonne(intestazione):
    nomi = [re.sub(r"\s+", " ", c.strip().lower()) for c in intestazione]
    trovate = {}
    for campo, candidati in INTESTAZIONI.items():
        for cand in candidati:
            if cand in nomi:
                trovate[campo] = nomi.index(cand)
                break
    if "valuta" in trovate and nomi[trovate["valuta"]] == "data valuta":
        trovate.pop("valuta")
    return trovate


def leggi_estratto(testo):
    """Ritorna {"righe": [{"data", "ora", "importo", "descrizione"}], "ignorate": {motivo: quante}}; ValueError se illeggibile."""
    testo = (testo or "").lstrip("﻿")
    if not testo.strip():
        raise ValueError("Il file è vuoto.")
    if testo.startswith("%PDF"):
        raise ValueError("I PDF non si leggono: scarica l'estratto in formato CSV o Excel (in Revolut: Conti, tre puntini, Estratto).")
    righe_csv = list(csv.reader(io.StringIO(testo), delimiter=_delimitatore(testo)))
    colonne, inizio = {}, 0
    for i, riga in enumerate(righe_csv[:20]):
        c = _colonne(riga)
        if "data" in c and ("importo" in c or ("dare" in c and "avere" in c) or "avere" in c or "dare" in c):
            colonne, inizio = c, i + 1
            break
    if not colonne:
        raise ValueError("Non riconosco il formato: serve un CSV con almeno data, descrizione e importo.")
    ignorate = {}

    def salta(motivo):
        ignorate[motivo] = ignorate.get(motivo, 0) + 1

    def cella(riga, campo):
        i = colonne.get(campo)
        return riga[i].strip() if i is not None and i < len(riga) else ""
    out = []
    for riga in righe_csv[inizio:]:
        if not any(c.strip() for c in riga):
            continue
        if len(out) >= MAX_RIGHE:
            raise ValueError(f"Troppi movimenti (più di {MAX_RIGHE}): carica un periodo più corto.")
        stato = cella(riga, "stato").lower()
        if stato and any(k in stato for k in NON_COMPLETATI):
            salta("annullati o in attesa")
            continue
        quando = data_ora(cella(riga, "data"))
        if "importo" in colonne:
            importo = numero(cella(riga, "importo"))
            costo = numero(cella(riga, "costo")) or 0.0
            if importo is not None:
                importo -= costo
        else:
            dare, avere = numero(cella(riga, "dare")) or 0.0, numero(cella(riga, "avere")) or 0.0
            importo = abs(avere) - abs(dare) if (dare or avere) else None
        if not quando or importo is None:
            salta("senza data o importo")
            continue
        tipo = f"{cella(riga, 'tipo')} {cella(riga, 'descrizione')}".lower()
        if "exchange" in tipo or tipo.startswith("cambio") or "scambiato" in tipo:
            salta("cambi di valuta tra i tuoi conti")
            continue
        valuta = cella(riga, "valuta").upper()
        if valuta and valuta != "EUR":
            salta("in altra valuta")
            continue
        if abs(importo) < 0.005:
            salta("importo zero")
            continue
        descrizione = " ".join(cella(riga, "descrizione").split())[:80] or "(senza descrizione)"
        out.append({"data": quando[0], "ora": quando[1], "importo": round(importo, 2), "descrizione": descrizione})
    return {"righe": out, "ignorate": ignorate}


def giorni_tra(a, b):
    try:
        return abs((date.fromisoformat(a) - date.fromisoformat(b)).days)
    except ValueError:
        return 999
