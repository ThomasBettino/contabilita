"""Igiene dei test: non possono usare la rete vera né le impostazioni (chiavi, token) del telefono.

Succede PRIMA che i moduli di src vengano importati, così anche i collegamenti con `apri=urlopen`
di default (Claude, GitHub, script Google) ricevono la versione protetta.
Un test che prova a uscire su internet fallisce con un errore chiaro invece di agire per davvero.
"""
import os
import urllib.parse
import urllib.request

for _k in [k for k in os.environ if k.startswith("ADA_") or k in ("ANTHROPIC_API_KEY", "GITHUB_TOKEN", "GH_TOKEN")]:
    del os.environ[_k]

_urlopen_vero = urllib.request.urlopen
_LOCALI = ("127.0.0.1", "localhost", "::1")


def _solo_locale(req, *args, **kwargs):
    url = req if isinstance(req, str) else req.full_url
    if urllib.parse.urlparse(url).hostname not in _LOCALI:
        raise AssertionError(f"I test non devono usare la rete vera: {url}")
    return _urlopen_vero(req, *args, **kwargs)


urllib.request.urlopen = _solo_locale
