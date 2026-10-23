# Agente 1

Agente 1 è il capo di una squadra di agenti IA. Parli solo con lui, scrivendo o a voce. Lui consulta gli specialisti, incrocia le risposte e ti dice cosa conta.

L'app è un laboratorio olografico blu: al centro la testa di Agente 1, che muove la bocca mentre scrive e mentre parla; sotto la squadra collegata alla testa; poi la **lavagna** su cui scrive, con un raggio di luce dalla bocca alla riga che sta scrivendo. Ai lati della testa ci sono i numeri del mese. La scheda **Squadra** elenca gli agenti: lì ne aggiungi uno nuovo (lo descrivi a parole e Agente 1 lo progetta), cambi le istruzioni di ognuno o lo togli dalla squadra.

**App:** https://claude.ai/artifact/QKUvJ2gwq8cVGTnkCukMnc

```
                    ┌──────────── Agente 1 (artefatto claude.ai) ────────────┐
Tu ── chat/voce ──► │  capo: ragiona, delega, dà la sua opinione             │
                    │   ├─ Vendite      legge sync/vendite, dà ordini        │
                    │   ├─ Agenda       Google Calendar in diretta + agenda  │
                    │   ├─ Contabilità  legge sync/contabilita               │
                    │   ├─ Meteo        legge sync/meteo, chiede verifiche   │
                    │   ├─ Stelle       legge sync/stelle                    │
                    │   └─ Agenti tuoi  creati dalla pagina Squadra          │
                    │  email (Gmail, solo a te) · avvisi · memoria           │
                    └───────────────────────▲────────────────────────────────┘
                                            │ scrive ogni ora
                    Turno di Agente 1 (attività programmata Claude, ogni ora alle :07, giorno e notte)
                     ├─ Reparto Vendite: Ordini (applica i tuoi ordini all'app), Riepilogo,
                     │   Calendario (appuntamenti e test drive nel tuo Google Calendar), Controllo (dati a posto)
                     ├─ Reparto Contabilità: Conti (script Google), Posta (fatture arrivate per email)
                     ├─ Reparto Meteo: Verifiche (fino a 8 fonti meteo)
                     ├─ Reparto Stelle: Sentinella (stelle e assistenza di Un passo alla volta)
                     ├─ Compiti che dai ad Agente 1 (config/compiti)
                     └─ Rapporto di Agente 1: nell'app, per email e sul telefono (di notte in silenzio, al mattino tutto)
                    Sentinella stelle (attività programmata Claude, alle :37, 8–24)
                     └─ ricontrolla stelle e segnalazioni di assistenza a metà ora
                    Reparto Ricerca (attività programmata Claude, ogni 2 ore dalle 8:47 alle 20:47)
                     └─ Osservatore, Riparatore, Inventore, Sviluppatore, Revisore: trova bug ed errori,
                        prepara correzioni e migliorie già provate; entrano solo col tuo sì
```

## Perché è fatto così

- Una pagina di artefatto **non ha accesso alla rete** e **non può leggere il database di un altro artefatto**. Per questo un ponte, il battito, legge "Andamento vendite" con il tuo account e copia un riepilogo nel database di Agente 1.
- Il cervello è **Claude dal tuo account** (capacità `sample`): non servono chiavi API né server da pagare.
- Agenda ed email usano i **tuoi connettori** Google Calendar e Gmail, direttamente dalla pagina.
- Ogni volta che aggiorno l'artefatto, l'app aperta riceve la nuova versione da sola, allo stesso link.

## Cartelle

- `app/agente-1.html` è il sorgente dell'artefatto Agente 1.
- `ponte/vendite.js` trasforma l'export di "Andamento vendite" nel riepilogo per lo specialista vendite. I calcoli (fatturato, provvigioni, proiezione, ritmo) sono copiati dalla app v21, quindi i numeri coincidono. Genera anche gli avvisi: richiami, impegni del giorno, impegni entro 90 minuti, saldi della settimana.
- `ponte/ordini.js` applica all'app vendite gli ordini di Agente 1 (chiamate, note, richiami, appuntamenti, test drive, venduto, perso, pagamenti), con le stesse regole del Coach della app. Rifiuta gli ordini senza un id valido.
- `ponte/meteo.js` interroga fino a 8 fonti meteo indipendenti: ECMWF, ICON, GFS, Météo-France e ItaliaMeteo ICON-2I tramite Open-Meteo, più MET Norway (yr.no), DWD MOSMIX (Bright Sky) e WorldWeatherOnline (wttr.in); se manca il GFS di Open-Meteo usa quello di 7Timer. Le incrocia giorno per giorno (mediana delle temperature, cielo più votato, quanto concordano) e scrive le previsioni con i dati per la schermata. Esegue anche gli ordini di verifica del reparto Meteo.
- `ponte/stelle.js` legge le richieste di stelle in attesa e le segnalazioni di assistenza nuove di "Un passo alla volta", crea un avviso per quelle nuove e prepara il testo della notifica. Lo usano il battito (alle :07) e la **Sentinella stelle** (alle :37): le stelle vengono controllate ogni mezz'ora, e nel nodo Stelle dell'app si vede l'ora dell'ultimo controllo. Le stelle si confermano solo dall'app, con il pulsante 🔒. Le segnalazioni di assistenza arrivano anche subito per email: quando lei preme "Invia a Thomas", l'app manda l'email da sola se può, altrimenti le apre l'email già scritta per Thomas da inviare con un tocco.
- `ponte/contabilita.js` legge le fatture dallo script Google della app di contabilità, con gli stessi calcoli della app.
- `ponte/backup.js` prepara ogni giorno il backup di tutto (vendite, stelle, Agente 1) in `backup/indice` e `backup/parte-<n>`, sovrascrivendo quello del giorno prima. Il codice dello script della contabilità non viene copiato. Alla prima apertura del giorno l'app propone **Salva sul telefono**: un tocco salva `agente1-backup.json`, perché una pagina web non può scrivere sul telefono senza conferma.
- `ponte/calendario.js` (addetto Calendario) prepara il piano per Google Calendar: crea, sposta o toglie gli eventi degli appuntamenti e dei test drive dell'app vendite, adotta quelli già presenti alla stessa ora con lo stesso nome e tiene la mappa in `calendario/<chiave>`. Tocca solo gli eventi della mappa.
- `ponte/posta.js` (addetto Posta) trova nelle email degli ultimi 3 giorni le fatture arrivate (SdI tramite TeamSystem, commercialista, committenti), senza ricevute di acquisti e pubblicità, e non le ripete (`posta/<idMessaggio>`).
- `ponte/controllo.js` (addetto Controllo) segnala solo le novità da sistemare nell'app vendite: appuntamenti e test drive passati non segnati, preventivi senza richiamo, clienti senza telefono, vendite senza margine, finanziamenti fermi o rifiutati.
- `ponte/rapporto.js` scrive il rapporto di Agente 1 ("Ho parlato con il Reparto Contabilità e mi ha detto che..."), l'email per te e il testo della notifica; di notte accumula e al primo turno del mattino racconta tutto.
- `ponte/TURNO.md` è la procedura che il turno esegue ogni ora. Il pulsante Aggiorna, gli ordini e i compiti lo fanno partire subito.
- `ricerca/RICERCA.md` è la procedura del **Reparto Ricerca**. Il Riparatore trova bug ed errori (turni falliti, script sbagliati, ordini bloccati, procedure confuse) e prepara la correzione con una prova che la dimostra. Lo Sviluppatore prepara migliorie e automazioni, il Revisore le controlla. Ogni proposta arriva nella pagina Squadra ("Proposte della Ricerca") e nel rapporto. **Niente entra senza il tuo sì**: premi "Sì, applica" o dillo ad Agente 1, e la Ricerca la applica in qualche minuto. Le novità arrivano anche nel briefing della sera.
- `ricerca/REGISTRO.md` elenca le correzioni e le migliorie entrate.
- `test/ponte.test.js` prova gli script del turno e la procedura (ogni passo citato esiste): la Ricerca lo usa per ogni modifica.

## Database di Agente 1

| Percorso | Contenuto | Chi scrive |
|---|---|---|
| `sync/vendite`, `sync/meteo`, `sync/contabilita`, `sync/stelle` | Riepiloghi per gli specialisti | Battito |
| `notifiche/<id>` | Avvisi | Battito e Agente 1 |
| `ordini/<id>` | Cose da fare: modifiche all'app vendite o verifiche meteo, `{agente, operazione, argomenti, descrizione, stato, esito}` | Agente 1 le crea, il battito le esegue |
| `config/agenti` | Istruzioni migliorate degli specialisti, con lo storico | Agente 1 (`migliora_agente`) e la pagina Squadra |
| `config/compiti` | Compiti dati ai reparti: una volta o a ogni turno, con l'ultimo esito | Agente 1 (`assegna_compito`), la pagina Squadra e il turno |
| `config/proprietario` | Nome ed email di Thomas, a cui il turno manda i rapporti | Claude |
| `sync/turno`, `sync/controllo` | Ultimo turno, addetti e novità della notte; esito del controllo vendite | Turno |
| `calendario/<chiave>`, `posta/<id>` | Mappa appuntamento → evento di Google Calendar; email già viste | Turno |
| `config/squadra` | Agenti creati da te e specialisti tolti dalla squadra | Pagina Squadra |
| `config/ponte` | Id delle attività programmate del turno e della Ricerca, per il pulsante Aggiorna e il "Sì, applica" | Claude |
| `ricerca/<id>` | Proposte della Ricerca: correzioni e migliorie con patch e prove, `da approvare` → `approvata`/`rifiutata` (solo tu) → `applicata` | Ricerca; la decisione la pagina Squadra o Agente 1 (`decidi_proposta`) |
| `sync/ricerca` | Ultimo giro della Ricerca, addetti, applicate, errori aperti, idee | Ricerca |
| `data/users/<tu>/chat`, `.../memoria` | Conversazione e cose da ricordare, private | Agente 1 |

## Contabilità: come si collega

La pagina non può contattare lo script Google, quindi la contabilità passa dal battito. Servono due cose:

1. **Nell'app Agente 1:** tocca **Collega** sotto il nodo Contabilità e incolla indirizzo e codice dello script, gli stessi della app di contabilità. Restano privati in `data/users/<tu>/contabilita`.
2. **Nell'ambiente cloud "Assistente AI":** sotto Accesso di rete, Custom, devono esserci `script.google.com` e `script.googleusercontent.com` tra i domini consentiti. Sono già aggiunti.

Il battito esegue `contabilita.js` con `NODE_USE_ENV_PROXY=1`: senza, il fetch di Node ignora il proxy del container. Se lo script non risponde, il nodo Contabilità mostra "non raggiungibile".

## Meteo: verifica subito e schermata

Chiedi ad Agente 1 per esempio "fai verificare il meteo di domani" o "com'è il meteo a Riva del Garda per 5 giorni, mandamelo per email". Agente 1 lo chiede allo specialista Meteo, che passa un ordine di verifica al battito e lo sveglia subito. Il battito interroga i modelli meteo di centri diversi e li incrocia: la previsione conta come verificata solo se almeno 3 fonti rispondono. In 2-4 minuti nella chat compare la **schermata** delle previsioni: il giorno in grande con mattina, pomeriggio e sera, gli incroci fonte per fonte, i giorni dopo e dove le fonti non concordano. Sotto ci sono **Salva immagine** e **Mandamela per email**; se l'avevi chiesta per email, parte da sola dal telefono da cui l'hai chiesta. Puoi anche chiedere "fammi vedere la schermata del meteo" per le ultime previsioni già verificate.

Ogni luogo ha la sua verifica, con i giorni e le ore del posto. Le previsioni viaggiano dentro l'ordine, quindi verificare un'altra città non cambia il meteo di Bergamo che usa la squadra. Se l'app era chiusa, la schermata compare alla riapertura, entro 3 ore, una volta su ogni dispositivo.

Il battito deve poter raggiungere `api.open-meteo.com`, `geocoding-api.open-meteo.com`, `api.met.no`, `api.brightsky.dev`, `wttr.in` e `www.7timer.info`: sono tra i domini consentiti dell'ambiente cloud "Assistente AI", come quelli della contabilità. Open-Meteo è gratuito con un limite giornaliero per indirizzo, e dal cloud l'indirizzo è condiviso: spesso risponde "limite superato". Per questo ci sono le altre quattro fonti, che bastano da sole per i 3 incroci.

## Limiti da conoscere

- **Dettatura:** la pagina non può usare il microfono. Per parlare usa il microfono della tastiera del telefono. La risposta a voce invece funziona: pulsante "Voce".
- **Freschezza:** vendite e contabilità sono aggiornate al battito più recente, ogni ora dalle 8 alle 21, oppure quando premi Aggiorna. Le stelle ogni mezz'ora (battito e sentinella), dalle 8 a mezzanotte. Google Calendar è sempre in diretta.
- **Ogni quanto:** un'attività programmata può partire al massimo una volta all'ora. Per questo le stelle non si possono controllare ogni 10 minuti: le controllano due attività diverse, sfasate di mezz'ora.
- **Vendite: ordini, non scrittura diretta.** Una pagina non può scrivere nell'app di un'altra, quindi quando chiedi una modifica Agente 1 passa un **ordine** allo specialista Vendite. In chat compare la carta "→ Vendite · in coda" con Annulla. Agente 1 sveglia il battito, che applica l'ordine nell'app entro un paio di minuti; la carta diventa "fatto" e arriva la notifica. Se Agente 1 decide di modificare qualcosa senza che tu l'abbia chiesto, la carta aspetta il tuo **Conferma**. Le stelle e la contabilità restano in sola lettura.
- **Costo:** ogni battito è una breve sessione Claude sul tuo piano, 14 al giorno. Puoi cambiare orari o frequenza dell'attività programmata.
