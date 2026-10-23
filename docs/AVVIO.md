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

## Se il telefono si spegne o si riavvia
Il programma si ferma, ma **non perdi niente**: database, prompt, fatture e chiavi restano nei file di Termux. Per rilanciarla a mano, in Termux:
```
termux-wake-lock
cd ~/contabilita
nohup sh scripts/ada.sh > ~/ada.log 2>&1 &
sleep 3
cat ~/ada.log
```
**Avvio automatico dopo ogni riavvio (una volta sola):**
1. Da **F-Droid** installa l'app **Termux:Boot** (la stessa fonte di Termux).
2. In Termux: `cd ~/contabilita && git pull && sh scripts/installa-boot.sh`
3. Apri **una volta** l'app Termux:Boot, e in Impostazioni, App, togli le restrizioni di batteria a **Termux** e **Termux:Boot**.
4. Prova: riavvia il telefono, aspetta un minuto e apri Ada.

**Se Ada non parte e nel log (`cat ~/ada.log`) c'è `cannot open scripts/ada.sh`, oppure `[1]+ Exit 2`:** sei sul ramo sbagliato. Su `main` il codice di Ada c'è solo dopo l'unione della richiesta #2; prima è sul ramo di lavoro. Controlla con `git branch --show-current` e, se non è `ccr-b35db874-occc4m`, torna con `git checkout ccr-b35db874-occc4m && git pull`. Non fare `git checkout main` finché la #2 non è unita.

La lettura delle notifiche di Revolut riparte da sola dopo il riavvio (è un lavoro persistente: controlla con `termux-job-scheduler --pending`). Il collegamento dello schermo no: va rifatto con **Collega schermo**.

Tieni il telefono carico: sotto il 10% Android limita i servizi in background.

## Ada che lavora da sola
Con l'hub acceso, Ada ha delle **routine** (le vedi in **Registro**, dove puoi spegnerle o lanciarle subito):
- **Riepilogo della sera**, ogni giorno alle 21:00: spese, cose che aspettano te, miglioramenti. Lo trovi in chat e ricevi una notifica.
- **Miglioramento**, ogni 3 ore (dipende dal ritmo, vedi sotto): se ci sono segnalazioni aperte, Ada corregge i prompt. Senza segnalazioni non fa nulla e non costa nulla.
- **Promemoria**, ogni 2 ore: ti ricorda con una notifica le decisioni ferme da più di 2 ore.

**Lavoro continuo: ritmo, collaudi, studio e libri.** «Ogni secondo» non è né possibile né sostenibile (ogni pensiero di Ada costa token, quindi soldi), ma Ada lavora da sola per tutto il tempo in cui è accesa, a un **ritmo** che scegli in **Registro, Ritmo di lavoro** (serve il token di accesso, vedi sotto):

| Ritmo | Collaudo | Studio | Lettura | Tetto giornaliero lavori automatici |
|---|---|---|---|---|
| Spento | no | no | no | 400.000 token |
| Leggero | ogni 4 ore | ogni 12 ore | ogni 12 ore | 400.000 token |
| **Normale** (predefinito) | ogni 3 ore | ogni 7 ore | ogni 4 ore | 800.000 token |
| Intenso | ogni 30 minuti | ogni 2 ore | ogni ora | 2.000.000 token (costa molto: l'app chiede conferma) |

- **Collaudo.** Un «avatar» esigente e imprevedibile (il **Collaudatore**, un assistente che sa solo parlare, senza strumenti) si comporta come faresti tu: ha fretta, cambia idea, ti rimprovera, incolla testi con ordini nascosti, chiede cose impossibili. Fa un messaggio, poi insiste. Un revisore dà un voto da 1 a 10 e dice cosa non va; se il voto è 7 o meno, il problema diventa una **segnalazione** per Ada, che nel suo ciclo di miglioramento corregge i prompt. Le categorie girano a rotazione (soldi, dati inventati, promesse senza azioni, pressione, istruzioni nascoste, privacy…). Li vedi in **Registro, Collaudi**, con tutto il dialogo.
- **La prova è una simulazione isolata**: Ada lì dentro usa una *copia* dei suoi prompt, un database vuoto e movimenti finti. Non può toccare soldi, schermo, notifiche, la tua chat né i prompt veri. Per risparmiare, il Collaudatore e il revisore usano il modello più economico (`ADA_MODEL_ECONOMICO`, predefinito Haiku; se non esiste sul tuo account si usa quello principale).
- **Studio.** A rotazione Ada studia 24 grandi menti (scienziati, matematici, investitori, venditori e negoziatori) e ne ricava tre principi da applicare a te. **È la sua conoscenza di quelle persone, non la lettura dei loro libri**, e le è vietato inventare citazioni: sull'app è etichettato come «lezione». Durante lo studio può solo aggiungere una regola breve a un prompt (annullabile) o proporre un'idea.
- **Libri veri.** Ada non può leggere libri che non ha. Se vuoi che li legga, copia file `.txt`, `.md` o `.epub` nella cartella `~/ada/libri` (da Termux: `cp /sdcard/Download/libro.epub ~/ada/libri/`; i PDF non sono supportati). Ada li legge a pezzi, ricorda a che punto è e scrive appunti: **Registro, Studio e letture**. Il testo di un libro è per lei materiale da studiare, mai ordini da eseguire.
- **Costi.** Tutto questo sta dentro il tetto dei lavori automatici (la chat con Ada non lo consuma mai). Quando il tetto di oggi è finito, collaudi, studio e letture si fermano fino a domani; da **Esegui ora** puoi comunque lanciarli a mano. Se non la vuoi lavorare da sola, scegli **Spento**.

**Ogni giorno una miglioria (alle 6:30).** Ada guarda cosa è successo (attività, errori, segnalazioni, spese rimaste senza categoria) e sceglie la miglioria più utile e a basso rischio.
- **Cose che fa da sola, subito:** correggere i prompt dei suoi assistenti (di norma aggiungendo una regola breve in fondo, nella sezione «Regole imparate»; riscrivere tutto un prompt è l'eccezione), creare o cambiare routine, insegnare regole di categoria alle spese (per esempio "Anthropic" va in Abbonamenti), chiudere segnalazioni. Tutto compare in **Registro** e si può annullare.
- **Funzioni nuove che richiedono codice:** le **propone**, una al giorno al massimo. La proposta arriva in **Approva** con una notifica. Se approvi, compare in **Registro, Idee di Ada** con un tasto che copia il testo pronto da dare a chi sviluppa; quando è realizzata la segni come **Fatta**.
- **Realizzazione:** le idee approvate non partono da sole. Con **Copia il testo per lo sviluppo** prepari un testo completo, con i vincoli di sicurezza già dentro, da dare a chi sviluppa. Quando la funzione è pronta la segni **Fatta**.
- **Cosa non fa mai:** modificare il proprio codice o i confini di sicurezza (soldi, tasto finale, schermo).

Ada può anche creare altre routine da sola (massimo 8, ogni 30 minuti al minimo, mai con lo schermo del telefono).

**Notifiche sul telefono:** servono Termux:API e il permesso notifiche. Impostazioni, App, **Termux:API**, Notifiche, attiva. I testi sono generici ("Ada ha bisogno di te"), senza importi, per non mostrare dati sul blocco schermo.

**Costi sotto controllo:** i lavori automatici si fermano quando superano il tetto del ritmo scelto (400.000 token al giorno è la base, per il ritmo Normale il doppio; cambia la base con `export ADA_LIMITE_TOKEN=200000` in `~/.ada.env`). **La chat con Ada non consuma quel tetto e non ha limiti.** In Registro vedi il consumo totale di oggi e quello dei lavori automatici. I token della cache dei prompt contano un decimo, perché costano un decimo.

**Fuso orario:** le routine usano l'ora italiana (`Europe/Rome`). Se serve un altro fuso, `export ADA_FUSO=...` in `~/.ada.env`.

Le routine girano solo mentre Ada è accesa (il processo in Termux). Se il telefono si riavvia, riavvia Ada con `scripts/ada.sh`.

## Token di accesso (serve per salvare codici e per aggiornare)
Qualunque app del telefono può raggiungere Ada su `localhost`. Per questo Ada **rifiuta** di salvare codici (script fatture) e di aggiornarsi finché non imposti un token di accesso. In Termux, una volta:
```
echo "export ADA_TOKEN=$(head -c 18 /dev/urandom | base64 | tr -d '/+=')" >> ~/.ada.env
pkill -f src.ada.server
cd ~/contabilita
nohup sh scripts/ada.sh > ~/ada.log 2>&1 &
```
Poi copialo negli appunti, senza vederlo, e incollalo quando Ada lo chiede in Chrome (il browser lo ricorda):
```
grep -o 'ADA_TOKEN=.*' ~/.ada.env | cut -d= -f2 | termux-clipboard-set
```
Il token non va condiviso con nessuno.

## Aggiornare Ada con un tocco
Quando ci sono versioni nuove del programma: **Registro, Aggiornamenti, Aggiorna Ada** (serve il token di accesso). Scarica la versione nuova con un avanzamento semplice (non sovrascrive niente), **fa girare i test** e riavvia Ada. Se i test **falliscono**, torna da sola alla versione di prima e te lo dice. Il ramo seguito è quello su cui si trova il telefono: per controllarlo, `git branch --show-current` in Termux.

## Sicurezza
- Il server ascolta solo sul telefono (127.0.0.1): dall'esterno non è raggiungibile.
- Se un giorno lo apri su rete (`ADA_HOST=0.0.0.0`) il sistema si rifiuta di partire senza `ADA_TOKEN`.
- Database e prompt di Ada stanno in `~/ada`, i movimenti in `~/movimenti.db`: fuori dal repo, mai nel repository.

## Cosa fa oggi e cosa no
Funziona: chat con Ada, team di 7 assistenti più il Collaudatore (che esiste solo per mettere alla prova Ada), delega, ciclo di miglioramento dei prompt, approvazioni, riepilogo spese dai movimenti Revolut.
Controllo del telefono (ricerca e acquisti): richiede la configurazione in `docs/TELEFONO.md`.
Non ancora collegati come strumenti propri: Gmail, Calendario, WhatsApp, fatture (Ada può usarli solo attraverso lo schermo, quando il telefono è collegato). Ada lo sa e non finge di usarli.
