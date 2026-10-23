"""Collegamento con GitHub: ogni idea approvata diventa un problema (issue) che avvia lo sviluppo."""
import json
import re
import urllib.error
import urllib.request

API = "https://api.github.com"
REPO = re.compile(r"[A-Za-z0-9_.-]{1,39}/[A-Za-z0-9_.-]{1,100}")
ETICHETTA = "idea-ada"


class ErroreGitHub(Exception):
    pass


def corpo_issue(i: dict) -> str:
    return (f"@claude Implementa questa idea per l'app Ada.\n\n**{i['titolo']}**\n\n{i['descrizione']}\n\n"
            f"**Perché:** {i['motivo']}\n\n## Istruzioni\n"
            "- Leggi prima `docs/PROGETTO-AGENTI.md` e `docs/AVVIO.md`.\n"
            "- Aggiungi test per ogni comportamento nuovo e fai passare `python3 -m unittest discover -s tests -t .`.\n"
            "- Non toccare i confini di sicurezza: `src/telefono/guardiano.py`, `REGOLE` in `src/ada/agenti.py`, "
            "i permessi sui soldi e il tasto finale degli acquisti.\n"
            "- Nessuna dipendenza nuova: solo libreria standard. Testi dell'interfaccia in italiano.\n"
            "- Apri una pull request verso il ramo predefinito: la rivede e la unisce una persona.\n\n"
            "_Proposta da Ada, approvata dall'utente._")


class ClienteGitHub:
    def __init__(self, repo="", token="", apri=urllib.request.urlopen):
        self.repo, self.token, self.apri = repo, token, apri

    @property
    def configurato(self) -> bool:
        return bool(self.token and REPO.fullmatch(self.repo or ""))

    def _chiama(self, metodo, percorso, corpo=None):
        if not self.configurato:
            raise ErroreGitHub("GitHub non collegato")
        req = urllib.request.Request(API + percorso, method=metodo,
                                     data=None if corpo is None else json.dumps(corpo).encode(),
                                     headers={"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json",
                                              "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "ada-hub",
                                              "Content-Type": "application/json"})
        try:
            with self.apri(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            try:
                msg = str(json.loads(e.read()).get("message", ""))[:120]
            except ValueError:
                msg = ""
            raise ErroreGitHub(f"HTTP {e.code}{': ' + msg if msg else ''}") from None  # mai il token nei messaggi
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            raise ErroreGitHub("GitHub non raggiungibile") from None

    def verifica(self) -> dict:
        j = self._chiama("GET", f"/repos/{self.repo}")
        return {"privato": bool(j.get("private")), "ramo": j.get("default_branch")}

    def crea_issue(self, titolo: str, corpo: str) -> dict:
        j = self._chiama("POST", f"/repos/{self.repo}/issues", {"title": titolo[:200], "body": corpo, "labels": [ETICHETTA]})
        return {"numero": j["number"], "url": j["html_url"]}
