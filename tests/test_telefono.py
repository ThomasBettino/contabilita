import json
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

from src.ada.cervello import strumenti_di
from src.ada.server import costruisci, crea_server
from src.telefono.guardiano import valuta_digitazione, valuta_tocco
from src.telefono.mano import Mano
from src.telefono.schermo import parse, render
from tests.test_ada import FinteRisposte, testo


def nodo(testo="", cl=False, b="[0,0][100,100]", classe="android.widget.TextView", pw=False, rid="", pkg="com.amazon.mShop.android.shopping"):
    return (f'<node text="{testo}" resource-id="{rid}" class="{classe}" package="{pkg}" content-desc="" '
            f'clickable="{str(cl).lower()}" password="{str(pw).lower()}" scrollable="false" bounds="{b}" />')


def xml(*nodi):
    return '<?xml version="1.0"?><hierarchy rotation="0">' + "".join(nodi) + "</hierarchy>"


class FakeAdb:
    def __init__(self, *schermate, connesso=True):
        self.schermate, self.azioni, self.connesso = list(schermate), [], connesso

    def collegato(self):
        return self.connesso

    def dump(self):
        return self.schermate.pop(0) if len(self.schermate) > 1 else self.schermate[0]

    def tap(self, x, y): self.azioni.append(("tap", x, y))
    def scrivi(self, t): self.azioni.append(("scrivi", t))
    def scorri(self, d): self.azioni.append(("scorri", d))
    def tasto(self, n): self.azioni.append(("tasto", n))
    def apri_app(self, p): self.azioni.append(("app", p))
    def apri_url(self, u): self.azioni.append(("url", u))


def mano(*schermate, autorizzato=False):
    return Mano(FakeAdb(*schermate), autorizzato=lambda: autorizzato, pausa=0, dormi=lambda s: None)


PRODOTTO = xml(nodo("Cuffie XY", b="[0,0][100,50]"), nodo("29,99 €", b="[0,50][100,100]"),
               nodo("Aggiungi al carrello", True, "[0,100][100,200]"), nodo("Acquista ora", True, "[0,200][100,300]"))
FINALE = xml(nodo("Riepilogo ordine"), nodo("Effettua l'ordine", True, "[0,100][100,200]"), nodo("Modifica", True, "[0,200][100,300]"))


class TestSchermo(unittest.TestCase):
    def test_parse_e_render(self):
        pkg, el = parse(xml(nodo("Cerca", True, classe="android.widget.EditText"), nodo("segreto", pw=True, classe="android.widget.EditText"),
                            nodo("", False, "[5,5][5,5]")))
        self.assertEqual((pkg, len(el)), ("com.amazon.mShop.android.shopping", 2))  # l'elemento a area zero è scartato
        r = render(pkg, el)
        self.assertIn('[1] "Cerca" (cliccabile, campo di testo)', r)
        self.assertNotIn("segreto", r)  # il contenuto dei campi password non viene mai mostrato


class TestGuardiano(unittest.TestCase):
    def els(self, x):
        return parse(x)[1]

    def test_acquista_ora_mai(self):
        el = self.els(PRODOTTO)
        acquista = next(e for e in el if e.etichetta == "Acquista ora")
        self.assertIn("lo preme l'utente", valuta_tocco(acquista, el, autorizzato=True))

    def test_schermata_finale_blocca_tutto(self):
        el = self.els(FINALE)
        for e in el:
            self.assertIsNotNone(valuta_tocco(e, el, autorizzato=True), e.etichetta)

    def test_carrello_solo_con_autorizzazione(self):
        el = self.els(PRODOTTO)
        carrello = next(e for e in el if e.etichetta == "Aggiungi al carrello")
        self.assertIn("autorizzazione", valuta_tocco(carrello, el, autorizzato=False))
        self.assertIsNone(valuta_tocco(carrello, el, autorizzato=True))

    def test_id_tecnico_e_inglese(self):
        el = self.els(xml(nodo("", True, rid="buy-now-button"), nodo("Place your order", True)))
        self.assertIsNotNone(valuta_tocco(el[0], el, True))

    def test_digitazione(self):
        campo = self.els(xml(nodo("x", classe="android.widget.EditText")))[0]
        pw = self.els(xml(nodo("x", pw=True, classe="android.widget.EditText")))[0]
        self.assertIsNone(valuta_digitazione(campo, "cuffie bluetooth"))
        self.assertIsNotNone(valuta_digitazione(pw, "ciao"))
        self.assertIsNotNone(valuta_digitazione(campo, "4111 1111 1111 1111"))
        self.assertIsNotNone(valuta_digitazione(campo, "IT60X0542811101000000123456"))


class TestMano(unittest.TestCase):
    def test_tocco_consentito_e_bloccato(self):
        m = mano(PRODOTTO, autorizzato=True)
        m.guarda()
        cart = next(e.id for e in m.elementi if e.etichetta == "Aggiungi al carrello")
        buy = next(e.id for e in m.elementi if e.etichetta == "Acquista ora")
        self.assertTrue(m.tocca(buy).startswith("BLOCCATO"))
        self.assertEqual(m.adb.azioni, [])
        m.tocca(cart)
        self.assertEqual(m.adb.azioni, [("tap", 50, 150)])

    def test_senza_autorizzazione_carrello_bloccato(self):
        m = mano(PRODOTTO, autorizzato=False)
        m.guarda()
        cart = next(e.id for e in m.elementi if e.etichetta == "Aggiungi al carrello")
        self.assertTrue(m.tocca(cart).startswith("BLOCCATO"))
        self.assertEqual(m.adb.azioni, [])

    def test_app_protetta_non_letta_ne_toccata(self):
        m = mano(xml(nodo("Saldo 59,90", True, pkg="com.revolut.revolut")))
        self.assertIn("App protetta", m.guarda())
        self.assertEqual(m.elementi, [])
        self.assertTrue(m.apri(app="revolut").startswith("BLOCCATO"))
        self.assertTrue(m.apri(app="com.paypal.android.p2pmobile").startswith("BLOCCATO"))

    def test_stop_ferma_tutto(self):
        m = mano(PRODOTTO, autorizzato=True)
        m.guarda()
        m.fermo = True
        for risposta in (m.guarda(), m.tocca(1), m.scorri("giu"), m.vai("home"), m.apri(app="chrome")):
            self.assertTrue(risposta.startswith("FERMO"))
        self.assertEqual(m.adb.azioni, [])

    def test_url_solo_https_semplici(self):
        m = mano(PRODOTTO)
        for url in ("http://amazon.it", "intent://x#Intent;end", "https://a.it/x;rm -rf", "https://a.it/ $(id)"):
            self.assertTrue(m.apri(url=url).startswith("BLOCCATO"), url)
        m.apri(url="https://www.amazon.it/s?k=cuffie")
        self.assertEqual(m.adb.azioni, [("url", "https://www.amazon.it/s?k=cuffie")])


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def ctx(self, llm=None, *schermate):
        ctx = costruisci(llm=llm or FinteRisposte(), home=Path(self.tmp.name), movimenti=Path(self.tmp.name) / "n.db", token="")
        ctx.ada.mano = Mano(FakeAdb(*(schermate or (PRODOTTO,))), autorizzato=ctx.ada.autorizzazione_attiva,
                            log=ctx.ada.log, pausa=0, dormi=lambda s: None)
        self.addCleanup(ctx.db.c.close)
        return ctx


OPZIONI = [{"nome": "Cuffie XY", "prezzo_totale": 29.99, "stelle": 4.5, "recensioni": 3200, "venditore": "Amazon", "etichetta": "consigliata"},
           {"nome": "Cuffie Z", "prezzo_totale": 19.9, "stelle": 4.1, "recensioni": 210, "venditore": "Terzi", "etichetta": "economica"}]


class TestFlussoAcquisto(Base):
    def proponi(self, ctx):
        return ctx.ada._esegui("acquisti", "proponi_acquisto", {"richiesta": "cuffie bluetooth", "opzioni": OPZIONI})

    def test_proposta_valida_e_non_valida(self):
        ctx = self.ctx()
        self.assertIn("Servono da 1 a 5", ctx.ada._esegui("acquisti", "proponi_acquisto", {"richiesta": "x", "opzioni": []}))
        self.assertIn("prezzo_totale reale", ctx.ada._esegui("acquisti", "proponi_acquisto",
                      {"richiesta": "x", "opzioni": [{"nome": "A", "prezzo_totale": "gratis"}]}))
        self.assertIn("Proposta #1", self.proponi(ctx))

    def test_catena_completa_e_cancello_del_carrello(self):
        ctx = self.ctx()
        self.proponi(ctx)
        ctx.ada.mano.guarda()
        cart = next(e.id for e in ctx.ada.mano.elementi if e.etichetta == "Aggiungi al carrello")
        self.assertTrue(ctx.ada.mano.tocca(cart).startswith("BLOCCATO"))          # prima della scelta
        with self.assertRaises(ValueError):
            ctx.ada.risolvi(1, "approva")                                           # senza opzione
        ctx.ada.risolvi(1, "approva", 0)                                            # l'utente sceglie
        self.assertTrue(ctx.ada.mano.tocca(cart).startswith("BLOCCATO"))          # scelta non basta
        self.assertIn("non autorizzato", ctx.ada._pronto(1, "x"))                   # pronto richiede autorizzazione
        ctx.ada.autorizza(1)                                                        # l'utente autorizza
        self.assertFalse(ctx.ada.mano.tocca(cart).startswith("BLOCCATO"))         # ora il carrello si può toccare
        self.assertIn("tocca all'utente", ctx.ada._esegui("acquisti", "acquisto_pronto", {"id": 1, "nota": "alla cassa"}))
        self.assertFalse(ctx.ada.autorizzazione_attiva())                           # fine autorizzazione
        ctx.ada.chiudi_acquisto(1, "comprato")
        self.assertEqual(ctx.db.uno("SELECT stato FROM approvazioni")["stato"], "chiusa")

    def test_autorizza_richiede_scelta(self):
        ctx = self.ctx()
        self.proponi(ctx)
        with self.assertRaises(ValueError):
            ctx.ada.autorizza(1)

    def test_autorizzazione_scade(self):
        ctx = self.ctx()
        self.proponi(ctx)
        ctx.ada.risolvi(1, "approva", 0)
        ctx.ada.autorizza(1)
        ctx.db.esegui("UPDATE approvazioni SET risolta_ts=risolta_ts-4000")
        self.assertFalse(ctx.ada.autorizzazione_attiva())

    def test_prepara_acquisto_delega_e_scrive_in_chat(self):
        ctx = self.ctx(FinteRisposte(testo("Sono alla schermata finale, premi tu.")))
        self.proponi(ctx)
        ctx.ada.risolvi(1, "approva", 0)
        ctx.ada.autorizza(1)
        ctx.ada.prepara_acquisto(1)
        self.assertIn("premi tu", ctx.db.uno("SELECT testo FROM chat ORDER BY id DESC")["testo"])

    def test_strumenti_per_agente(self):
        for nome in ("revisore", "quotidiano", "contabilita_piva"):
            self.assertNotIn("telefono_tocca", [t["name"] for t in strumenti_di(nome)])
        self.assertIn("telefono_tocca", [t["name"] for t in strumenti_di("acquisti")])
        self.assertIn("telefono_tocca", [t["name"] for t in strumenti_di("ada")])
        ctx = self.ctx()
        self.assertEqual(ctx.ada._esegui("revisore", "telefono_tocca", {"id": 1}), "Strumento non consentito.")

    def test_senza_telefono_collegato_lo_dice(self):
        ctx = self.ctx()
        ctx.ada.mano = None
        self.assertIn("NON collegato", ctx.ada._esegui("ada", "telefono_schermo", {}))


class TestServerAcquisti(Base):
    def test_api_scelta_autorizza_stop(self):
        ctx = self.ctx(FinteRisposte(testo("ok")))
        ctx.ada._esegui("acquisti", "proponi_acquisto", {"richiesta": "cuffie", "opzioni": OPZIONI})
        srv = crea_server(ctx, "127.0.0.1", 0)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        self.addCleanup(srv.server_close)
        base = f"http://127.0.0.1:{srv.server_address[1]}"

        def post(path, dati):
            req = urllib.request.Request(base + path, data=json.dumps(dati).encode(), headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req) as r:
                    return r.status, json.load(r)
            except urllib.error.HTTPError as e:
                return e.code, json.load(e)

        self.assertEqual(post("/api/approvazioni/1/autorizza", {})[0], 400)         # prima serve la scelta
        self.assertEqual(post("/api/approvazioni/1", {"esito": "approva", "opzione": 9})[0], 400)
        self.assertEqual(post("/api/approvazioni/1", {"esito": "approva", "opzione": 1})[1]["stato"], "scelta")
        stato = json.load(urllib.request.urlopen(base + "/api/stato"))
        self.assertEqual(stato["approvazioni"][0]["stato"], "scelta")
        self.assertEqual(post("/api/telefono", {"fermo": True})[1], {"collegato": True, "fermo": True})
        self.assertEqual(post("/api/approvazioni/1/chiudi", {"esito": "annullato"})[0], 200)


if __name__ == "__main__":
    unittest.main()
