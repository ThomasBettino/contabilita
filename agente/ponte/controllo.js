#!/usr/bin/env node
// Reparto Vendite, addetto Controllo: ogni turno controlla che i dati dell'app Andamento vendite siano a posto
// e dice ad Agente 1 solo le cose nuove da sistemare (quelle già segnalate restano in sync/controllo.firme).
//
// Uso: node controllo.js <export-vendite> <export-agente> <uscita>
//   <export-vendite>  trattative/ e appuntamenti/ di Andamento vendite
//   <export-agente>   sync/controllo.json del turno prima, se c'è
//   scrive <uscita>/sync/controllo.json e <uscita>/righe/vendite-controllo.json
process.env.TZ = 'Europe/Rome';

const fs = require('node:fs');
const path = require('node:path');

function leggiCartella(dir) {
  const o = {};
  if (!dir || !fs.existsSync(dir)) return o;
  for (const f of fs.readdirSync(dir)) if (f.endsWith('.json')) o[f.slice(0, -5)] = JSON.parse(fs.readFileSync(path.join(dir, f), 'utf8'));
  return o;
}
function leggiFile(file) { try { return JSON.parse(fs.readFileSync(file, 'utf8')); } catch (e) { return null; } }
function scrivi(file, dati) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify(dati, null, 2) + '\n');
}
const pad = (n) => String(n).padStart(2, '0');
const giorno = (d) => d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
const giorniFa = (iso, oggi) => Math.round((new Date(oggi + 'T12:00:00') - new Date(String(iso).slice(0, 10) + 'T12:00:00')) / 86400000);
const nomi = (l, n = 3) => l.slice(0, n).join(', ') + (l.length > n ? ' e altri ' + (l.length - n) : '');

const [dirVendite, dirAgente, dirUscita] = process.argv.slice(2);
if (!dirVendite || !dirAgente || !dirUscita) {
  console.error('Uso: node controllo.js <export-vendite> <export-agente> <uscita>');
  process.exit(1);
}
const ora = new Date();
const oggi = giorno(ora);
const trattative = Object.entries(leggiCartella(path.join(dirVendite, 'trattative'))).map(([id, t]) => Object.assign({ id }, t));
const appuntamenti = Object.entries(leggiCartella(path.join(dirVendite, 'appuntamenti'))).map(([id, a]) => Object.assign({ id }, a));
const aperte = trattative.filter((t) => (t.stato || 'aperto') === 'aperto');
const vendute = trattative.filter((t) => t.stato === 'venduto');

// Ogni voce ha una firma: cambia quando cambia l'elenco delle persone coinvolte, così una novità viene segnalata una volta sola.
const voci = [];
const voce = (tipo, persone, testo) => { if (persone.length) voci.push({ firma: tipo + ':' + persone.map((p) => p.id).sort().join(','), testo }); };

const passati = appuntamenti.filter((a) => a.data && a.data < oggi && !a.fatto).sort((a, b) => String(a.data).localeCompare(String(b.data)));
voce('app-passati', passati, passati.length + (passati.length === 1 ? ' appuntamento passato non è segnato come fatto' : ' appuntamenti passati non sono segnati come fatti') +
  ' (' + nomi(passati.map((a) => (a.tipo || 'Appuntamento') + ' con ' + (a.con || '?'))) + '): segnali o spostali.');

const tdPassati = aperte.filter((t) => t.tdData && t.tdData < oggi && !t.testDrive);
voce('td-passati', tdPassati, (tdPassati.length === 1 ? 'un test drive passato non è segnato come fatto' : tdPassati.length + ' test drive passati non sono segnati come fatti') +
  ' (' + nomi(tdPassati.map((t) => t.nome || '?')) + ').');

// Un cliente con un appuntamento o un test drive in arrivo non ha bisogno di un richiamo.
const conImpegno = new Set(appuntamenti.filter((a) => a.data && a.data >= oggi && a.clienteId).map((a) => a.clienteId));
const senzaRichiamo = aperte.filter((t) => !t.richiamo && !(t.tdData && t.tdData >= oggi) && !conImpegno.has(t.id));
voce('senza-richiamo', senzaRichiamo, (senzaRichiamo.length === 1 ? 'un preventivo aperto non ha una data di richiamo e rischia' : senzaRichiamo.length + ' preventivi aperti non hanno una data di richiamo e rischiano') +
  ' di restare fermi (' + nomi(senzaRichiamo.map((t) => t.nome || '?')) + ').');

const senzaTelefono = aperte.filter((t) => !String(t.telefono || '').trim());
voce('senza-telefono', senzaTelefono, (senzaTelefono.length === 1 ? 'un cliente aperto non ha' : senzaTelefono.length + ' clienti aperti non hanno') +
  ' il numero di telefono (' + nomi(senzaTelefono.map((t) => t.nome || '?')) + ').');

const senzaMargine = vendute.filter((t) => t.formula !== 'contanti' && !(Number(t.margine) > 0));
voce('senza-margine', senzaMargine, (senzaMargine.length === 1 ? 'una vendita non ha' : senzaMargine.length + ' vendite non hanno') +
  ' il margine, quindi la provvigione non si calcola (' + nomi(senzaMargine.map((t) => t.nome || '?')) + ').');

const finFermi = vendute.filter((t) => t.formula && t.formula !== 'contanti' && (!t.statoFin || t.statoFin === 'attesa') && t.dataVendita && giorniFa(t.dataVendita, oggi) > 7);
voce('fin-fermi', finFermi, (finFermi.length === 1 ? 'un finanziamento aspetta' : finFermi.length + ' finanziamenti aspettano') +
  ' la risposta da più di una settimana (' + nomi(finFermi.map((t) => t.nome || '?')) + ').');

const respinti = vendute.filter((t) => t.statoFin === 'rifiutato' && (t.statoCliente || 'da_saldare') !== 'consegnata');
voce('fin-rifiutati', respinti, (respinti.length === 1 ? 'un finanziamento è stato rifiutato' : respinti.length + ' finanziamenti sono stati rifiutati') +
  ' (' + nomi(respinti.map((t) => t.nome || '?')) + '): serve un\'altra soluzione di pagamento.');

const prima = leggiFile(path.join(dirAgente, 'sync', 'controllo.json')) || {};
const giaViste = new Set(prima.firme || []);
const nuove = voci.filter((v) => !giaViste.has(v.firma));
scrivi(path.join(dirUscita, 'sync', 'controllo.json'), {
  aggiornato: ora.toISOString(),
  stato: voci.length ? 'da sistemare' : 'tutto ok',
  voci: voci.map((v) => v.testo),
  firme: voci.map((v) => v.firma),
  controllati: { preventivi: aperte.length, vendite: vendute.length, appuntamenti: appuntamenti.length }
});
scrivi(path.join(dirUscita, 'righe', 'vendite-controllo.json'), {
  reparto: 'vendite', addetto: 'controllo',
  riepilogo: voci.length ? voci.length + (voci.length === 1 ? ' cosa da sistemare' : ' cose da sistemare') : 'dati in ordine',
  righe: nuove.map((v) => v.testo)
});
console.log(JSON.stringify({ voci: voci.length, nuove: nuove.length }));
