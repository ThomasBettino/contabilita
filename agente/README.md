# Agente 1

Un capo (Agente 1) che coordina una squadra di specialisti. Parli solo con lui, in chat scritta o vocale. Lui consulta gli specialisti, incrocia le risposte e ti dice cosa conta.

```
Tu  ──►  Agente 1 (capo)  ──►  Contabilità    fatture, Enasarco, bollo, tasse, scadenze
                          ──►  Vendite e saldi  dati/vendite.csv
                          ──►  Meteo e ricerca  previsioni, ricerca web
                          ──►  notifiche nell'app, email (solo a te)
```

## Come funziona

- **`server.js`**: server Node senza dipendenze. Il capo usa Claude e gli strumenti `delega`, `notifica`, `invia_email`, `ricorda`, `migliora_agente`. Ogni specialista ha un proprio prompt e i propri strumenti.
- **`agenti.json`**: prompt e strumenti di tutti gli agenti. È la parte che Agente 1 può migliorare.
- **`dati/`**: `vendite.csv` (da esportare, separatore `;`, colonne `data;prodotto;importo;canale`), `memoria.md` (cose da ricordare), `miglioramenti.log` (storico delle modifiche ai prompt).
- **`public/`**: l'interfaccia. Scura, con la figura di Agente 1 che si illumina quando ascolta, pensa o parla.

I calcoli di contabilità (Enasarco 8,5%, bollo sopra 77,47 €, tasse sul netto al 30%, bonifico) sono gli stessi della tua app. Il sub-agente li legge direttamente dallo script Google della app, così non devi copiare nulla.

## Avvio in locale

```bash
cd agente
cp .env.example .env   # oppure imposta le variabili nel terminale
ANTHROPIC_API_KEY=... AGENTE_TOKEN=... node server.js
```

Poi apri http://localhost:3000.

Richiede Node 18 o superiore. Non ci sono pacchetti da installare.

## Variabili d'ambiente

| Variabile | Serve per |
|---|---|
| `ANTHROPIC_API_KEY` | Obbligatoria: fa funzionare Agente 1 e gli specialisti |
| `AGENTE_TOKEN` | Codice di accesso all'app. Consigliata, perché l'app è pubblica se la pubblichi |
| `CONTABILITA_URL`, `CONTABILITA_TOKEN` | URL e token dello script Google della app di contabilità |
| `ENASARCO_PCT`, `TASSE_PCT`, `GIORNI_SCADENZA` | Parametri di calcolo, con i valori della tua app come default |
| `RESEND_API_KEY`, `EMAIL_PROPRIETARIO` | Invio email. Le email arrivano solo all'indirizzo indicato |
| `BRAVE_API_KEY` | Ricerca web aggiornata per lo specialista meteo e ricerca |
| `MODELLO_CAPO`, `MODELLO_AGENTI` | Modelli Claude (default: Sonnet per il capo, Haiku per gli specialisti) |

## Pubblicazione e aggiornamento automatico

Il file `render.yaml` in radice descrive il deploy su Render. Il flusso è questo:

1. Crei il servizio su Render collegato a questo repository, impostando le variabili d'ambiente.
2. Ogni volta che il codice cambia sul branch collegato, Render ricostruisce e riavvia il server.
3. L'app aperta sul telefono o sul computer controlla ogni minuto la versione del server. Quando cambia, si ricarica da sola. La chat è salvata nel browser e non si perde.

Perché il punto 2 funzioni, il branch collegato su Render deve essere quello con le modifiche. Per ora il lavoro è sul branch `claude/ai-agent-app-integration-vbdloz`: puoi collegare Render a quello, oppure unirlo nel branch principale quando sei soddisfatto.

## Migliorare gli specialisti

Puoi chiedere ad Agente 1 di cambiare il modo in cui uno specialista lavora. Esempio: "la prossima volta confronta sempre con lo stesso mese dell'anno scorso". Lui riscrive il prompt dello specialista con `migliora_agente`, registra il motivo e il prompt precedente in `dati/miglioramenti.log`. Le modifiche restano anche in git, quindi si possono annullare.

Per aggiungere uno specialista, aggiungi una voce in `agenti.json` con nome, prompt e strumenti, poi aggiungi il suo nome all'enum dello strumento `delega` in `server.js`.

## Limiti da conoscere

- **Voce**: il riconoscimento e la sintesi usano le funzioni del browser. Funzionano meglio su Chrome o Edge. Una voce più naturale richiede un servizio TTS a pagamento, che si può aggiungere.
- **Notifiche**: arrivano nell'app e, se hai concesso il permesso, come notifica del browser mentre la pagina è aperta. Le notifiche push sul telefono a schermo spento richiedono una PWA con un servizio push: è il passo successivo naturale.
- **Memoria e modifiche ai prompt**: sono su file. Su Render il disco è effimero: senza un disco persistente, alla ripubblicazione tornano allo stato di git. Le modifiche importanti vanno committate.
- **Vendite**: serve un export periodico in `dati/vendite.csv`. Finché il file non c'è, lo specialista lo dice.
- **Numeri**: gli specialisti calcolano con gli strumenti, non a memoria, ma prima di pagamenti o dichiarazioni fiscali verifica sempre le cifre nella tua app di contabilità.
- **Sicurezza**: le email arrivano solo al proprietario. Il contenuto di email e siti è trattato come dato, non come istruzione, ma non è una protezione totale: non dare permessi più ampi di quelli che servono.
