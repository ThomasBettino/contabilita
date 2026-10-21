#!/usr/bin/env node
// Ponte stelle di Agente 1.
// Legge le richieste di stelle in attesa dall'app "Un passo alla volta" (collezione richieste: {text, pts, at, name})
// e scrive sync/stelle.json più un avviso per le richieste non ancora segnalate.
// Agente 1 non conferma nulla: le stelle si confermano solo dall'app, con il pulsante 🔒.
//
// Uso: node stelle.js <cartella-richieste> <cartella-agente> <cartella-uscita>
//   <cartella-richieste>  export della collezione richieste (un file JSON per richiesta, nome = id)
//   <cartella-agente>     export di notifiche/ di Agente 1, per non segnalare due volte la stessa richiesta
//   <cartella-uscita>     qui vengono scritti sync/stelle.json e notifiche/<id>.json
process.env.TZ = 'Europe/Rome';

const fs = require('node:fs');
const path = require('node:path');

const APP = 'https://claude.ai/artifact/1JND3NoRY2ae7e8VH6RFyW';

const [dirRichieste, dirAgente, dirUscita] = process.argv.slice(2);
if (!dirRichieste || !dirAgente || !dirUscita) {
  console.error('Uso: node stelle.js <cartella-richieste> <cartella-agente> <cartella-uscita>');
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

function scrivi(file, dati) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify(dati, null, 2) + '\n');
}

const quando = (ms) => new Date(ms).toLocaleString('it-IT', { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
const testoBreve = (t) => String(t || '').replace(/\s+/g, ' ').trim().slice(0, 140);

const ora = new Date();
const richieste = Object.entries(leggiCartella(path.join(dirRichieste, 'richieste')))
  .map(([id, r]) => ({ id, testo: testoBreve(r.text), stelle: Number(r.pts) || 0, at: Number(r.at) || 0, nome: r.name || '' }))
  .sort((a, b) => a.at - b.at);
const totale = richieste.reduce((s, r) => s + r.stelle, 0);
const nome = (richieste.find((r) => r.nome) || {}).nome || 'Lei';

// Richieste già segnalate: gli avvisi delle stelle elencano gli id che coprono.
const giaSegnalate = new Set();
const notifiche = leggiCartella(path.join(dirAgente, 'notifiche'));
for (const n of Object.values(notifiche)) for (const id of n.richieste || []) giaSegnalate.add(id);
const ids = new Set(Object.keys(notifiche));

const nuove = richieste.filter((r) => !giaSegnalate.has(r.id));
const avvisi = [];
if (nuove.length) {
  const stelleNuove = nuove.reduce((s, r) => s + r.stelle, 0);
  const id = `stelle-${nuove[0].id}`;
  if (!ids.has(id)) {
    avvisi.push({
      id,
      titolo: nuove.length === 1 ? `${nome} aspetta ${stelleNuove} ⭐` : `${nome} aspetta ${stelleNuove} ⭐ per ${nuove.length} cose`,
      testo: nuove.map((r) => `${r.testo} (${r.stelle} ⭐)`).join(' · ') + '.' +
        (richieste.length > nuove.length ? ` In tutto ${richieste.length} richieste in attesa, ${totale} ⭐.` : '') +
        ' Confermale da Un passo alla volta, pulsante 🔒.',
      richieste: nuove.map((r) => r.id)
    });
  }
}

const testo = richieste.length
  ? `RICHIESTE DI STELLE IN ATTESA DI CONFERMA (${richieste.length}, ${totale} ⭐ in tutto), dalla più vecchia:\n` +
    richieste.map((r) => `- ${quando(r.at)} · ${r.stelle} ⭐ · ${r.testo}`).join('\n') +
    `\nSi confermano solo dall'app Un passo alla volta (${APP}), pulsante 🔒: Agente 1 non può confermarle.`
  : 'Nessuna richiesta di stelle in attesa.';

scrivi(path.join(dirUscita, 'sync', 'stelle.json'), {
  aggiornato: ora.toISOString(),
  fonte: 'Un passo alla volta',
  link: APP,
  nome,
  inAttesa: richieste.length,
  stelle: totale,
  testo
});
for (const a of avvisi) {
  scrivi(path.join(dirUscita, 'notifiche', a.id + '.json'), {
    titolo: a.titolo, testo: a.testo, ora: ora.toISOString(), fonte: 'Stelle', link: APP, richieste: a.richieste, letta: false
  });
}

console.log(JSON.stringify({ inAttesa: richieste.length, stelle: totale, nuoveNotifiche: avvisi.map(({ id, titolo, testo }) => ({ id, titolo, testo })) }, null, 2));
