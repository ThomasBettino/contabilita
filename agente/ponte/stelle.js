#!/usr/bin/env node
// Ponte stelle di Agente 1, usato dalla Sentinella stelle ogni 10 minuti.
// Legge dall'app "Un passo alla volta" le richieste di stelle in attesa (collezione richieste: {text, pts, at, name})
// e le segnalazioni di assistenza nuove (collezione assistenza: {text, type, page, status, at, name}),
// e scrive sync/stelle.json più un avviso per quelle non ancora segnalate.
// Agente 1 non conferma nulla: le stelle si confermano solo dall'app, con il pulsante 🔒.
//
// Uso: node stelle.js <export-stelle> <export-agente> <uscita>
//   <export-stelle>  export di Un passo alla volta: richieste/ e, se c'è, assistenza/ (solo quelle con status "nuova")
//   <export-agente>  export di Agente 1: sync/stelle.json (il controllo precedente) e, se c'è, notifiche/
//                    Le richieste già segnalate sono quelle in sync/stelle.ids e negli avvisi (campi richieste, segnalazioni).
//   <uscita>         scrive sempre sync/stelle.json (con l'ora del controllo) e notifiche/<id>.json per le novità
// Stampa un JSON: {inAttesa, stelle, assistenza, nuove, push} dove push è {titolo, testo} da mandare sul telefono,
// oppure null se non c'è niente di nuovo.
process.env.TZ = 'Europe/Rome';

const fs = require('node:fs');
const path = require('node:path');

const APP = 'https://claude.ai/artifact/1JND3NoRY2ae7e8VH6RFyW';
const TIPI = { bug: 'Non funziona', idea: 'Idea', dubbio: 'Non capisce', altro: 'Altro' };

const [dirStelle, dirAgente, dirUscita] = process.argv.slice(2);
if (!dirStelle || !dirAgente || !dirUscita) {
  console.error('Uso: node stelle.js <export-stelle> <export-agente> <uscita>');
  process.exit(1);
}

function leggiCartella(dir) {
  const o = {};
  if (!fs.existsSync(dir)) return o;
  for (const f of fs.readdirSync(dir)) {
    if (f.endsWith('.json')) o[f.slice(0, -5)] = JSON.parse(fs.readFileSync(path.join(dir, f), 'utf8'));
  }
  return o;
}
function leggiFile(file) {
  try { return JSON.parse(fs.readFileSync(file, 'utf8')); } catch (e) { return null; }
}
function scrivi(file, dati) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify(dati, null, 2) + '\n');
}

const quando = (ms) => new Date(ms).toLocaleString('it-IT', { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
const testoBreve = (t) => String(t || '').replace(/\s+/g, ' ').trim().slice(0, 140);

const ora = new Date();
const richieste = Object.entries(leggiCartella(path.join(dirStelle, 'richieste')))
  .map(([id, r]) => ({ id, testo: testoBreve(r.text), stelle: Number(r.pts) || 0, at: Number(r.at) || 0, wrote: Number(r.wrote) || 0, nome: r.name || '' }))
  .sort((a, b) => a.at - b.at);
// L'export di assistenza dovrebbe contenere solo le segnalazioni nuove; il filtro qui resiste a un export completo.
const segnalazioni = Object.entries(leggiCartella(path.join(dirStelle, 'assistenza')))
  .filter(([, s]) => s.status === 'nuova')
  .map(([id, s]) => ({ id, testo: testoBreve(s.text), tipo: TIPI[s.type] || 'Altro', pagina: String(s.page || '').slice(0, 40), at: Number(s.at) || 0 }))
  .sort((a, b) => a.at - b.at);
const totale = richieste.reduce((s, r) => s + r.stelle, 0);
const nome = (richieste.find((r) => r.nome) || {}).nome || 'Lei';

// Già segnalate: quelle viste al controllo precedente e quelle che hanno già un avviso.
const prima = leggiFile(path.join(dirAgente, 'sync', 'stelle.json')) || {};
const giaViste = new Set([].concat(prima.ids || [], prima.idsAssistenza || []));
const notifiche = leggiCartella(path.join(dirAgente, 'notifiche'));
for (const n of Object.values(notifiche)) for (const id of [].concat(n.richieste || [], n.segnalazioni || [])) giaViste.add(id);
const idsAvvisi = new Set(Object.keys(notifiche));

const nuove = richieste.filter((r) => !giaViste.has(r.id));
const nuoveSegnalazioni = segnalazioni.filter((s) => !giaViste.has(s.id));

const avvisi = [];
const stelleNuove = nuove.reduce((s, r) => s + r.stelle, 0);
if (nuove.length && !idsAvvisi.has('stelle-' + nuove[0].id)) {
  avvisi.push({
    id: 'stelle-' + nuove[0].id,
    titolo: nuove.length === 1 ? `${nome} aspetta ${stelleNuove} ⭐` : `${nome} aspetta ${stelleNuove} ⭐ per ${nuove.length} cose`,
    testo: nuove.map((r) => `${r.testo} (${r.stelle} ⭐)`).join(' · ') + '.' +
      (richieste.length > nuove.length ? ` In tutto ${richieste.length} richieste in attesa, ${totale} ⭐.` : '') +
      ' Confermale da Un passo alla volta, pulsante 🔒.',
    richieste: nuove.map((r) => r.id)
  });
}
if (nuoveSegnalazioni.length && !idsAvvisi.has('assistenza-' + nuoveSegnalazioni[0].id)) {
  avvisi.push({
    id: 'assistenza-' + nuoveSegnalazioni[0].id,
    titolo: `🛟 ${nome}: ${nuoveSegnalazioni.length === 1 ? 'una segnalazione' : nuoveSegnalazioni.length + ' segnalazioni'} su Un passo alla volta`,
    testo: nuoveSegnalazioni.map((s) => `${s.tipo}${s.pagina ? ' (' + s.pagina + ')' : ''}: ${s.testo}`).join(' · '),
    segnalazioni: nuoveSegnalazioni.map((s) => s.id)
  });
}

// La notifica sul telefono: prima le segnalazioni, poi le stelle, al massimo 8 righe.
let push = null;
if (avvisi.length) {
  const righe = [];
  for (const s of nuoveSegnalazioni) righe.push(`🛟 ${s.tipo}${s.pagina ? ' (' + s.pagina + ')' : ''}: ${s.testo}`);
  for (const r of nuove) righe.push(`+${r.stelle} ${r.testo}` + (r.wrote && r.at - r.wrote < 5 * 60000 ? ' (fatta subito dopo averla scritta)' : ''));
  const mostrate = righe.slice(0, 8);
  if (righe.length > 8) mostrate.push(`e altre ${righe.length - 8}`);
  if (richieste.length) mostrate.push(`Totale in attesa: ${totale} ⭐`);
  mostrate.push('Apri Un passo alla volta');
  const titolo = nuoveSegnalazioni.length
    ? `🛟 Assistenza: ${nuoveSegnalazioni.length === 1 ? '1 segnalazione' : nuoveSegnalazioni.length + ' segnalazioni'}` + (stelleNuove ? ` · ⭐ ${stelleNuove}` : '')
    : `⭐ ${stelleNuove} stelle da confermare`;
  push = { titolo: 'Agente 1 · ' + titolo, testo: mostrate.join('\n') };
}

const testo = (richieste.length
  ? `RICHIESTE DI STELLE IN ATTESA DI CONFERMA (${richieste.length}, ${totale} ⭐ in tutto), dalla più vecchia:\n` +
    richieste.map((r) => `- ${quando(r.at)} · ${r.stelle} ⭐ · ${r.testo}`).join('\n') +
    `\nSi confermano solo dall'app Un passo alla volta (${APP}), pulsante 🔒: Agente 1 non può confermarle.`
  : 'Nessuna richiesta di stelle in attesa.') +
  (segnalazioni.length ? `\nSEGNALAZIONI DI ASSISTENZA NUOVE (${segnalazioni.length}):\n` + segnalazioni.map((s) => `- ${quando(s.at)} · ${s.tipo}${s.pagina ? ' (' + s.pagina + ')' : ''}: ${s.testo}`).join('\n') : '');

const ids = richieste.map((r) => r.id), idsAssistenza = segnalazioni.map((s) => s.id);
const uguale = (a, b) => Array.isArray(b) && a.length === b.length && a.every((x, i) => x === b[i]);
const cambiato = !uguale(ids, prima.ids) || !uguale(idsAssistenza, prima.idsAssistenza) || prima.stelle !== totale;
scrivi(path.join(dirUscita, 'sync', 'stelle.json'), {
  // aggiornato: quando le richieste sono cambiate l'ultima volta; controllato: l'ultimo controllo della sentinella.
  aggiornato: cambiato || !prima.aggiornato ? ora.toISOString() : prima.aggiornato,
  controllato: ora.toISOString(),
  fonte: 'Un passo alla volta',
  link: APP,
  nome,
  inAttesa: richieste.length,
  stelle: totale,
  assistenza: segnalazioni.length,
  ids,
  idsAssistenza,
  testo
});
for (const a of avvisi) {
  scrivi(path.join(dirUscita, 'notifiche', a.id + '.json'), {
    titolo: a.titolo, testo: a.testo, ora: ora.toISOString(), fonte: 'Stelle', link: APP,
    ...(a.richieste ? { richieste: a.richieste } : {}), ...(a.segnalazioni ? { segnalazioni: a.segnalazioni } : {}), letta: false
  });
}

console.log(JSON.stringify({ inAttesa: richieste.length, stelle: totale, assistenza: segnalazioni.length, nuove: avvisi.map((a) => a.id), push }, null, 2));
