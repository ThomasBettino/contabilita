# Progetto: sistema di assistenti AI auto-migliorante

Stato: **bozza v2, da approvare**. Nessun codice scritto finché non approvi questo documento.

## 0. Revisione v2: da moduli a "persona digitale"

Richiesta aggiornata: non un insieme di script che preparano il lavoro, ma un agente **autonomo e con propria intelligenza**, che fa tutto ciò che faresti tu con il telefono in mano.

Decisioni:
- **Telefono:** Android. L'agente comanda lo schermo (tocca, scrive, apre app, legge) su un telefono dedicato o un emulatore Android, tramite Claude con controllo del dispositivo.
- **Autonomia:** libero su tutto **tranne i soldi**. Email, WhatsApp, calendario, app, archivio, cancellazioni e modifiche: lo fa da solo. **Ogni pagamento o movimento di denaro chiede sempre il tuo ok** sul telefono.
- **Architettura:** un solo agente principale ("Io digitale") che ragiona, pianifica e usa il telefono. Gli assistenti specializzati diventano **competenze/sotto-agenti** che il Capo richiama quando servono. Il ciclo di auto-miglioramento resta.
- **Limiti da conoscere:** le app bancarie possono bloccare l'uso automatico; un errore su azioni non reversibili (messaggio inviato, dato cancellato) non si annulla. Per questo la cancellazione di dati importanti e la modifica di documenti fiscali restano tracciate con copia di sicurezza prima di ogni modifica.

- **Dispositivo:** il tuo telefono personale. Rischi: l'agente vede tutto (chat, foto) e può intralciare l'uso normale. Mitigazioni: tasto di arresto immediato, log di ogni azione, lavoro in momenti che scegli tu.
- **Attivazione:** sempre attivo (controlla a intervalli fatture, notifiche, scadenze) e a comando (esegue subito ciò che gli scrivi su un canale di chat).

- **Ada e l'hub (costruito):** app web in `app/` servita da `src/ada/server.py`. Ada è il capo; la chat è la sua interfaccia, le altre schede mostrano team, approvazioni, registro e soldi. I confini sono nel codice: i pagamenti sono sempre solo richieste (nessun pagamento parte), le modifiche ai prompt si classificano per dimensione (piccole subito, grandi con ok), massimo 3 piccole al giorno per agente. I prompt vivi stanno in `~/ada/agenti/` con storico e annullamento nel database, al posto della cronologia git prevista all'inizio.

Dove questa sezione contraddice quelle sotto, vale questa.


## 1. Obiettivo

Un assistente "Capo" che coordina assistenti specializzati per gestire:

- contabilità P.IVA (fatture, registrazioni, scadenze fiscali, tasse da accantonare)
- contabilità privata (estratti conto, spese, spese fisse, entrate, dove risparmiare)
- gestione quotidiana (email, calendario, promemoria)
- sviluppo software (codice, test, revisioni)
- clienti e vendite (clienti, preventivi, solleciti)

Il sistema si migliora da solo: quando un assistente sbaglia o manca qualcosa, il Capo corregge il prompt di quell'assistente.

## 2. Scelte fatte

| Tema | Scelta |
|---|---|
| Autonomia del Capo | Modifiche piccole da solo, grandi con tuo ok |
| Azioni sempre con tuo ok | **Solo pagamenti e movimenti di denaro** (v2). Il resto è autonomo, con log e copie di sicurezza |
| Fonti di apprendimento | Tuoi feedback, test automatici, controllo incrociato, errori ricorrenti |
| Storico | Git + registro dei miglioramenti |
| Esecuzione | Processo schedulato (gira anche quando non ci sei) |
| Strumenti | File del repo, Gmail, Google Calendar, database, notifiche Revolut, WhatsApp, telefono |
| Complessità | Strutturata (codice vero, moduli, test, log) |
| Ordine di lavoro | Prima il progetto, poi il codice |

## 3. Architettura

```
                      Tu (approvazioni, feedback)
                               |
                         [ CAPO ]  <-- orchestratore + "meta-agente"
        ______________________|_______________________
       |          |            |           |           |
  Contabilità  Contabilità   Quotidiano  Sviluppo   Clienti
    P.IVA       privata      (mail,cal)   software   e vendite
       |__________|____________|___________|___________|
                               |
                        [ REVISORE ]  controlla il lavoro di tutti
                               |
                    Registro + Test + Storico git
```

### Ruoli

- **Capo**: riceve le richieste, le assegna all'assistente giusto, raccoglie i problemi e gestisce il ciclo di miglioramento (sezione 5).
- **Assistenti specializzati**: uno per ambito, ognuno con il proprio prompt in `agenti/<nome>/prompt.md` e i propri permessi.
- **Revisore**: ricontrolla il lavoro degli altri (somme, categorie, date, coerenza) e segnala errori al Capo. Non esegue mai azioni sui dati.
- **Guardiano dei permessi**: livello di codice, non di prompt, che blocca le azioni vietate finché non arriva il tuo ok.

## 4. Sicurezza e permessi

Le quattro azioni vietate in automatico (email, pagamenti, cancellazioni, documenti fiscali) sono imposte **dal codice**, non solo dai prompt. Un prompt sbagliato, o riscritto male dal Capo, non deve poter aggirarle.

- Ogni azione sensibile crea una **richiesta di approvazione**: cosa, perché, anteprima.
- L'azione parte solo dopo il tuo ok (notifica sul telefono con tasto di conferma).
- Gli assistenti lavorano con permessi minimi: lettura di default, scrittura solo dove serve.
- **Il Capo non può modificare** il Guardiano dei permessi né le regole di sicurezza. Può modificare solo i prompt degli assistenti.
- Dati personali e finanziari restano in repo/database privati. Nessun segreto nel codice (chiavi in variabili d'ambiente).

## 5. Ciclo di auto-miglioramento

1. **Rilevamento**: un problema emerge da una di quattro fonti:
   - tuo feedback ("questo è sbagliato")
   - test automatici falliti
   - segnalazione del Revisore
   - stesso errore ripetuto più volte
2. **Diagnosi**: il Capo capisce se la causa è nel prompt (istruzione mancante o ambigua), negli strumenti o nei dati.
3. **Proposta**: il Capo scrive la modifica al prompt con motivo ed esempio.
4. **Classificazione**:
   - *piccola* (precisazione, esempio, regola di formato su un solo assistente): applicata da sola
   - *grande* (cambia comportamento, tocca più assistenti, ruolo o permessi): serve il tuo ok
5. **Verifica**: prima di salvare, si rilanciano i test. Se peggiorano, la modifica viene scartata.
6. **Registrazione**: commit git + riga in `registro_miglioramenti.md` (data, assistente, problema, modifica, esito test).
7. **Rollback**: se una modifica peggiora i risultati dopo il salvataggio, il Capo la annulla con `git revert` e lo annota.

## 6. Struttura proposta del repo

```
agenti/
  capo/prompt.md
  contabilita_piva/prompt.md
  contabilita_privata/prompt.md
  quotidiano/prompt.md
  sviluppo/prompt.md
  clienti_vendite/prompt.md
  revisore/prompt.md
src/
  orchestratore/      # smista le richieste, esegue gli assistenti
  miglioramento/      # ciclo della sezione 5
  permessi/           # Guardiano + richieste di approvazione
  strumenti/          # connettori (file, Gmail, Calendar, DB, Revolut, ...)
  pianificazione/     # lavori schedulati
tests/
  casi/               # casi di prova per ogni assistente
registro_miglioramenti.md
docs/PROGETTO-AGENTI.md
contabilita-app.zip   # app esistente "Contabilità Smart" (PWA)
```

## 7. Strumenti e collegamenti

| Strumento | Uso | Stato / nota |
|---|---|---|
| File del repo | Fatture, estratti conto, documenti | Facile, si parte da qui |
| Database | Movimenti, fatture, storico | Da scegliere (SQLite per iniziare) |
| Gmail | Leggere, preparare bozze | Invio sempre con tuo ok |
| Google Calendar | Scadenze, promemoria | Collegabile |
| Notifiche Revolut | Aggiornare i movimenti | **Da verificare**: vedi domande aperte |
| WhatsApp | Messaggi, canale di approvazione | **Da verificare**: vedi domande aperte |
| Telefono | Notifiche e conferme | Già c'è ntfy nell'app esistente |
| App "Contabilità Smart" | Fatture, Enasarco, netto, tasse da accantonare | Esistente: gli assistenti ne leggono e ne aggiornano i dati |

## 8. Fasi di lavoro

1. **Fase 0, questo documento**: approvazione di architettura e regole.
2. **Fase 1, fondamenta**: struttura repo, Guardiano dei permessi, registro, test di base.
3. **Fase 2, primo nucleo**: Capo + Contabilità P.IVA + Contabilità privata + Revisore, con il ciclo di miglioramento funzionante.
4. **Fase 3, collegamenti**: Gmail e Calendar, poi Revolut e WhatsApp se fattibili.
5. **Fase 4, allargamento**: Quotidiano, Clienti e vendite, Sviluppo.
6. **Fase 5, schedulazione**: esecuzione automatica periodica con report e approvazioni sul telefono.

Gli ambiti sono tanti: conviene costruirli uno alla volta, ognuno con i propri test, invece di tutti insieme.

## 9. Domande aperte

1. **Revolut**: le notifiche del telefono non sono leggibili da un sistema in cloud. Opzioni: esportare l'estratto conto (CSV) a mano o a cadenza fissa, oppure usare le API/Open Banking di Revolut Business, se hai un conto Business. Quale preferisci?
2. **WhatsApp**: serve un canale ufficiale (WhatsApp Business API) oppure basta usare ntfy/Telegram per le approvazioni?
3. **Regime fiscale**: sei in regime forfettario o ordinario? Cambia le regole di calcolo di tasse e scadenze.
4. **Dove gira il processo schedulato**: nel cloud di Claude o su un tuo computer/server? Per i dati finanziari è una scelta importante.
5. **Linguaggio**: Python o TypeScript/JavaScript? L'app esistente è in JavaScript.
6. **Dati sensibili**: il repo è privato? Dove vanno tenuti estratti conto e fatture reali?

## 10. Rischi principali

- **Errori fiscali**: gli assistenti non sostituiscono il commercialista. Calcoli e scadenze vanno verificati e il Revisore deve controllarli.
- **Deriva dei prompt**: tante piccole modifiche automatiche possono peggiorare il sistema. Mitigazione: test prima di ogni salvataggio, registro, rollback.
- **Privacy**: dati finanziari trattati con permessi minimi, niente segreti nel repo, accessi tracciati.
- **Troppo ambito insieme**: si parte da contabilità e si allarga per fasi.
