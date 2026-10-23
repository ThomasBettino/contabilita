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

## Ada che lavora da sola
Con l'hub acceso, Ada ha tre **routine** (le vedi in **Registro**, dove puoi spegnerle o lanciarle subito):
- **Riepilogo della sera**, ogni giorno alle 21:00: spese, cose che aspettano te, miglioramenti. Lo trovi in chat e ricevi una notifica.
- **Miglioramento**, ogni 6 ore: se ci sono segnalazioni aperte, Ada corregge i prompt. Senza segnalazioni non fa nulla e non costa nulla.
- **Promemoria**, ogni 2 ore: ti ricorda con una notifica le decisioni ferme da più di 2 ore.

Ada può anche creare altre routine da sola (massimo 8, ogni 30 minuti al minimo, mai con lo schermo del telefono).

**Notifiche sul telefono:** servono Termux:API e il permesso notifiche. Impostazioni, App, **Termux:API**, Notifiche, attiva. I testi sono generici ("Ada ha bisogno di te"), senza importi, per non mostrare dati sul blocco schermo.

**Costi sotto controllo:** i lavori automatici si fermano quando superano 400.000 token al giorno (cambialo con `export ADA_LIMITE_TOKEN=200000` in `~/.ada.env`). La chat con Ada non ha tetto. Il consumo di oggi lo vedi in Registro.

**Fuso orario:** le routine usano l'ora italiana (`Europe/Rome`). Se serve un altro fuso, `export ADA_FUSO=...` in `~/.ada.env`.

Le routine girano solo mentre Ada è accesa (il processo in Termux). Se il telefono si riavvia, riavvia Ada con `scripts/ada.sh`.

## Sicurezza
- Il server ascolta solo sul telefono (127.0.0.1): dall'esterno non è raggiungibile.
- Se un giorno lo apri su rete (`ADA_HOST=0.0.0.0`) il sistema si rifiuta di partire senza `ADA_TOKEN`.
- Database e prompt di Ada stanno in `~/ada`, i movimenti in `~/movimenti.db`: fuori dal repo, mai su GitHub.

## Cosa fa oggi e cosa no
Funziona: chat con Ada, team di 7 assistenti (con Acquisti), delega, ciclo di miglioramento dei prompt, approvazioni, riepilogo spese dai movimenti Revolut.
Controllo del telefono (ricerca e acquisti): richiede la configurazione in `docs/TELEFONO.md`.
Non ancora collegati come strumenti propri: Gmail, Calendario, WhatsApp, fatture (Ada può usarli solo attraverso lo schermo, quando il telefono è collegato). Ada lo sa e non finge di usarli.
