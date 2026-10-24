"""File dei codici salvati dall'app (indirizzo e codice dello script Google). Mai in chat, mai nel repo."""
import json
import os
from pathlib import Path


class Segreti:
    def __init__(self, percorso):
        self.p = Path(percorso)

    def leggi(self) -> dict:
        try:
            return json.loads(self.p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def scrivi(self, **dati) -> None:
        tmp = self.p.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)  # permessi stretti fin dalla creazione
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({**self.leggi(), **dati}, f)
        os.replace(tmp, self.p)
        os.chmod(self.p, 0o600)
