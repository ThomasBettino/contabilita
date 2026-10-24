import io
import json
import tempfile
import unittest
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from unittest import mock

from src.ada import cervello, studio
from src.ada.cervello import CAPACITA, strumenti_di
from src.ada.server import costruisci
from src.ada.studio import _controlla_indirizzo, senza_intestazione_gutenberg
from tests.test_ada import FinteRisposte, testo, usa
from tests.test_agenda import ClienteHTTP

TESTO_LUNGO = "Chi conosce il terreno e conosce sé stesso non teme cento battaglie. " * 12
RICERCA = """<html><body><ul>
<li class="booklink"><a class="link" href="/ebooks/132" accesskey="1"><span class="cover-thumb"><img src="x.png"></span>
<span class="content"><span class="title">The Art of War</span><span class="subtitle">Sunzi, 6th century B.C.</span><span class="extra">9999 downloads</span></span></a></li>
<li class="booklink"><a class="link" href="/ebooks/1232"><span class="content"><span class="title">Il Principe &amp; altri scritti</span><span class="subtitle">Machiavelli, Niccol&#242;</span></span></a></li>
<li class="statusline">non è un libro</li>
</ul></body></html>"""
LIBRO = ("The Project Gutenberg eBook of The Art of War\n\nTitle: The Art of War\nAuthor: Sun Tzu\nLanguage: English\n\n"
         "*** START OF THE PROJECT GUTENBERG EBOOK THE ART OF WAR ***\n\n" + TESTO_LUNGO +
         "\n\n*** END OF THE PROJECT GUTENBERG EBOOK THE ART OF WAR ***\nLicenza e note legali che non vanno lette.\n")


class _Risposta:
    def __init__(self, dati):
        self.dati = dati

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, n=-1):
        return self.dati if n < 0 else self.dati[:n]


class FinteRete:
    """Finto Project Gutenberg: indirizzo -> contenuto (o errore). Ricorda cosa è stato chiesto."""
    def __init__(self, **pagine):
        self.pagine, self.richieste = pagine, []

    def __call__(self, richiesta, timeout=30):
        url = richiesta.full_url
        self.richieste.append(url)
        for pezzo, contenuto in self.pagine.items():
            if pezzo in url:
                if isinstance(contenuto, Exception):
                    raise contenuto
                return _Risposta(contenuto if isinstance(contenuto, bytes) else contenuto.encode())
        raise urllib.error.HTTPError(url, 404, "non trovato", {}, None)


def epub(testo_pagina):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("OEBPS/c1.xhtml", f"<html><body><p>{testo_pagina}</p></body></html>")
    return b.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)

    def ctx(self, llm=None, token=""):
        c = costruisci(llm=llm or FinteRisposte(), home=self.home, movimenti=self.home / "n.db", token=token)
        self.addCleanup(c.db.c.close)
        return c


class TestCaricoDellUtente(Base):
    def test_un_libro_caricato_entra_in_cartella_e_nell_elenco(self):
        c = self.ctx()
        nome = c.ada.studio.aggiungi_libro("Il metodo.txt", TESTO_LUNGO.encode())
        self.assertEqual(nome, "Il metodo.txt")
        self.assertEqual(c.ada.studio.elenco_libri(), [{"nome": "Il metodo.txt", "percentuale": 0}])
        self.assertTrue((self.home / "libri" / "Il metodo.txt").is_file())

    def test_il_nome_non_puo_uscire_dalla_cartella(self):
        c = self.ctx()
        for cattivo in ("../../etc/passwd.txt", "/tmp/x/evil.md", "..\\..\\win.txt", ".nascosto.txt"):
            c.ada.studio.aggiungi_libro(cattivo, TESTO_LUNGO.encode())
        nomi = sorted(f.name for f in (self.home / "libri").iterdir())
        self.assertEqual(nomi, ["evil.md", "nascosto.txt", "passwd.txt", "win.txt"])
        self.assertFalse((self.home.parent / "passwd.txt").exists())

    def test_formati_e_file_non_validi_si_rifiutano_con_parole_chiare(self):
        c = self.ctx()
        s = c.ada.studio
        with self.assertRaisesRegex(ValueError, "Formato non leggibile"):
            s.aggiungi_libro("libro.pdf", b"%PDF-1.7 " + b"x" * 500)
        with self.assertRaisesRegex(ValueError, "Non riesco a leggere il testo"):
            s.aggiungi_libro("vuoto.txt", b"  \n ")
        with self.assertRaisesRegex(ValueError, "non è un epub valido"):
            s.aggiungi_libro("falso.epub", b"non e uno zip " * 50)
        with self.assertRaisesRegex(ValueError, "protetto"):
            s.aggiungi_libro("drm.epub", epub("troppo corto"))
        self.assertEqual(list((self.home / "libri").iterdir()), [])  # niente scarti rimasti in cartella

    def test_un_epub_vero_si_accetta_e_un_doppione_no(self):
        c = self.ctx()
        s = c.ada.studio
        s.aggiungi_libro("storia.epub", epub(TESTO_LUNGO))
        with self.assertRaisesRegex(ValueError, "C'è già un libro"):
            s.aggiungi_libro("storia.epub", epub(TESTO_LUNGO))

    def test_c_e_un_massimo_di_libri(self):
        c = self.ctx()
        with mock.patch.object(studio, "MAX_LIBRI", 2):
            c.ada.studio.aggiungi_libro("a.txt", TESTO_LUNGO.encode())
            c.ada.studio.aggiungi_libro("b.txt", TESTO_LUNGO.encode())
            with self.assertRaisesRegex(ValueError, "Ci sono già 2 libri"):
                c.ada.studio.aggiungi_libro("c.txt", TESTO_LUNGO.encode())

    def test_togliere_un_libro_cancella_file_e_progresso(self):
        c = self.ctx()
        s = c.ada.studio
        s.aggiungi_libro("a.txt", TESTO_LUNGO.encode())
        s._imposta("libro:a.txt", {"offset": 100, "totale": 800})
        s.rimuovi_libro("a.txt")
        self.assertEqual((s.libri(), s._kv("libro:a.txt")), ([], None))
        with self.assertRaises(LookupError):
            s.rimuovi_libro("a.txt")
        with self.assertRaises(LookupError):
            s.rimuovi_libro("../a.txt")

    def test_il_messaggio_senza_libri_manda_all_app(self):
        c = self.ctx()
        m = c.ada.studio.lettura()
        self.assertIn("Aggiungi un libro", m)
        self.assertIn("metti file .txt, .md o .epub", m)


class TestProjectGutenberg(Base):
    def studio_con(self, **pagine):
        c = self.ctx()
        c.ada.studio.apri = FinteRete(**pagine)
        return c

    def test_la_ricerca_legge_titolo_autore_e_id(self):
        c = self.studio_con(**{"ebooks/search": RICERCA})
        trovati = c.ada.studio.cerca_pubblici("sun tzu")
        self.assertEqual(trovati, [(132, "The Art of War", "Sunzi, 6th century B.C."), (1232, "Il Principe & altri scritti", "Machiavelli, Niccolò")])

    def test_con_la_lingua_prova_prima_quella_poi_senza(self):
        rete = FinteRete(**{"ebooks/search": "<html>nessun risultato</html>"})
        c = self.ctx()
        c.ada.studio.apri = rete
        self.assertEqual(c.ada.studio.cerca_pubblici("principe", "it"), [])
        self.assertEqual(len(rete.richieste), 2)
        self.assertIn("l.it", rete.richieste[0])
        self.assertNotIn("l.it", rete.richieste[1])

    def test_senza_parole_da_cercare_si_dice(self):
        c = self.studio_con()
        with self.assertRaisesRegex(ValueError, "cosa cercare"):
            c.ada.studio.cerca_pubblici(" ")

    def test_lo_scarico_toglie_la_presentazione_e_da_il_titolo_al_file(self):
        c = self.studio_con(**{"pg132.txt": LIBRO})
        nome = c.ada.studio.scarica_pubblico(132)
        self.assertEqual(nome, "The Art of War - Sun Tzu.txt")
        scritto = (self.home / "libri" / nome).read_text(encoding="utf-8")
        self.assertEqual(scritto, TESTO_LUNGO.strip())
        self.assertNotIn("Licenza", scritto)
        self.assertNotIn("START OF", scritto)

    def test_se_il_testo_non_c_e_si_prova_l_epub(self):
        c = self.studio_con(**{"132.epub": epub(TESTO_LUNGO)})
        self.assertEqual(c.ada.studio.scarica_pubblico(132), "gutenberg-132.epub")

    def test_se_non_c_e_niente_si_dice_chiaramente(self):
        c = self.studio_con(**{"pg9.txt": urllib.error.URLError("rete assente")})
        with self.assertRaisesRegex(ValueError, "Non riesco a scaricare"):
            c.ada.studio.scarica_pubblico(9)
        with self.assertRaisesRegex(ValueError, "non valido"):
            c.ada.studio.scarica_pubblico(0)

    def test_scarica_solo_da_gutenberg_in_https(self):
        for ok in ("https://www.gutenberg.org/ebooks/1", "https://gutenberg.org/x", "https://aleph.gutenberg.org/1/1.txt"):
            _controlla_indirizzo(ok)
        for no in ("http://www.gutenberg.org/x", "https://gutenberg.org.evil.com/x", "https://evilgutenberg.org/x",
                   "https://www.libri-pirata.example/48-leggi.epub", "file:///etc/passwd", "ftp://gutenberg.org/x"):
            with self.assertRaises(ValueError, msg=no):
                _controlla_indirizzo(no)
        with self.assertRaises(ValueError):
            studio._apri_gutenberg(urllib.request.Request("https://www.example.com/libro.epub"))

    def test_un_reindirizzamento_fuori_da_gutenberg_si_ferma(self):
        gestore = studio._SoloGutenberg()
        richiesta = urllib.request.Request("https://www.gutenberg.org/ebooks/1.txt.utf-8")
        with self.assertRaises(ValueError):
            gestore.redirect_request(richiesta, None, 302, "Found", {}, "https://sito-pirata.example/libro.txt")

    def test_senza_intestazione_se_i_segni_mancano_resta_il_testo(self):
        self.assertEqual(senza_intestazione_gutenberg("  solo testo  "), "solo testo")


class TestStrumentiDiAda(Base):
    def test_solo_ada_ha_gli_strumenti_dei_libri(self):
        for chi in ("ada",):
            nomi = [t["name"] for t in strumenti_di(chi)]
            self.assertIn("libri_cerca", nomi)
            self.assertIn("libro_scarica", nomi)
        for chi in ("acquisti", "quotidiano", "clienti_vendite", "revisore", "contabilita_piva", "collaudatore"):
            nomi = [t["name"] for t in strumenti_di(chi)]
            self.assertNotIn("libro_scarica", nomi)
            self.assertNotIn("libri_cerca", nomi)

    def test_ada_cerca_e_scarica_con_gli_strumenti(self):
        c = self.ctx()
        c.ada.studio.apri = FinteRete(**{"ebooks/search": RICERCA, "pg132.txt": LIBRO})
        r = c.ada._esegui("ada", "libri_cerca", {"cosa": "sun tzu"})
        self.assertIn("id 132: The Art of War, di Sunzi", r)
        self.assertIn("libro_scarica", r)
        r = c.ada._esegui("ada", "libro_scarica", {"id": 132})
        self.assertIn("The Art of War - Sun Tzu.txt", r)
        self.assertEqual([x["nome"] for x in c.ada.studio.elenco_libri()], ["The Art of War - Sun Tzu.txt"])

    def test_se_gutenberg_non_risponde_o_non_c_e_il_libro_lo_dice_senza_inventare(self):
        c = self.ctx()
        c.ada.studio.apri = FinteRete(**{"ebooks/search": urllib.error.URLError("rete assente")})
        self.assertIn("non risponde", c.ada._esegui("ada", "libri_cerca", {"cosa": "sun tzu"}))
        c.ada.studio.apri = FinteRete(**{"ebooks/search": "<html>vuoto</html>"})
        r = c.ada._esegui("ada", "libri_cerca", {"cosa": "le 48 leggi del potere"})
        self.assertIn("solo libri di pubblico dominio", r)
        self.assertIn("carica", r)

    def test_non_si_scarica_oltre_il_massimo_e_l_errore_arriva_ad_ada(self):
        c = self.ctx()
        c.ada.studio.apri = FinteRete(**{"pg132.txt": LIBRO})
        with mock.patch.object(studio, "MAX_LIBRI", 0):
            r = c.ada._esegui("ada", "libro_scarica", {"id": 132})
        self.assertIn("Errore nello strumento libro_scarica", r)
        self.assertIn("toglierne qualcuno", r)


class TestCosaSaAda(Base):
    def test_ada_sa_di_avere_la_cartella_e_cosa_dire_dei_libri_con_copyright(self):
        self.assertIn("Non dire mai di non avere una cartella dei libri", CAPACITA)
        self.assertIn("Aggiungi un libro", CAPACITA)
        self.assertIn("pubblico dominio", CAPACITA)
        self.assertIn("Le 48 leggi del potere", CAPACITA)
        self.assertIn("non puoi scaricarlo da sola", CAPACITA)

    def test_il_contesto_elenca_i_libri_con_l_avanzamento(self):
        c = self.ctx()
        self.assertIn("LIBRERIA: vuota", c.ada._contesto("ada")[1])
        c.ada.studio.aggiungi_libro("Il metodo.txt", TESTO_LUNGO.encode())
        c.ada.studio._imposta("libro:Il metodo.txt", {"offset": 400, "totale": 800})
        self.assertIn("LIBRERIA: Il metodo.txt (50% letto)", c.ada._contesto("ada")[1])
        self.assertNotIn("LIBRERIA", c.ada._contesto("revisore")[1])

    def test_il_contesto_con_tanti_libri_resta_corto(self):
        c = self.ctx()
        for i in range(11):
            (self.home / "libri" / f"l{i:02d}.txt").write_text(TESTO_LUNGO, encoding="utf-8")
        linea = [r for r in c.ada._contesto("ada")[1].splitlines() if r.startswith("LIBRERIA")][0]
        self.assertIn("e altri 3", linea)


class TestSceltaAutonoma(Base):
    def lettura(self, c):
        return c.pian._lettura(False)

    def test_senza_libri_ada_se_ne_sceglie_uno_di_pubblico_dominio(self):
        llm = FinteRisposte(usa("libri_cerca", cosa="art of war", lingua="en"), usa("libro_scarica", id=132),
                            testo("Ho scelto «The Art of War» di Sun Tzu: strategia e preparazione, utili nelle trattative."))
        c = self.ctx(llm)
        c.ada.studio.apri = FinteRete(**{"ebooks/search": RICERCA, "pg132.txt": LIBRO})
        esito = self.lettura(c)
        self.assertIn("Nuovo libro scelto da Ada", esito)
        self.assertEqual([x["nome"] for x in c.ada.studio.elenco_libri()], ["The Art of War - Sun Tzu.txt"])
        self.assertEqual(llm.chiamate[0]["strumenti"], ["aggiungi_regola_prompt", "proponi_idea", "libri_cerca", "libro_scarica"])
        self.assertIn("pubblico dominio", llm.chiamate[0]["ultimo"]["content"])
        self.assertIn("non vanno presi da altre parti", llm.chiamate[0]["ultimo"]["content"])
        (a,) = c.db.tutti("SELECT tipo, titolo FROM appunti")
        self.assertEqual((a["tipo"], a["titolo"]), ("lettura", "Nuovo libro scelto da Ada"))

    def test_non_ne_sceglie_uno_nuovo_prima_di_venti_ore(self):
        llm = FinteRisposte(testo("Ho scelto un libro."))
        c = self.ctx(llm)
        c.ada.studio.apri = FinteRete()
        self.assertIn("Nuovo libro scelto da Ada", self.lettura(c))
        self.assertIn("Nessun libro da leggere", self.lettura(c))  # nessuna seconda chiamata al modello: la sua lista è finita
        self.assertEqual(len(llm.chiamate), 1)

    def test_se_ci_sono_libri_da_leggere_non_sceglie_niente(self):
        llm = FinteRisposte(testo("Parla di strategia."), testo("Parla di strategia."))
        c = self.ctx(llm)
        c.ada.studio.aggiungi_libro("a.txt", TESTO_LUNGO.encode())
        self.assertIn("Lettura: a", self.lettura(c))
        self.assertEqual(len(llm.chiamate), 1)
        self.assertIsNone(c.ada.studio._kv("libri_scelta_ts"))

    def test_con_la_cartella_piena_non_sceglie(self):
        llm = FinteRisposte()
        c = self.ctx(llm)
        with mock.patch.object(studio, "MAX_LIBRI", 0):
            self.assertIn("Nessun libro da leggere", self.lettura(c))
        self.assertEqual(llm.chiamate, [])


class TestServerLibri(ClienteHTTP):
    def carica(self, nome, dati, token=None):
        h = {"Content-Type": "application/octet-stream"}
        if token:
            h["Authorization"] = "Bearer " + token
        req = urllib.request.Request(f"{self.base}/api/libri?nome={urllib.request.quote(nome)}", data=dati, headers=h, method="POST")
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)

    def test_senza_token_non_si_toccano_i_libri(self):
        self.avvia(token="")
        codice, r = self.carica("a.txt", TESTO_LUNGO.encode())
        self.assertEqual(codice, 403)
        self.assertIn("token", r["errore"])
        self.assertEqual(self.chiama("/api/libri/rimuovi", {"nome": "a.txt"})[0], 403)

    def test_con_token_si_carica_si_vede_nello_stato_e_si_toglie(self):
        c = self.avvia(token="segreto")
        codice, r = self.carica("Il metodo.txt", TESTO_LUNGO.encode(), "segreto")
        self.assertEqual((codice, r["nome"], r["libri"]), (200, "Il metodo.txt", [{"nome": "Il metodo.txt", "percentuale": 0}]))
        self.assertEqual(self.chiama("/api/stato")[1]["libri"], [{"nome": "Il metodo.txt", "percentuale": 0}])
        codice, r = self.chiama("/api/libri/rimuovi", {"nome": "Il metodo.txt"})
        self.assertEqual((codice, r["libri"]), (200, []))
        self.assertEqual(self.chiama("/api/libri/rimuovi", {"nome": "Il metodo.txt"})[0], 404)

    def test_formato_sbagliato_e_file_troppo_grande_danno_un_errore_chiaro(self):
        self.avvia(token="segreto")
        codice, r = self.carica("libro.pdf", b"%PDF " + b"x" * 400, "segreto")
        self.assertEqual(codice, 400)
        self.assertIn("Formato non leggibile", r["errore"])
        with mock.patch("src.ada.server.MAX_CARICO", 1000):
            codice, r = self.carica("grande.txt", b"x" * 5000, "segreto")
        self.assertEqual(codice, 400)
        self.assertIn("troppo grande", r["errore"])


if __name__ == "__main__":
    unittest.main()
