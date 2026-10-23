# Prova 1: leggere le notifiche Revolut dal telefono

Scopo: capire se Revolut si lascia leggere e quanto sono utili le sue notifiche. Se funziona, il resto del sistema si costruisce sopra.

## Cosa serve (5 minuti, sul telefono Android)

1. Installa **Termux** e **Termux:API** da **F-Droid** (non dal Play Store: quella versione è obsoleta).
2. Apri Termux e scrivi:
   ```
   pkg install python git termux-api
   ```
3. In Android: Impostazioni, Accesso speciale, **Accesso alle notifiche**, e attiva **Termux:API**.
4. Scarica il progetto:
   ```
   git clone https://github.com/thomasbettino/contabilita
   cd contabilita
   git checkout ccr-b35db874-occc4m
   ```

## Lancio

Fatti mandare una notifica da Revolut (paga qualcosa con la carta, oppure aspetta un movimento), poi:

```
python -m src.revolut.ingest
```

Scrive in `movimenti.db` e stampa un riepilogo delle uscite per esercente.

## Cosa devi dirmi

- Il comando ha funzionato senza errori?
- Quanti movimenti riconosciuti e quanti "non_riconosciuti"?
- Se ci sono non riconosciuti: copiami 3-4 esempi di testo (togli i dati che vuoi tenere privati). Con quelli miglioro il parser. È anche il primo esempio del ciclo di auto-miglioramento.

## Limiti noti

- Il parser è scritto su formati ipotizzati: i testi reali di Revolut possono essere diversi.
- Android conserva solo le notifiche ancora presenti nella tendina: lo script va lanciato spesso (poi lo schedulo).
- Nessuna azione sul denaro: questo script legge soltanto.

## Lettura automatica ogni 15 minuti (Termux)

```
git pull
chmod +x scripts/ingest.sh
termux-job-scheduler -s ~/contabilita/scripts/ingest.sh --period-ms 900000 --persisted true --job-id 1
```

- Controlla che sia attivo: `termux-job-scheduler --pending`
- Ferma: `termux-job-scheduler --cancel --job-id 1`
- Vedi cosa ha fatto: `tail ~/ingest.log`
- I movimenti stanno in `~/movimenti.db` (fuori dal repo, mai su GitHub).
- 15 minuti è il minimo che Android permette. Se cancelli una notifica prima, il movimento non viene letto.
