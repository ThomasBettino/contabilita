# Dalle idee di Ada al codice (GitHub)

Il percorso, con te che hai sempre l'ultima parola:

1. Ada propone una funzione nuova → tu la **approvi** in *Approva*.
2. Ada apre su GitHub un **problema** (issue) con l'etichetta `idea-ada` e il testo dell'idea.
3. L'azione `.github/workflows/claude.yml` fa partire Claude, che prepara la modifica.
4. Tu **rivedi la modifica su GitHub** e la unisci (o la rifiuti). Senza il tuo ok non entra niente.
5. In Ada: *Registro, Sviluppo e aggiornamenti, **Aggiorna Ada***. Scarica la versione nuova, **fa girare i test** e, se non passano, **torna da sola alla versione di prima**.

## Da fare una volta sola

### A. Sul repository (comodo dal PC)
1. **Unire il ramo di lavoro nel ramo principale.** Oggi il ramo principale contiene solo il file zip. GitHub legge i file di automazione solo dal ramo principale, e l'azione parte da lì: senza il codice di Ada non ha su cosa lavorare.
2. **Installare l'app Claude sul repository**: da Claude Code scrivi `/install-github-app`, oppure da github.com/apps/claude, *Install*, scegliendo solo il repository `contabilita`.
3. **Aggiungere la chiave**: nel repository, *Settings, Secrets and variables, Actions, New repository secret*, nome `ANTHROPIC_API_KEY`. Meglio una chiave dedicata, con un limite di spesa nella console di Anthropic.

### B. Il codice di accesso per Ada
GitHub, *Settings, Developer settings, Personal access tokens, Fine-grained tokens, Generate new token*:
- *Repository access*: **Only select repositories**, solo `contabilita`.
- *Permissions, Repository*: **Issues: Read and write**. Nient'altro.
- Scadenza: 90 giorni.

Poi in Ada: *Registro, Sviluppo e aggiornamenti*: incolla `proprietario/contabilita` e il codice, tocca **Collega GitHub**. Ada prova il collegamento prima di salvare e ti avvisa se il repository è **pubblico** (le idee sarebbero visibili a tutti). Come per le fatture, serve prima il token di accesso di Ada (`docs/FATTURE.md`, passo 1).

### C. Il ramo sul telefono
Dopo l'unione nel ramo principale, in Termux:
```
cd ~/contabilita
git checkout main
git pull
```
Da quel momento *Aggiorna Ada* segue il ramo principale.

## Cosa protegge
- **Il codice di Ada** può solo aprire problemi su quel repository: niente codice, niente segreti, niente altri repository.
- **Dati personali**: Ada non può proporre idee con importi, email, IBAN o numeri lunghi, perché un problema può essere pubblico.
- **L'azione** parte solo da problemi con l'etichetta `idea-ada` o da commenti con `@claude`, e di norma solo per chi ha accesso in scrittura al repository.
- **La modifica entra solo se la approvi tu** su GitHub.
- **Aggiorna Ada** non modifica nulla senza il token di accesso, usa solo avanzamento semplice (nessuna sovrascrittura), collauda con i test e torna indietro se falliscono.
- **I confini di sicurezza** (soldi, tasto finale, schermo) sono richiamati nelle istruzioni dell'idea: la modifica non deve toccarli. Quando rivedi, guarda che non compaiano nei file cambiati: `src/telefono/guardiano.py` e `REGOLE` in `src/ada/agenti.py`.

## Cosa non so con certezza
- L'azione `anthropics/claude-code-action@v1` può chiedere un permesso o un'impostazione in più: se il primo problema non produce nulla, guarda la scheda *Actions* del repository, c'è scritto perché.
- A volte Claude non apre la richiesta di unione da solo ma lascia nel problema un collegamento "Create PR": basta toccarlo.
- Ogni idea realizzata consuma credito sulla chiave `ANTHROPIC_API_KEY` del repository.
