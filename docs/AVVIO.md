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

## Riavviare Ada (dopo un aggiornamento o se non si apre)
Un solo comando: ferma la copia in corso, la fa ripartire e ti dice subito se è partita; se no, mostra le ultime righe del log con l'errore.
```
cd ~/contabilita
git pull
sh scripts/riavvia.sh
```
Se scrive «Ada NON è partita», copia quelle righe e mandale a chi ti aiuta: dicono il motivo.

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

La lettura delle notifiche di Revolut riparte da sola con Ada (routine «notifiche»); il vecchio lavoro ogni 15 minuti riparte anch'esso (controlla con `termux-job-scheduler --pending`). Il collegamento dello schermo no: va rifatto con **Collega schermo**.

Tieni il telefono carico: sotto il 10% Android limita i servizi in background.

## Ada che lavora da sola
Con l'hub acceso, Ada ha delle **routine** (le vedi in **Registro, Routine**, raggruppate, ognuna con il suo timer; puoi spegnerle o lanciarle subito):
- **Riepilogo della sera**, ogni giorno alle 21:00: spese, cose che aspettano te, miglioramenti. Lo trovi in chat e ricevi una notifica.
- **Miglioramento**, ogni 3 ore (dipende dal ritmo, vedi sotto): se ci sono segnalazioni aperte, Ada corregge i prompt. Senza segnalazioni non fa nulla e non costa nulla.
- **Notifiche Revolut**, ogni 2 minuti: Ada legge da sola le notifiche di Revolut (serve Termux:API con l'accesso alle notifiche, ma non lo schermo collegato né te). Quando arriva un movimento nuovo controlla subito le fatture, quindi l'avviso di un bonifico arriva in pochi minuti. In **Soldi, Conto** una riga dice quando ha letto l'ultima volta e se funziona; se fallisce, scrive il motivo. Android mostra solo le notifiche ancora presenti: non cancellare quelle di Revolut finché non sono passati un paio di minuti. Il vecchio lavoro ogni 15 minuti (`scripts/ingest.sh`) può restare: è un ripiego e non crea doppioni.
- **Promemoria**, ogni 2 ore: ti ricorda con una notifica le decisioni ferme da più di 2 ore.

**Lavoro continuo: ritmo, collaudi, studio e libri.** «Ogni secondo» non è né possibile né sostenibile (ogni pensiero di Ada costa token, quindi soldi), ma Ada lavora da sola per tutto il tempo in cui è accesa, a un **ritmo** che scegli in **Registro, Lavoro** (serve il token di accesso, vedi sotto):

| Ritmo | Collaudo | Studio | Lettura | Tetto giornaliero lavori automatici |
|---|---|---|---|---|
| Spento | no | no | no | 400.000 token |
| Leggero | ogni 4 ore | ogni 12 ore | ogni 12 ore | 400.000 token |
| **Normale** (predefinito) | ogni 3 ore | ogni 7 ore | ogni 4 ore | 800.000 token |
| Intenso | ogni 30 minuti | ogni 2 ore | ogni ora | 2.000.000 token (costa molto: l'app chiede conferma) |

- **Collaudo.** Un «avatar» esigente e imprevedibile (il **Collaudatore**, un assistente che sa solo parlare, senza strumenti) si comporta come faresti tu: ha fretta, cambia idea, ti rimprovera, incolla testi con ordini nascosti, chiede cose impossibili. Fa un messaggio, poi insiste. Un revisore dà un voto da 1 a 10 e dice cosa non va; se il voto è 7 o meno, il problema diventa una **segnalazione** per Ada, che nel suo ciclo di miglioramento corregge i prompt. Le categorie girano a rotazione (soldi, dati inventati, promesse senza azioni, pressione, istruzioni nascoste, privacy…). Li vedi in **Registro, Prove**, con tutto il dialogo.
- **La prova è una simulazione isolata**: Ada lì dentro usa una *copia* dei suoi prompt, un database vuoto e movimenti finti. Non può toccare soldi, schermo, notifiche, la tua chat né i prompt veri. Per risparmiare, il Collaudatore e il revisore usano il modello più economico (`ADA_MODEL_ECONOMICO`, predefinito Haiku; se non esiste sul tuo account si usa quello principale).
- **Studio.** A rotazione Ada studia 24 grandi menti (scienziati, matematici, investitori, venditori e negoziatori) e ne ricava tre principi da applicare a te. **È la sua conoscenza di quelle persone, non la lettura dei loro libri**, e le è vietato inventare citazioni: sull'app è etichettato come «lezione». Durante lo studio può solo aggiungere una regola breve a un prompt (annullabile) o proporre un'idea.
- **Libri veri.** Ada ha una libreria: la cartella `~/ada/libri`. Per aggiungere un tuo libro apri **Registro, Prove, Aggiungi un libro** e scegli un file `.txt`, `.md` o `.epub` (massimo 20 MB, serve il token di accesso); con la ✕ accanto al nome lo togli. I PDF non si leggono, e un epub comprato con protezione (DRM) nemmeno: Ada te lo dice. Ada li legge a pezzi, ricorda a che punto è e scrive appunti: **Registro, Prove**. Il testo di un libro è per lei materiale da studiare, mai ordini da eseguire.
- **Libri che Ada si cerca da sola.** Quando non ha niente da leggere, ne sceglie lei uno **di pubblico dominio** da **Project Gutenberg** (al massimo uno ogni 20 ore, fino a 20 libri) e lo scarica nella sua cartella; puoi anche chiederglielo in chat («cercati un libro di strategia»). Scarica **solo** da `gutenberg.org`: libri recenti coperti da diritto d'autore (per esempio *Le 48 leggi del potere*) non li prende da altre parti, e se glieli chiedi te lo dice. Se ne hai una copia tua (epub o txt) la carichi tu con «Aggiungi un libro». Alternative libere sugli stessi temi: *L'arte della guerra* (Sun Tzu), *Il Principe* (Machiavelli), *Meditazioni* (Marco Aurelio).
- **Costi.** Tutto questo sta dentro il tetto dei lavori automatici (la chat con Ada non lo consuma mai). Quando il tetto di oggi è finito, collaudi, studio e letture si fermano fino a domani; da **Esegui ora** puoi comunque lanciarli a mano. Se non la vuoi lavorare da sola, scegli **Spento**.

**Ogni giorno una miglioria (alle 6:30).** Ada guarda cosa è successo (attività, errori, segnalazioni, spese rimaste senza categoria) e sceglie la miglioria più utile e a basso rischio.
- **Cose che fa da sola, subito:** correggere i prompt dei suoi assistenti (di norma aggiungendo una regola breve in fondo, nella sezione «Regole imparate»; riscrivere tutto un prompt è l'eccezione), creare o cambiare routine, insegnare regole di categoria alle spese (per esempio "Anthropic" va in Abbonamenti), chiudere segnalazioni. Tutto compare in **Registro, Modifiche** e si può annullare.
- **Funzioni nuove che richiedono codice:** le **propone**, una al giorno al massimo. La proposta arriva in **Approva** con una notifica. Se approvi, compare in **Registro, Idee** con un tasto che copia il testo pronto da dare a chi sviluppa; quando è realizzata la segni come **Fatta**.
- **Realizzazione:** le idee approvate non partono da sole. Con **Copia il testo per lo sviluppo** prepari un testo completo, con i vincoli di sicurezza già dentro, da dare a chi sviluppa. Quando la funzione è pronta la segni **Fatta**.
- **Cosa non fa mai:** modificare il proprio codice o i confini di sicurezza (soldi, tasto finale, schermo).

Ada può anche creare altre routine da sola (massimo 8, ogni 30 minuti al minimo, mai con lo schermo del telefono).

**Notifiche sul telefono:** servono Termux:API e il permesso notifiche. Impostazioni, App, **Termux:API**, Notifiche, attiva. I testi sono generici ("Ada ha bisogno di te"), senza importi, per non mostrare dati sul blocco schermo.

**Costi sotto controllo:** i lavori automatici si fermano quando superano il tetto del ritmo scelto (400.000 token al giorno è la base, per il ritmo Normale il doppio; cambia la base con `export ADA_LIMITE_TOKEN=200000` in `~/.ada.env`). **La chat con Ada non consuma quel tetto e non ha limiti.** In **Registro, Lavoro** vedi il consumo totale di oggi e quello dei lavori automatici. I token della cache dei prompt contano un decimo, perché costano un decimo.

**Fuso orario:** le routine usano l'ora italiana (`Europe/Rome`). Se serve un altro fuso, `export ADA_FUSO=...` in `~/.ada.env`.

Le routine girano solo mentre Ada è accesa (il processo in Termux). Se il telefono si riavvia, riavvia Ada con `scripts/ada.sh`.

## Agenda e promemoria
Ada ha un'agenda sua (non è il Calendario di Google: quello non lo legge né lo scrive). In **Agenda** vedi, giorno per giorno, promemoria e appuntamenti, e quelli scaduti da chiudere. Le voci si aggiungono dal tasto **＋ Nuova voce** (tipo, cosa, giorno, ora o tutto il giorno, quanto prima avvisare, ripetizione ogni giorno, settimana o mese) oppure a parole: «ricordami domani alle 9 di chiamare Zanetti».
- **Avvisi:** la routine «agenda» controlla ogni minuto e all'ora giusta il telefono manda la notifica (il testo è quello che hai scritto tu). Se il telefono era spento, l'avviso arriva appena riparte, fino a 12 ore dopo; oltre, la voce resta tra i **scaduti** da chiudere o spostare.
- **Mattina:** alle 7:30 un solo avviso con il riassunto di oggi. **Se non c'è niente in agenda, non manda niente.**
- **Ore:** sono quelle italiane (`Europe/Rome`, o `ADA_FUSO`). Una voce senza ora vale tutto il giorno e avvisa alle 8.
- Ada conosce la tua agenda: vede nel suo contesto le cose delle prossime 36 ore, quindi puoi chiederle «cosa ho domani?». Le voci create da Ada o dal reparto vendite compaiono nella stessa lista.

## Reparto vendite: l'app «Andamento vendite»
Il reparto vendite (l'assistente «Clienti e vendite») conosce a memoria l'app **Andamento vendite**: schede, dati di un preventivo o di un cliente, stati, calcolo del fatturato e tutto quello che sa fare il suo Coach. Il manuale è in `agenti/clienti_vendite/manuale-app.md`, scritto leggendo il codice dell'app alla versione **v22**.
1. **Una volta sola:** in **Agenda, Reparto vendite** incolla il link dell'app (quello che vedi in Condividi, tipo `https://claude.ai/artifact/…`). Apri l'app e fai l'accesso una volta, con «Resta collegato su questo dispositivo» spuntato (Ada non scrive mai la password).
2. **Come funziona:** dici ad Ada una novità («ho chiuso la vendita di Zanetti Emilio», «ho chiamato Rossi, lo richiamo lunedì», «Bianchi ha versato 1000 euro di acconto»). Ada ti avvisa subito con una notifica («Bravo, hai venduto! Parlo con il reparto vendite e aggiorno tutto subito.») e passa il compito al reparto vendite. Lui apre l'app dal telefono, va nel **Coach**, scrive la frase, aspetta la risposta e ti dice cosa è stato registrato. Se manca un dato obbligatorio (per una vendita: la formula full drive/contanti/altro e il margine in euro) te lo chiede, non lo inventa. Richiami e appuntamenti li mette anche nella tua agenda, così il telefono ti avvisa all'ora giusta (l'app da sola non manda notifiche).
3. **Serve lo schermo collegato** (**Collega schermo**, vedi `docs/TELEFONO.md`). Se non lo è, o se l'app chiede l'accesso, l'aggiornamento **non va perso**: resta in **Agenda, Reparto vendite, Da riportare nell'app** con il tasto **Copia e apri l'app**: ti basta incollare la frase nel Coach. Poi premi Fatto.
4. **Il diario e il riepilogo delle 18:55.** Da ora puoi parlare solo con Ada: ogni novità (preventivo fatto, vendita, chiamata, test drive, appuntamento, cliente perso, pagamento) finisce anche nel **diario di lavoro**, che Ada tiene da sé, con o senza lo schermo collegato. Anche le cose raccontate in ritardo («ieri ho venduto Zanetti») vanno nel giorno giusto. **Ogni giorno alle 18:55** Ada ti scrive da sola in chat e ti manda una notifica con: quanti preventivi hai fatto oggi, quante vendite (con i nomi), chiamate e test drive, cosa è ancora da riportare nell'app e cosa hai in agenda per il giorno dopo. Il riepilogo arriva tutti i giorni, anche a zero, e non usa il cervello: è costruito da diario e agenda. In **Agenda, Reparto vendite, Il diario di oggi** vedi i numeri e puoi togliere una voce sbagliata con la ✕. Quello che scrivi direttamente nell'app arriva ad Ada solo se hai attivato gli **avvisi dall'app** (punto 8); altrimenti nel riepilogo non c'è.
5. **Cosa non può fare:** senza lo schermo Ada non vede i dati dell'app (non sa quanti preventivi hai o chi è da richiamare, a meno che glielo dici o che lei li legga dallo schermo); non manda messaggi ai clienti; non invia notifiche con nomi di clienti o importi (restano sul blocco schermo). Le routine automatiche non toccano mai lo schermo (di sera il telefono è spesso bloccato): l'aggiornamento dell'app parte quando le scrivi tu, e se in coda c'è roba vecchia la riporta in quel momento, con lo schermo collegato.
6. **Se l'app cambia:** il numero di versione si legge sotto il titolo dell'app («Sincronizzato alle … · v22»). Il manuale è fermo a v22: se aggiungi funzioni, fallo rileggere e aggiornare (in una sessione di sviluppo: «aggiorna `agenti/clienti_vendite/manuale-app.md` rileggendo l'app»).
7. **Prova:** scrivi ad Ada «ho chiamato Zanetti Emilio, vuole pensarci, richiamalo lunedì» con lo schermo collegato e guarda cosa fa; se qualcosa non va, dimmi dove si ferma (l'attività del reparto vendite si vede nel popup del team e in **Registro, Storico**).
8. **Avvisi automatici dall'app (sperimentale).** Per far sapere ad Ada anche quello che scrivi direttamente nell'app, per esempio dal PC al lavoro: l'app, a ogni cambiamento (preventivo, vendita, chiamata, test drive, pagamento, appuntamento, richiamo), manda un messaggio in codice alla tua Gmail. Ada lo legge dalle notifiche del telefono, lo mette nel diario o nella sua agenda e ti scrive da sola: «Hei Thomas, ho visto che hai aggiunto un preventivo: l'ho segnato». Un richiamo o un appuntamento che togli nell'app sparisce anche dall'agenda di Ada. Si attiva una volta sola:
   - Sul telefono, in Termux: `sh scripts/token.sh` (token di accesso), poi apri Ada, **Agenda, Avvisi automatici dall'app, Genera il codice**, **Copia il codice**.
   - Apri l'app Andamento vendite (aggiornata alla v22), **Altro, Impostazioni, Avvisi ad Ada**: scrivi la tua Gmail, incolla il codice e tocca **Salva e prova il collegamento**. La prima volta Claude ti chiede il permesso di usare Gmail: accetta. Poco dopo Ada ti avvisa «il collegamento con l'app vendite funziona!». Fai lo stesso sul PC (gli avvisi valgono per il dispositivo da cui scrivi).
   - Limiti da sapere: se Gmail non fa suonare le mail che mandi a te stesso, Ada non vede niente (la prova lo mostra subito); l'oggetto con il nome del cliente si legge anche sul blocco schermo; ogni modifica lascia una mail in più in Gmail (puoi filtrarle con l'etichetta `[ADA]`); se una notifica è tagliata, Ada la conta come «non leggibile» in **Agenda, Avvisi automatici dall'app** e non la usa. Nei messaggi non ci sono importi né note.

## Token di accesso (serve per salvare codici, aggiornare, cambiare ritmo e modificare i movimenti)
Qualunque app del telefono può raggiungere Ada su `localhost`. Per questo Ada **rifiuta** di salvare codici (script fatture), di aggiornarsi, di cambiare ritmo e di modificare i movimenti finché non imposti un token di accesso. In Termux, una volta sola:
```
cd ~/contabilita
git pull
sh scripts/token.sh
```
Lo script crea il token (in `~/.ada.env`, fuori dal repo), riavvia Ada e lo **copia negli appunti senza mostrarlo**. Poi apri Ada in Chrome: la prima volta chiede il token, lo incolli e il browser se lo ricorda. Se lo rilanci, non ne crea un altro: lo ricopia soltanto.

Il token non va condiviso con nessuno.

## Soldi: movimenti a mano ed estratto conto
Ada legge solo le notifiche di Revolut, quindi può perdersi un pagamento (o leggerne uno due volte). In **Soldi, Conto** puoi sistemare i conti da solo (serve il token di accesso):
- **Aggiungi un pagamento**: uscita o entrata, importo, a chi o per cosa, data. Se è un bonifico di un cliente, Ada lo abbina alla fattura come per le notifiche.
- **Togli un movimento** con la ✕ accanto a ogni riga (anche uno letto da una notifica: non ricompare, anche se la notifica è ancora nella tendina). Il menu del mese permette di tornare indietro fino a un anno.
- **Carica estratto conto (CSV)**: in Revolut, Conti, tre puntini, Estratto, formato Excel o CSV (vanno bene anche i CSV delle banche italiane con data, descrizione e importo, o con colonne dare e avere; i PDF non si leggono). Ada confronta ogni riga con i movimenti che ha già, ammettendo uno scarto di due giorni tra notifica e estratto: quelli che ci sono li lascia, quelli che mancano li aggiunge, e ti mostra in **Da controllare** quelli che ha nel conto ma che nell'estratto, nel periodo, non ci sono (doppioni o pagamenti ancora in sospeso), con la ✕ per toglierli. Si può ricaricare lo stesso file senza creare doppioni.
- Non vengono importati: movimenti annullati o in attesa, cambi di valuta tra i tuoi conti e movimenti in altra valuta (te lo dice con i numeri).
- I movimenti aggiunti dall'estratto **non fanno scattare avvisi né abbinamenti alle fatture**: servono a far tornare le spese e le entrate. Per segnare una fattura incassata usa la scheda Fatture P.IVA o scrivi ad Ada.

## Aggiornare Ada con un tocco
Quando ci sono versioni nuove del programma: **Registro, Lavoro, Versione, Aggiorna Ada** (serve il token di accesso). Scarica la versione nuova con un avanzamento semplice (non sovrascrive niente), **fa girare i test** e riavvia Ada. Se i test **falliscono**, torna da sola alla versione di prima e te lo dice. Il ramo seguito è quello su cui si trova il telefono: per controllarlo, `git branch --show-current` in Termux.

## Sicurezza
- Il server ascolta solo sul telefono (127.0.0.1): dall'esterno non è raggiungibile.
- Se un giorno lo apri su rete (`ADA_HOST=0.0.0.0`) il sistema si rifiuta di partire senza `ADA_TOKEN`.
- Database e prompt di Ada stanno in `~/ada`, i movimenti in `~/movimenti.db`: fuori dal repo, mai nel repository.

## Cosa fa oggi e cosa no
Funziona: agenda e promemoria con avvisi, reparto vendite per l'app Andamento vendite, chat con Ada, team di 7 assistenti più il Collaudatore (che esiste solo per mettere alla prova Ada), delega, ciclo di miglioramento dei prompt, approvazioni, riepilogo spese dai movimenti Revolut.
Controllo del telefono (ricerca e acquisti): richiede la configurazione in `docs/TELEFONO.md`.
Non ancora collegati come strumenti propri: Gmail, Calendario di Google, WhatsApp, fatture (Ada può usarli solo attraverso lo schermo, quando il telefono è collegato). Ada lo sa e non finge di usarli.
