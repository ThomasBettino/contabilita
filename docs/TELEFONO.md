# Collegare il controllo del telefono (ADB via Termux)

Serve ad Ada per guardare e usare lo schermo (ad esempio cercare su Amazon). Si attiva una volta, richiede Android 11 o più recente e il wifi acceso solo durante la configurazione (poi si può usare il 5G, vedi 4 bis).

## 1. Opzioni sviluppatore
1. Impostazioni, Informazioni sul telefono, Informazioni sul software.
2. Tocca 7 volte **Numero build**. Android chiede il PIN e dice "Ora sei uno sviluppatore".
3. Torna in Impostazioni: in fondo c'è **Opzioni sviluppatore**.

## 2. Debug wireless
1. In Opzioni sviluppatore attiva **Debug wireless** (conferma con "Consenti"). Il telefono deve essere collegato al wifi.
2. Entra nella voce **Debug wireless**: vedi un indirizzo tipo `192.168.1.20:37215`. La porta (l'ultimo numero) ti serve.

## 3. Abbina Termux
In Termux:
```
pkg install android-tools
```
Poi, in Debug wireless, tocca **Abbina dispositivo con codice di abbinamento**: compaiono un codice di 6 cifre e una porta di abbinamento (diversa dalla precedente).

Per scrivere in Termux mentre il codice è sullo schermo, usa la **vista a schermo diviso** (Termux sopra, Impostazioni sotto). Poi:
```
adb pair localhost:PORTA_DI_ABBINAMENTO
```
e scrivi il codice di 6 cifre.

## 4. Collega
Con la **porta principale** (quella della schermata Debug wireless):
```
adb connect localhost:PORTA_PRINCIPALE
adb devices
```
Deve comparire una riga con `device`. Se ne compaiono più di una, imposta quale usare:
```
export ADA_ADB_SERIALE=localhost:PORTA_PRINCIPALE
```
(mettilo anche in `~/.ada.env`).

## 4 bis. Usare solo i dati del telefono (5G)
Il Debug wireless vuole un wifi, ma solo per questa configurazione. Quando `adb devices` mostra il telefono, fissa una porta che funziona anche senza wifi:
```
adb tcpip 5555
adb connect localhost:5555
adb devices
```
Poi **spegni il wifi** e rilancia `adb devices`: deve restare una riga con `device`. Se lo vede, da qui in avanti basta il 5G. Imposta anche:
```
export ADA_ADB_SERIALE=localhost:5555
```
Se senza wifi il collegamento cade (dipende dal telefono), piano B: attiva l'**hotspot personale** del telefono prima di usare il Debug wireless, perché Android lo considera una rete wifi.
Dopo ogni **riavvio** del telefono la modalità 5555 si perde: serve un wifi per pochi minuti e si ripetono questi comandi.

## 5. Prova
Avvia Ada come da `docs/AVVIO.md`. In alto compare il tasto **⏹** quando il telefono è collegato: toccalo per fermare tutto all'istante, toccalo di nuovo per riattivare.

## Cose da sapere
- **Dopo un riavvio o un cambio di rete la porta cambia**: bisogna rifare `adb connect` con la nuova porta (l'abbinamento resta).
- **Il telefono deve essere sbloccato** mentre Ada lo usa. Se lo usi tu nello stesso momento, vi intralciate.
- **Il testo di ciò che Ada vede sullo schermo viene inviato a Claude** per capire cosa fare. Per questo le app finanziarie (Revolut, banche, PayPal), i gestori di password e gli autenticatori sono protette: Ada non le legge e non le tocca.
- **Il tasto finale di un acquisto lo premi sempre tu.** Il filtro è nel codice (`src/telefono/guardiano.py`): blocca "Acquista ora", "Effettua l'ordine", "Paga" e simili, e quando Ada arriva alla schermata finale non tocca più nulla. Carrello e cassa si aprono solo dopo che tu hai scelto un'opzione e premuto "Autorizza" nell'app, e l'autorizzazione dura 30 minuti.
- **Limite onesto del filtro:** riconosce i pulsanti dal testo e dall'identificativo. Un tasto d'acquisto con solo un'icona e un nome tecnico insolito potrebbe sfuggire, ma ogni schermata finale d'ordine ha di norma testi riconoscibili, e in quel caso Ada si ferma. Prima del primo acquisto vero guarda tu cosa c'è sulla schermata finale.
- Ada scrive solo testo senza accenti nei campi (limite di `adb input text`).
