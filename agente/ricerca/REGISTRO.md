# Registro delle correzioni e delle migliorie

Ogni correzione e ogni miglioria che entra (con il sì di Thomas) aggiunge qui una voce in cima: data, tipo, titolo, perché, file, prove, approvata il.

## 2026-10-23 · Nasce il Reparto Ricerca
- **Tipo:** miglioria.
- **Perché:** Thomas vuole una squadra che trovi da sola i bug e gli errori, prepari le correzioni e le migliorie già provate e gliele proponga: entrano col suo sì, e le novità arrivano anche nel briefing della sera.
- **File:** `agente/ricerca/RICERCA.md`, `agente/app/agente-1.html`, `agente/ponte/TURNO.md`.
- **Prove:** `node agente/test/ponte.test.js` (28 prove).

## 2026-10-23 · Ordine doppione rimasto "da confermare"
- **Tipo:** correzione (dati).
- **Cosa non andava:** un ordine per la consegna di Alessandro del 23/10 era fermo su "da confermare" dal 22/10, uno stato che dopo l'autonomia di Agente 1 nessuno porta più avanti. La stessa consegna era già in agenda con un altro ordine.
- **Correzione:** ordine chiuso come "annullato", con il motivo: doppione.

## 2026-10-23 · Passo 5 del meteo perso nella procedura del turno
- **Tipo:** correzione.
- **Cosa non andava:** il titolo del passo 5 era sparito: le istruzioni del meteo stavano attaccate al passo 4f dei compiti, e i rimandi al passo 5 e al passo 4b non portavano a niente.
- **Causa:** una modifica del 22/10 a `TURNO.md` aveva unito due passi.
- **File:** `agente/ponte/TURNO.md`, `agente/test/ponte.test.js` (nuova prova: ogni passo citato esiste, il passo 1 copia tutti gli script).
- **Prove:** la prova nuova falliva sulla procedura vecchia e passa su quella corretta; 28 prove superate.
