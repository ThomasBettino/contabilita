# Avviare Ada sul telefono

Ada è un'app web che gira su Termux, sul tuo telefono. Il suo "cervello" è Claude, che si raggiunge con una chiave API.

## 1. Aggiorna il progetto
```
cd ~/contabilita
git pull
```

## 2. Chiave API (il cervello di Ada)
La chiave si crea su **console.anthropic.com**, sezione API Keys. Attenzione: è separata dall'abbonamento di Claude e si paga a consumo, quindi serve caricare un piccolo credito.

Poi in Termux scrivi (sostituisci con la tua chiave, **non incollarla mai in chat né nel repo**):
```
nano ~/.ada.env
```
dentro metti una sola riga:
```
export ANTHROPIC_API_KEY=la-tua-chiave
```
Salva con CTRL+O, invio, CTRL+X. Poi proteggi il file:
```
chmod 600 ~/.ada.env
```
Senza chiave l'hub parte lo stesso, ma Ada risponde che il cervello non è collegato.

## 3. Avvio
```
termux-wake-lock
sh scripts/ada.sh
```
Quando vedi `Ada è pronta su http://127.0.0.1:8765` apri **Chrome** sul telefono e vai su `http://localhost:8765`. Dal menu di Chrome scegli **Aggiungi a schermata Home** per averla come app.

Per lasciarla attiva in background: `nohup sh scripts/ada.sh > ~/ada.log 2>&1 &`

## Sicurezza
- Il server ascolta solo sul telefono (127.0.0.1): dall'esterno non è raggiungibile.
- Se un giorno lo apri su rete (`ADA_HOST=0.0.0.0`) il sistema si rifiuta di partire senza `ADA_TOKEN`.
- Database e prompt di Ada stanno in `~/ada`, i movimenti in `~/movimenti.db`: fuori dal repo, mai su GitHub.

## Cosa fa oggi e cosa no
Funziona: chat con Ada, team di 7 assistenti (con Acquisti), delega, ciclo di miglioramento dei prompt, approvazioni, riepilogo spese dai movimenti Revolut.
Controllo del telefono (ricerca e acquisti): richiede la configurazione in `docs/TELEFONO.md`.
Non ancora collegati come strumenti propri: Gmail, Calendario, WhatsApp, fatture (Ada può usarli solo attraverso lo schermo, quando il telefono è collegato). Ada lo sa e non finge di usarli.
