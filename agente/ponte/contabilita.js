#!/usr/bin/env node
// Ponte contabilità di Agente 1.
// Legge le fatture dallo script Google della app di contabilità e scrive sync/contabilita.json
// con gli stessi calcoli della app (Enasarco, bollo, tasse da accantonare, scadenze).
//
// Uso: NODE_USE_ENV_PROXY=1 node contabilita.js <cartella-uscita> [file-collegamento.json]
// Indirizzo e codice dello script vengono dal file di collegamento ({url, token}, salvato dall'app Agente 1)
// oppure da CONTABILITA_URL e CONTABILITA_TOKEN. Nel container il fetch di Node passa dal proxy solo con NODE_USE_ENV_PROXY=1.
// Se non è collegata esce senza scrivere; se non risponde scrive lo stato, così l'app lo mostra.
process.env.TZ = 'Europe/Rome';

const fs = require('node:fs');
const path = require('node:path');

const [dirUscita, fileCollegamento] = process.argv.slice(2);
if (!dirUscita) {
  console.error('Uso: node contabilita.js <cartella-uscita> [file-collegamento.json]');
  process.exit(1);
}

const collegamento = fileCollegamento && fs.existsSync(fileCollegamento) ? JSON.parse(fs.readFileSync(fileCollegamento, 'utf8')) : {};
const URL_SCRIPT = collegamento.url || process.env.CONTABILITA_URL;
const TOKEN = collegamento.token || process.env.CONTABILITA_TOKEN;
const ENASARCO = Number(process.env.ENASARCO_PCT || 8.5);
const TASSE = Number(process.env.TASSE_PCT || 30);
const GIORNI_SCADENZA = Number(process.env.GIORNI_SCADENZA || 30);
const SOGLIA_BOLLO = 77.47;

const arrotonda = (x) => Math.round(x * 100) / 100;
const giorniDa = (iso) => Math.floor((Date.now() - new Date(iso + 'T12:00:00').getTime()) / 86400000);
const euro = (n) => '€ ' + Number(n || 0).toLocaleString('it-IT', { minimumFractionDigits: 2, maximumFractionDigits: 2, useGrouping: 'always' });

// Stessa lettura dei numeri della app (accetta 1.234,56 e 1234.56).
function leggiNumero(s) {
  if (typeof s === 'number') return s;
  const v = parseFloat(String(s || '').replace(/[^\d,.-]/g, '').replace(/\.(?=\d{3}(\D|$))/g, '').replace(',', '.'));
  return Number.isNaN(v) ? 0 : v;
}

function calcola(f) {
  const lordo = leggiNumero(f.lordo);
  const bollo = f.bollo !== undefined && f.bollo !== '' ? leggiNumero(f.bollo) : (lordo > SOGLIA_BOLLO ? 2 : 0);
  const enasarco = Math.round(lordo * ENASARCO) / 100;
  const netto = lordo - enasarco;
  const tasse = Math.round(netto * TASSE) / 100;
  return { lordo, enasarco, tasse, bonifico: lordo + bollo - enasarco };
}

const scaduta = (f) => f.stato !== 'incassata' && !!f.data && giorniDa(f.data) > GIORNI_SCADENZA;

function riepilogo(fatture, accantonamenti, mese) {
  const scope = mese ? fatture.filter((f) => String(f.data || '').startsWith(mese)) : fatture;
  const somma = (campo, lista) => arrotonda(lista.reduce((s, f) => s + calcola(f)[campo], 0));
  return {
    fatture: scope.length,
    daIncassare: somma('bonifico', scope.filter((f) => f.stato !== 'incassata')),
    incassato: somma('bonifico', scope.filter((f) => f.stato === 'incassata')),
    enasarco: somma('enasarco', scope),
    tasse: somma('tasse', scope),
    accantonato: mese ? accantonamenti[mese] ?? 0 : null
  };
}

function scriviSync(dati) {
  const file = path.join(dirUscita, 'sync', 'contabilita.json');
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify(Object.assign({ aggiornato: new Date().toISOString(), fonte: 'App Contabilità' }, dati), null, 2) + '\n');
}

async function main() {
  if (!URL_SCRIPT || !TOKEN) {
    console.log(JSON.stringify({ stato: 'non configurata', motivo: 'manca il collegamento: indirizzo e codice dello script' }));
    return;
  }
  let j;
  try {
    const r = await fetch(URL_SCRIPT, {
      method: 'POST',
      headers: { 'Content-Type': 'text/plain;charset=utf-8' },
      body: JSON.stringify({ action: 'list', token: TOKEN })
    });
    j = await r.json();
    if (!j.ok) throw new Error(j.error || 'lo script ha risposto con errore');
  } catch (e) {
    const motivo = e.message + (e.cause && e.cause.code ? ' (' + e.cause.code + ')' : '');
    scriviSync({ stato: 'non raggiungibile', testo: 'Lo script della contabilità non ha risposto: ' + motivo + '.' });
    console.log(JSON.stringify({ stato: 'non raggiungibile', motivo }));
    return;
  }

  const fatture = j.fatture || [];
  const acc = j.accantonamenti || {};
  const oggi = new Date();
  const mese = oggi.getFullYear() + '-' + String(oggi.getMonth() + 1).padStart(2, '0');
  const tutto = riepilogo(fatture, acc);
  const delMese = riepilogo(fatture, acc, mese);
  const scadute = fatture.filter(scaduta).map((f) => `n. ${f.numero || '?'} del ${f.data}, ${euro(leggiNumero(f.lordo))}, ${giorniDa(f.data) - GIORNI_SCADENZA} giorni di ritardo`);
  const recenti = fatture
    .slice()
    .sort((a, b) => String(b.data || '').localeCompare(String(a.data || '')))
    .slice(0, 15)
    .map((f) => `n. ${f.numero || '?'} | ${f.data || '-'} | ${f.stato || '-'} | lordo ${euro(leggiNumero(f.lordo))} | ${(f.descrizione || '').slice(0, 80)}`);

  const testo = [
    `REGOLE DI CALCOLO: Enasarco ${ENASARCO}% sul lordo, bollo 2 € sopra 77,47 € (salvo valore indicato), tasse da accantonare ${TASSE}% sul netto dopo Enasarco, fattura scaduta se non incassata dopo ${GIORNI_SCADENZA} giorni.`,
    `TUTTE LE FATTURE: ${tutto.fatture} fatture, da incassare ${euro(tutto.daIncassare)}, incassato ${euro(tutto.incassato)}, Enasarco ${euro(tutto.enasarco)}, tasse da accantonare ${euro(tutto.tasse)}.`,
    `MESE ${mese}: ${delMese.fatture} fatture, da incassare ${euro(delMese.daIncassare)}, incassato ${euro(delMese.incassato)}, tasse da accantonare ${euro(delMese.tasse)}, già accantonato ${euro(delMese.accantonato)}.`,
    `SCADUTE (${scadute.length}): ${scadute.join('; ') || 'nessuna'}.`,
    `ULTIME FATTURE — numero | data | stato | lordo | descrizione:`,
    ...recenti
  ].join('\n');

  scriviSync({ testo });
  console.log(JSON.stringify({ stato: 'aggiornata', fatture: tutto.fatture, scadute: scadute.length }));
}

main();
