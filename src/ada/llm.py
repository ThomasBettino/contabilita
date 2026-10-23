"""Client minimale per l'API Messages di Anthropic (solo libreria standard, gira anche su Termux)."""
import json
import os
import urllib.error
import urllib.request

URL = "https://api.anthropic.com/v1/messages"
MODELLO = "claude-sonnet-5-5"


# Separa le istruzioni stabili (che si possono mettere in cache) dal contesto del momento (ora, stato).
MARCATORE = "\n\n##CONTESTO_DEL_MOMENTO##\n"


class ErroreLLM(Exception):
    pass


class Claude:
    def __init__(self, chiave=None, modello=None, apri=urllib.request.urlopen):
        self.chiave = chiave or os.environ.get("ANTHROPIC_API_KEY", "")
        self.modello = modello or os.environ.get("ADA_MODEL") or MODELLO
        self.apri, self.cache = apri, True  # cache dei prompt: prompt e strumenti uguali costano un decimo

    @property
    def disponibile(self) -> bool:
        return bool(self.chiave)

    def _corpo(self, system, messaggi, strumenti, max_tokens):
        corpo = {"model": self.modello, "max_tokens": max_tokens, "system": system, "messages": messaggi}
        if strumenti:
            corpo["tools"] = strumenti
        stabile, _, volatile = system.partition(MARCATORE)
        corpo["system"] = stabile + ("\n\n" + volatile if volatile else "")  # senza cache: un testo solo
        if self.cache:
            corpo["system"] = [{"type": "text", "text": stabile, "cache_control": {"type": "ephemeral"}}]
            if volatile:
                corpo["system"].append({"type": "text", "text": volatile})  # cambia spesso: fuori dalla cache
            if strumenti:
                corpo["tools"] = [*strumenti[:-1], {**strumenti[-1], "cache_control": {"type": "ephemeral"}}]
        return corpo

    def __call__(self, system, messaggi, strumenti=None, max_tokens=1500) -> dict:
        try:
            return self._invia(self._corpo(system, messaggi, strumenti, max_tokens))
        except ErroreLLM as e:
            if self.cache and "cache_control" in str(e):  # se l'API non la accetta, si va avanti senza
                self.cache = False
                return self._invia(self._corpo(system, messaggi, strumenti, max_tokens))
            raise

    def _invia(self, corpo) -> dict:
        req = urllib.request.Request(URL, data=json.dumps(corpo).encode(), method="POST", headers={
            "x-api-key": self.chiave, "anthropic-version": "2023-06-01", "content-type": "application/json"})
        try:
            with self.apri(req, timeout=90) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            raise ErroreLLM(f"HTTP {e.code}: {e.read()[:200].decode(errors='replace')}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise ErroreLLM(f"rete non raggiungibile ({type(e).__name__})") from None
