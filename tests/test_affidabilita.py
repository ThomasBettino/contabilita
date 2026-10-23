import json
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

from src.ada import cervello
from src.ada.server import costruisci, crea_server
from tests.test_ada import FinteRisposte, testo, usa


def troncata(t="Faccio ora la modifica al mio prompt."):
    return {"stop_reason": "max_tokens", "content": [{"type": "text", "text": t}]}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def ctx(self, llm):
        c = costruisci(llm=llm, home=Path(self.tmp.name), movimenti=Path(self.tmp.name) / "n.db", token="")
        self.addCleanup(c.db.c.close)
        return c


class TestRispostaTagliata(Base):
    def test_si_riprova_con_piu_spazio_e_la_chiamata_riesce(self):
        prompt_lungo = "# Revisore\n" + "Controlla i totali con la massima attenzione. " * 40
        llm = FinteRisposte(troncata(), usa("migliora_prompt", agente="revisore", nuovo_prompt=prompt_lungo, motivo="riscrittura"),
                            testo("Fatto: la modifica è in attesa del tuo ok."))
        c = self.ctx(llm)
        self.assertIn("in attesa", c.ada.chiacchiera("migliora il revisore"))
        self.assertEqual([x["max_tokens"] for x in llm.chiamate], [cervello.MAX_TOKEN, cervello.MAX_TOKEN_RIPROVA, cervello.MAX_TOKEN_RIPROVA])
        self.assertEqual(c.db.uno("SELECT COUNT(*) AS n FROM approvazioni WHERE tipo='prompt'")["n"], 1)  # la chiamata è arrivata davvero

    def test_se_resta_troppo_lunga_lo_dice_senza_promettere(self):
        c = self.ctx(FinteRisposte(troncata(), troncata()))
        r = c.ada.chiacchiera("riscrivi tutto")
        self.assertIn("interrotta perché troppo lunga", r)
        self.assertIn("non ho potuto completare", r)
        self.assertTrue(any("troppo lunga" in (a["dettaglio"] or "") for a in c.db.tutti("SELECT dettaglio FROM attivita")))

    def test_spazio_di_base_adatto_ai_prompt_interi(self):
        self.assertGreaterEqual(cervello.MAX_TOKEN, 4096)
        llm = FinteRisposte(testo("ok"))
        self.ctx(llm).ada.chiacchiera("ciao")
        self.assertEqual(llm.chiamate[0]["max_tokens"], cervello.MAX_TOKEN)


class TestPromessaSenzaAzione(Base):
    def test_se_promette_senza_agire_viene_rimandata_a_farlo(self):
        llm = FinteRisposte(testo("Hai ragione. Lo faccio adesso."),
                            usa("aggiungi_regola_prompt", agente="revisore", regola="Controlla sempre gli arrotondamenti a due decimali.", motivo="errore"),
                            testo("Fatto: ho aggiunto la regola al revisore."))
        c = self.ctx(llm)
        self.assertIn("ho aggiunto la regola", c.ada.chiacchiera("dovevi averlo già fatto"))
        self.assertIn("non hai chiamato nessuno strumento", llm.chiamate[1]["ultimo"]["content"])
        self.assertIn("Controlla sempre gli arrotondamenti", c.squadra.prompt("revisore"))

    def test_una_sola_spinta_poi_si_fida(self):
        llm = FinteRisposte(testo("Lo faccio adesso."), testo("Lo faccio subito, davvero."))
        c = self.ctx(llm)
        self.assertEqual(c.ada.chiacchiera("fallo"), "Lo faccio subito, davvero.")
        self.assertEqual(len(llm.chiamate), 2)  # niente cicli infiniti

    def test_nessuna_spinta_se_non_promette(self):
        llm = FinteRisposte(testo("Oggi non c'è nulla da migliorare."))
        self.ctx(llm).ada.chiacchiera("come va?")
        self.assertEqual(len(llm.chiamate), 1)

    def test_riconosce_le_frasi_viste_nello_screenshot(self):
        for frase in ("Faccio ora la modifica al mio prompt.", "Lo faccio adesso.", "La faccio partire adesso.",
                      "Procedo subito con il cambiamento.", "Mi metto al lavoro."):
            self.assertTrue(cervello.PROMESSA.search(frase), frase)
        for frase in ("Ho fatto la modifica.", "Se vuoi lo faccio domani.", "Il telefono resta scollegato."):
            self.assertFalse(cervello.PROMESSA.search(frase), frase)


class TestRispostaMaiVuota(Base):
    def test_testo_vuoto_dopo_gli_strumenti_racconta_cosa_e_stato_fatto(self):
        vuota = {"stop_reason": "end_turn", "content": []}
        llm = FinteRisposte(usa("stato_sistema"), vuota)
        r = self.ctx(llm).ada.chiacchiera("controlla")
        self.assertTrue(r.startswith("Ho eseguito: stato_sistema"))

    def test_senza_strumenti_e_senza_testo(self):
        r = self.ctx(FinteRisposte({"stop_reason": "end_turn", "content": []})).ada.chiacchiera("ciao")
        self.assertEqual(r, "Ho finito, ma non ho nulla da riferire.")


class TestAggiungiRegolaPrompt(Base):
    def regola(self, c, testo_regola, agente="revisore"):
        return c.ada._esegui("ada", "aggiungi_regola_prompt", {"agente": agente, "regola": testo_regola, "motivo": "errore osservato"})

    def test_aggiunge_la_sezione_poi_le_regole_di_seguito(self):
        c = self.ctx(FinteRisposte())
        self.assertIn("applicata subito", self.regola(c, "Controlla sempre gli arrotondamenti a due decimali."))
        p = c.squadra.prompt("revisore")
        self.assertIn("## Regole imparate\n- Controlla sempre gli arrotondamenti a due decimali.", p)
        self.regola(c, "Segnala le date fuori dal mese richiesto nel risultato.")
        p = c.squadra.prompt("revisore")
        self.assertEqual(p.count("## Regole imparate"), 1)
        self.assertLess(p.index("arrotondamenti"), p.index("date fuori"))

    def test_la_regola_va_dentro_la_sezione_anche_se_dopo_ce_n_e_un_altra(self):
        c = self.ctx(FinteRisposte())
        c.squadra.scrivi("revisore", "# Revisore\n\n" + "Ricontrolli il lavoro. " * 5 + "\n\n## Regole imparate\n- Prima regola già presente nel testo.\n\n## Formato\nUna riga di sintesi.\n")
        self.regola(c, "Una seconda regola che deve restare nella sua sezione.")
        p = c.squadra.prompt("revisore")
        self.assertLess(p.index("seconda regola"), p.index("## Formato"))

    def test_si_annulla_come_ogni_miglioramento(self):
        c = self.ctx(FinteRisposte())
        prima = c.squadra.prompt("revisore")
        self.regola(c, "Controlla sempre gli arrotondamenti a due decimali.")
        c.ada.annulla(c.db.uno("SELECT id FROM miglioramenti")["id"])
        self.assertEqual(c.squadra.prompt("revisore").strip(), prima.strip())

    def test_limiti_e_duplicati(self):
        c = self.ctx(FinteRisposte())
        self.assertIn("tra 15 e 300", self.regola(c, "troppo corta"))
        self.assertIn("tra 15 e 300", self.regola(c, "x" * 301))
        self.assertIn("sconosciuto", self.regola(c, "Una regola abbastanza lunga da essere valida.", agente="../etc"))
        self.regola(c, "Controlla sempre gli arrotondamenti a due decimali.")
        self.assertIn("c'è già", self.regola(c, "Controlla sempre gli arrotondamenti a due decimali."))

    def test_resta_dentro_il_tetto_delle_modifiche_piccole_del_giorno(self):
        c = self.ctx(FinteRisposte())
        for i in range(cervello.MAX_PICCOLE_24H):
            self.assertIn("applicata subito", self.regola(c, f"Regola numero {i} per il controllo dei totali mensili."))
        self.assertIn("serve l'ok", self.regola(c, "Un'altra regola oltre il tetto giornaliero delle modifiche."))

    def test_solo_ada_la_usa(self):
        c = self.ctx(FinteRisposte())
        self.assertEqual(c.ada._esegui("revisore", "aggiungi_regola_prompt", {"agente": "revisore", "regola": "x" * 20, "motivo": "m"}),
                         "Strumento non consentito.")


class TestVedereIlLavoro(Base):
    def test_passo_corrente_e_endpoint_lavori(self):
        visto = {}
        c = self.ctx(FinteRisposte())

        class Spia(FinteRisposte):
            def __call__(inner, system, messaggi, strumenti=None, max_tokens=1500):
                r = super().__call__(system, messaggi, strumenti, max_tokens)
                if len(inner.chiamate) == 1:
                    return usa("stato_sistema")
                visto["durante"] = dict(c.ada.lavori.get("ada", {}))
                return r
        c.ada.llm = Spia(testo("ok"), testo("fatto"))
        srv = crea_server(c, "127.0.0.1", 0)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        self.addCleanup(srv.server_close)
        c.ada.chiacchiera("controlla")
        self.assertEqual(visto["durante"]["passo"], "stato_sistema")
        self.assertEqual(visto["durante"]["cosa"], "Sto rispondendo alla tua chat")
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        self.assertEqual(json.load(urllib.request.urlopen(base + "/api/lavori")), {"lavori": []})  # a lavoro finito è vuoto
        c.ada.lavori["revisore"] = {"cosa": "Ricontrollo i totali", "da": 1, "passo": "riepilogo_spese"}
        l = json.load(urllib.request.urlopen(base + "/api/lavori"))["lavori"]
        self.assertEqual((l[0]["titolo"], l[0]["cosa"], l[0]["passo"]), ("Revisore", "Ricontrollo i totali", "riepilogo_spese"))


if __name__ == "__main__":
    unittest.main()
