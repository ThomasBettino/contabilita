"""Client minimale per l'API Messages di Anthropic (solo libreria standard, gira anche su Termux)."""
import json
import os
import urllib.error
import urllib.request

URL = "https://api.anthropic.com/v1/messages"
MODELLO = "claude-sonnet-5-5"


class ErroreLLM(Exception):
    pass


class Claude:
    def __init__(self, chiave=None, modello=None):
        self.chiave = chiave or os.environ.get("ANTHROPIC_API_KEY", "")
        self.modello = modello or os.environ.get("ADA_MODEL") or MODELLO

    @property
    def disponibile(self) -> bool:
        return bool(self.chiave)

    def __call__(self, system, messaggi, strumenti=None, max_tokens=1500) -> dict:
        corpo = {"model": self.modello, "max_tokens": max_tokens, "system": system, "messages": messaggi}
        if strumenti:
            corpo["tools"] = strumenti
        req = urllib.request.Request(URL, data=json.dumps(corpo).encode(), method="POST", headers={
            "x-api-key": self.chiave, "anthropic-version": "2023-06-01", "content-type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            raise ErroreLLM(f"HTTP {e.code}: {e.read()[:200].decode(errors='replace')}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise ErroreLLM(f"rete non raggiungibile ({type(e).__name__})") from None
