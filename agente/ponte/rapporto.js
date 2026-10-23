#!/usr/bin/env node
// Il rapporto di Agente 1: raccoglie quello che i reparti gli hanno detto in questo turno e lo racconta a Thomas
// con la sua voce ("Ho parlato con il Reparto Contabilità e mi ha detto che..."), per l'app, per email e per il telefono.
// Di notte (dalle 0 alle 7) la squadra lavora in silenzio: le novità si accumulano e arrivano tutte al primo turno del mattino.
//
// Uso: node rapporto.js <W> <uscita>
//   <W>  cartella di lavoro del turno: legge W/righe/*.json (reparti e compiti), W/out/notifiche/*.json (avvisi nuovi),
//        W/out-ordini/ordini/*.json e W/out-meteo*/ordini-meteo/*.json (esiti degli ordini), W/agente/sync/turno.json (turno prima)
//   scrive <uscita>/sync/turno.json, <uscita>/notifiche/rapporto-<giorno>-<ora><minuti>.json se ci sono novità dei reparti,
//   <uscita>/email.json se c'è qualcosa da mandare a Thomas; stampa {push, email, notte, novita}
process.env.TZ = 'Europe/Rome';

const fs = require('node:fs');
const path = require('node:path');

const APP = 'https://claude.ai/artifact/QKUvJ2gwq8cVGTnkCukMnc';
const REPARTI = { vendite: 'Vendite', contabilita: 'Contabilità', meteo: 'Meteo', stelle: 'Stelle', agenda: 'Agenda', ricerca: 'Ricerca', telefono: 'Telefono', agente1: 'Agente 1' };
const ORDINE = ['vendite', 'telefono', 'contabilita', 'meteo', 'stelle', 'agenda', 'ricerca'];
const DA_FONTE = { Vendite: 'vendite', 'Andamento vendite': 'vendite', Stelle: 'stelle', Meteo: 'meteo', 'Contabilità': 'contabilita', Ricerca: 'ricerca' };

function leggiCartella(dir) {
  const o = {};
  if (!dir || !fs.existsSync(dir)) return o;
  for (const f of fs.readdirSync(dir).sort()) if (f.endsWith('.json')) {
    try { o[f.slice(0, -5)] = JSON.parse(fs.readFileSync(path.join(dir, f), 'utf8')); } catch (e) { /* file rotto: si salta */ }
  }
  return o;
}
function leggiFile(file) { try { return JSON.parse(fs.readFileSync(file, 'utf8')); } catch (e) { return null; } }
function scrivi(file, dati) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify(dati, null, 2) + '\n');
}
const pad = (n) => String(n).padStart(2, '0');
const nomeReparto = (k) => REPARTI[k] || String(k || 'Agente 1');
const breve = (s, n) => { s = String(s || '').replace(/\s+/g, ' ').trim(); return s.length > n ? s.slice(0, n - 1).replace(/\s+\S*$/, '') + '…' : s; };
// Accorcia tenendo gli a capo, per la notifica sul telefono.
const taglia = (s, n) => (s.length > n ? s.slice(0, n - 1).replace(/\s+\S*$/, '') + '…' : s);
const inOrdine = (chiavi) => ORDINE.filter((k) => chiavi.includes(k)).concat(chiavi.filter((k) => !ORDINE.includes(k)));

const [W, dirUscita] = process.argv.slice(2);
if (!W || !dirUscita) {
  console.error('Uso: node rapporto.js <W> <uscita>');
  process.exit(1);
}
const ora = new Date();
const notte = ora.getHours() < 7;
const prima = leggiFile(path.join(W, 'agente', 'sync', 'turno.json')) || {};

// 1. Quello che dicono i reparti in questo turno.
const notizie = []; // {reparto, riga}
const reparti = Object.assign({}, prima.reparti || {});
for (const r of Object.values(leggiCartella(path.join(W, 'righe')))) {
  const k = r.reparto || 'agente1';
  reparti[k] = reparti[k] || { addetti: {} };
  reparti[k].ultimo = ora.toISOString();
  reparti[k].addetti = Object.assign({}, reparti[k].addetti || {}, { [r.addetto || 'compiti']: { ultimo: ora.toISOString(), riepilogo: String(r.riepilogo || '') } });
  for (const riga of [].concat(r.righe || [])) if (String(riga).trim()) notizie.push({ reparto: k, riga: String(riga).trim() });
}
// 2. Esiti degli ordini che Agente 1 aveva passato ai reparti.
const esiti = [];
for (const dir of [path.join(W, 'out-ordini', 'ordini')].concat(fs.existsSync(W) ? fs.readdirSync(W).filter((d) => /^out-meteo/.test(d)).map((d) => path.join(W, d, 'ordini-meteo')) : [])) {
  const meteo = /out-meteo/.test(dir);
  for (const o of Object.values(leggiCartella(dir))) {
    if (o.stato === 'eseguito') esiti.push({ reparto: meteo ? 'meteo' : 'vendite', riga: (meteo ? 'verifica fatta: ' + breve(o.esito, 160) + ' La schermata è in Agente 1.' : 'ho eseguito il tuo ordine: ' + breve(o.esito, 160)) });
    else if (o.stato === 'errore') esiti.push({ reparto: meteo ? 'meteo' : 'vendite', riga: 'un ordine non è riuscito: ' + breve(o.esito, 160) });
  }
}
// 3. Avvisi nuovi preparati dai reparti in questo turno (richiami, impegni, stelle): vanno solo per email e sul telefono,
//    perché nell'app ci sono già come avvisi a sé.
const avvisi = Object.values(leggiCartella(path.join(W, 'out', 'notifiche'))).filter((n) => n && n.titolo)
  .map((n) => ({ reparto: DA_FONTE[n.fonte] || 'vendite', riga: n.titolo + (n.testo ? ': ' + breve(n.testo, 200) : '') }));

const novita = notizie.concat(esiti);
const tutto = novita.concat(avvisi.map((v) => Object.assign({ avviso: true }, v)));

function racconto(voci, apertura) {
  const promemoria = voci.filter((v) => v.avviso).map((v) => '- ' + v.riga);
  voci = voci.filter((v) => !v.avviso);
  const perReparto = {};
  for (const v of voci) (perReparto[v.reparto] = perReparto[v.reparto] || []).push(v.riga);
  const chiavi = inOrdine(Object.keys(perReparto));
  const coda = promemoria.length ? '\n\nPromemoria dei reparti:\n' + promemoria.join('\n') : '';
  if (!voci.length) return (apertura ? apertura + '\n\n' : '') + coda.trim();
  if (voci.length === 1) {
    const v = voci[0];
    return (apertura ? apertura + ' ' : '') + (v.reparto === 'agente1' ? 'Ho fatto io: ' : 'Ho parlato con il Reparto ' + nomeReparto(v.reparto) + ' e mi ha detto che ') + v.riga + coda;
  }
  return (apertura ? apertura + '\n\n' : '') + chiavi.map((k) => (k === 'agente1' ? 'Ho fatto io:' : 'Ho parlato con il Reparto ' + nomeReparto(k) + ' e mi ha detto che:') +
    '\n' + perReparto[k].map((r) => '- ' + r).join('\n')).join('\n\n') + coda;
}

let notteAccumulata = (prima.accumulate || []).slice();
let push = null, email = null;
if (notte) {
  notteAccumulata = notteAccumulata.concat(tutto.map((v) => Object.assign({ ora: ora.toISOString() }, v))).slice(-60);
} else {
  const blocchi = [];
  if (notteAccumulata.length) blocchi.push(racconto(notteAccumulata, 'Buongiorno Thomas, stanotte la squadra ha lavorato.'));
  if (tutto.length) blocchi.push(racconto(tutto, notteAccumulata.length ? 'E in quest\'ultima ora:' : 'Ciao Thomas.'));
  if (blocchi.length) {
    const testo = blocchi.join('\n\n');
    const coinvolti = inOrdine([...new Set(notteAccumulata.concat(tutto).map((v) => v.reparto))]).map(nomeReparto);
    const titolo = 'Agente 1 · ' + (notteAccumulata.length ? 'buongiorno, ' : '') + coinvolti.join(', ');
    push = { titolo, testo: taglia(testo.replace(/\n\n/g, '\n'), 700) };
    email = { oggetto: breve(titolo + ': ' + (notteAccumulata.concat(tutto)[0].riga), 120), testo: testo + '\n\nApri Agente 1: ' + APP + '\n\nAgente 1' };
    scrivi(path.join(dirUscita, 'email.json'), email);
  }
  notteAccumulata = [];
}

// Il rapporto nell'app: solo le novità dei reparti e degli ordini (gli avvisi hanno già la loro voce).
if (novita.length) {
  const id = 'rapporto-' + ora.getFullYear() + pad(ora.getMonth() + 1) + pad(ora.getDate()) + '-' + pad(ora.getHours()) + pad(ora.getMinutes());
  const coinvolti = inOrdine([...new Set(novita.map((v) => v.reparto))]).map(nomeReparto);
  scrivi(path.join(dirUscita, 'notifiche', id + '.json'), {
    titolo: 'Agente 1 · ' + coinvolti.join(', '), testo: racconto(novita, ''), ora: ora.toISOString(), fonte: 'Agente 1', tipo: 'rapporto',
    reparti: [...new Set(novita.map((v) => v.reparto))], voci: novita, letta: false, link: APP
  });
}

const prossimo = new Date(ora); prossimo.setMinutes(7, 0, 0); if (prossimo <= ora) prossimo.setHours(prossimo.getHours() + 1);
scrivi(path.join(dirUscita, 'sync', 'turno.json'), {
  aggiornato: ora.toISOString(), prossimo: prossimo.toISOString(), notte,
  reparti, ultime: novita.slice(0, 20), accumulate: notteAccumulata
});
console.log(JSON.stringify({ push, email: !!email, notte, novita: novita.length, avvisi: avvisi.length, accumulate: notteAccumulata.length }, null, 2));
