# Archivio fatture P.IVA in Ada

Lo script Google dell'app **Contabilità Smart** continua a fare quello che fa oggi: quando mandi la mail a Giulia con il Word, archivia la fattura (Word, PDF su Drive, stato). Ada **si collega a quello stesso archivio**: lo porta nell'hub, riconosce il bonifico di Autoghinzani, ti avvisa e segna proprio quella fattura come incassata.

## Cosa fa Ada
- **Archivio nell'hub:** Soldi, **Fatture P.IVA**: elenco con stato, bonifico atteso, link a PDF e Word.
- **Fattura nuova:** ti arriva una notifica generica ("Fattura archiviata").
- **Bonifico in arrivo:** guarda le notifiche di Revolut ogni 10 minuti.
  - Se arriva da Autoghinzani e l'importo corrisponde a **una sola** fattura: ti avvisa, segna quella fattura come incassata (anche nel foglio Google) e ti scrive in chat.
  - Se l'importo corrisponde a **più** fatture: non sceglie, te lo chiede in chat.
  - Se arriva da Autoghinzani ma nessuna fattura corrisponde: te lo dice e mostra i bonifici attesi.
  - Se l'importo è giusto ma il mittente è diverso: ti chiede conferma in **Approva**.
- **Riepilogo e tasse:** incassato, da incassare e quanto manca da accantonare. Entra anche nel riepilogo della sera.
- Ogni incasso si annulla con **Annulla incasso** nella scheda della fattura.

Il bonifico atteso si calcola come nella tua app: imponibile + bollo (2 € sopra 77,47 €) − Enasarco. Le tasse sono il 30% del netto dopo Enasarco.

## Collegarla (una volta, dal telefono)
1. Apri l'app **Contabilità Smart**, scheda **Avvisi**, **Impostazioni**. Lì ci sono l'**indirizzo dello script** (inizia con `https://script.google.com/`) e il **codice segreto**.
2. In Termux copia queste righe, una alla volta. Per il codice segreto uso un campo nascosto:
   ```
   read -rsp "Incolla il codice segreto: " T
   ```
   incolla il codice (non si vede), Invio, poi:
   ```
   echo "export ADA_FATTURE_TOKEN=$T" >> ~/.ada.env
   unset T
   ```
   Per l'indirizzo (sostituisci con il tuo):
   ```
   echo 'export ADA_FATTURE_URL=https://script.google.com/macros/s/.../exec' >> ~/.ada.env
   ```
3. Riavvia Ada:
   ```
   pkill -f src.ada.server
   cd ~/contabilita
   git pull
   nohup sh scripts/ada.sh > ~/ada.log 2>&1 &
   ```
4. In Ada: **Soldi**, **Fatture P.IVA**, **Sincronizza ora**.

## Se nella tua app hai cambiato le percentuali
Impostazioni di Ada in `~/.ada.env` (valori predefiniti uguali all'app):
```
export ADA_ENASARCO=8.5     # percentuale Enasarco
export ADA_TASSE=30         # percentuale tasse sul netto
export ADA_GIORNI=30        # giorni entro cui deve arrivare il bonifico
export ADA_PAGATORE=autoghinzani   # nome da cercare nella notifica del bonifico
```

## Cose da sapere
- **Al primo avvio** Ada importa lo storico senza farti notifiche e non riesamina i bonifici già arrivati: abbina solo quelli nuovi.
- **I testi delle notifiche Revolut** per i bonifici in entrata non li conosco con certezza. Ada cerca "autoghinzani" nel testo della notifica e confronta l'importo. Al primo bonifico vero controlla che l'abbinamento sia giusto e dimmi cosa è successo.
- Se lo script Google non risponde, il bonifico **non va perso**: viene ritentato al giro dopo.
- Il codice segreto non lascia mai il telefono se non verso `script.google.com`: se l'indirizzo non inizia così, Ada rifiuta di inviarlo.
