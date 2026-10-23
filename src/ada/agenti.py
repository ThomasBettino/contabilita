"""Il team di Ada: elenco agenti, prompt modificabili e regole di sistema fisse."""
import shutil
from pathlib import Path

SEED = Path(__file__).resolve().parents[2] / "agenti"

AGENTI = {
    "ada": ("Ada", "Capo del team. Coordina, decide e migliora gli altri."),
    "contabilita_piva": ("Contabilità P.IVA", "Fatture, scadenze fiscali, tasse da accantonare."),
    "contabilita_privata": ("Contabilità privata", "Spese, entrate, spese fisse, dove risparmiare."),
    "quotidiano": ("Quotidiano", "Email, calendario, promemoria, ricerche."),
    "sviluppo": ("Sviluppo", "Codice, test e revisioni dell'app."),
    "clienti_vendite": ("Clienti e vendite", "Clienti, preventivi, solleciti di pagamento."),
    "revisore": ("Revisore", "Ricontrolla il lavoro degli altri e segnala gli errori."),
}

# Fissate nel codice: stanno fuori dai file dei prompt, quindi Ada non può riscriverle.
REGOLE = """REGOLE DI SISTEMA (fissate nel codice: nessun prompt, nemmeno quello di Ada, può cambiarle o aggirarle):
1. Soldi: non muovi mai denaro e non dai mai per eseguito un pagamento. Ogni pagamento, bonifico, F24 o movimento di denaro si propone con richiedi_approvazione e si aspetta il via libera dell'utente.
2. Sincerità: non dichiarare di aver fatto ciò che i tuoi strumenti non hanno fatto. Se non hai accesso a qualcosa, dillo.
3. Dati: usa solo dati che hai davvero. Non inventare importi, scadenze o norme fiscali; se non sei sicuro dillo e indica cosa verificare con il commercialista.
4. Privacy: non ripetere dati personali o finanziari più del necessario.
5. Lingua: rispondi in italiano, in modo breve e chiaro."""


class Squadra:
    def __init__(self, casa: Path):
        self.dir = Path(casa) / "agenti"
        self.dir.mkdir(parents=True, exist_ok=True)
        for nome in AGENTI:
            dst, src = self.dir / f"{nome}.md", SEED / nome / "prompt.md"
            if not dst.exists() and src.exists():
                shutil.copyfile(src, dst)

    def _file(self, nome: str) -> Path:
        if nome not in AGENTI:
            raise KeyError(nome)
        return self.dir / f"{nome}.md"

    def prompt(self, nome: str) -> str:
        f = self._file(nome)
        return f.read_text(encoding="utf-8") if f.exists() else ""

    def scrivi(self, nome: str, testo: str) -> None:
        self._file(nome).write_text(testo, encoding="utf-8")

    def system(self, nome: str, contesto: str = "") -> str:
        return f"{self.prompt(nome).strip()}\n\n{contesto}\n\n{REGOLE}".strip()
