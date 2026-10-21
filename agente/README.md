# Agente 1

Agente 1 è il capo di una squadra di agenti IA. Parli solo con lui, in una chat scritta o a voce. Lui consulta gli specialisti, incrocia le risposte e ti dice cosa conta.

**App:** https://claude.ai/artifact/QKUvJ2gwq8cVGTnkCukMnc

```
                    ┌──────────── Agente 1 (artefatto claude.ai) ────────────┐
Tu ── chat/voce ──► │  capo: ragiona, delega, dà la sua opinione             │
                    │   ├─ Vendite      legge sync/vendite                   │
                    │   ├─ Agenda       Google Calendar in diretta + agenda  │
                    │   ├─ Contabilità  legge sync/contabilita               │
                    │   └─ Meteo        legge sync/meteo                     │
                    │  email (Gmail, solo a te) · avvisi · memoria           │
                    └───────────────────────▲────────────────────────────────┘
                                            │ scrive ogni ora
                    Battito (attività programmata Claude, 8–21)
                     ├─ legge l'artefatto Andamento vendite (solo lettura)
                     ├─ cerca il meteo su più fonti
                     └─ prova lo script Google della contabilità
```

## Perché è fatto così

- Una pagina di artefatto **non ha accesso alla rete** e **non può leggere il database di un altro artefatto**. Per questo un ponte, il battito, legge "Andamento vendite" con il tuo account e copia un riepilogo nel database di Agente 1.
- Il cervello è **Claude dal tuo account** (capacità `sample`): non servono chiavi API né server da pagare.
- Agenda ed email usano i **tuoi connettori** Google Calendar e Gmail, direttamente dalla pagina.
- Ogni volta che aggiorno l'artefatto, l'app aperta riceve la nuova versione da sola, allo stesso link.

## Cartelle

- `app/agente-1.html` è il sorgente dell'artefatto Agente 1.
- `ponte/vendite.js` trasforma l'export di "Andamento vendite" nel riepilogo per lo specialista vendite. I calcoli (fatturato, provvigioni, proiezione, ritmo) sono copiati dalla app v21, quindi i numeri coincidono. Genera anche gli avvisi: richiami, impegni del giorno, impegni entro 90 minuti, saldi della settimana.
- `ponte/contabilita.js` legge le fatture dallo script Google della app di contabilità, con gli stessi calcoli della app.
- `ponte/BATTITO.md` è la procedura che il battito esegue ogni ora.

## Database di Agente 1

| Percorso | Contenuto | Chi scrive |
|---|---|---|
| `sync/vendite`, `sync/meteo`, `sync/contabilita` | Riepiloghi per gli specialisti | Battito |
| `notifiche/<id>` | Avvisi | Battito e Agente 1 |
| `config/agenti` | Istruzioni migliorate degli specialisti, con lo storico | Agente 1 (`migliora_agente`) |
| `config/ponte` | Id dell'attività programmata, per il pulsante Aggiorna | Claude |
| `data/users/<tu>/chat`, `.../memoria` | Conversazione e cose da ricordare, private | Agente 1 |

## Contabilità: cosa manca

La pagina non può contattare lo script Google, e l'ambiente cloud del battito al momento blocca `script.google.com`. Per collegarla:

1. Nelle impostazioni dell'ambiente cloud (menu dell'ambiente nella barra della sessione, poi Modifica), sotto Accesso di rete aggiungi `script.google.com` e `script.googleusercontent.com` ai domini consentiti.
2. Nello stesso ambiente aggiungi le variabili `CONTABILITA_URL` e `CONTABILITA_TOKEN`, cioè gli stessi valori che usa la app di contabilità.

Dal battito successivo lo specialista Contabilità avrà i numeri.

## Limiti da conoscere

- **Dettatura:** la pagina non può usare il microfono. Per parlare usa il microfono della tastiera del telefono. La risposta a voce invece funziona: pulsante "Voce".
- **Freschezza:** vendite e contabilità sono aggiornate al battito più recente, ogni ora dalle 8 alle 21, oppure quando premi Aggiorna. Google Calendar è sempre in diretta.
- **Vendite in sola lettura:** Agente 1 legge l'app vendite ma non la modifica. Per registrare chiamate o vendite usa l'app, o il suo Coach.
- **Costo:** ogni battito è una breve sessione Claude sul tuo piano, 14 al giorno. Puoi cambiare orari o frequenza dell'attività programmata.
