#!/usr/bin/env node
// Reparto Contabilità, addetto Posta: trova nelle email di Thomas le fatture arrivate (ricevute dallo SdI, dal commercialista,
// dai committenti) e le racconta ad Agente 1. Non segnala due volte lo stesso messaggio (posta/<idMessaggio> in Agente 1).
// Ricevute di acquisti e pubblicità non contano.
//
// Uso: node posta.js <thread.json> <export-agente> <uscita> <email-di-thomas>
//   <thread.json>     risposta di Gmail search_threads con la query stampata da `node posta.js query`
//   <export-agente>   posta/ di Agente 1, i messaggi già visti
//   scrive <uscita>/posta/<idMessaggio>.json, <uscita>/posta-togli.json (visti da cancellare) e <uscita>/righe/contabilita-posta.json
// Uso: node posta.js query    stampa la query da usare in search_threads
process.env.TZ = 'Europe/Rome';

const fs = require('node:fs');
const path = require('node:path');

const QUERY = 'newer_than:3d (fattura OR fatture OR fatturare OR fatturato OR "nota di credito") -in:sent -in:chats -category:promotions -category:social';
const MESI = ['gennaio', 'febbraio', 'marzo', 'aprile', 'maggio', 'giugno', 'luglio', 'agosto', 'settembre', 'ottobre', 'novembre', 'dicembre'];

function leggiCartella(dir) {
  const o = {};
  if (!dir || !fs.existsSync(dir)) return o;
  for (const f of fs.readdirSync(dir)) if (f.endsWith('.json')) o[f.slice(0, -5)] = JSON.parse(fs.readFileSync(path.join(dir, f), 'utf8'));
  return o;
}
function scrivi(file, dati) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify(dati, null, 2) + '\n');
}
const entita = (s) => String(s || '').replace(/&#(\d+);/g, (_, n) => String.fromCharCode(Number(n))).replace(/&quot;/g, '"').replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>');
const pulito = (s) => entita(s).replace(/[͏​-‍﻿]/g, '').replace(/\s+/g, ' ').trim();
const breve = (s, n) => (s.length > n ? s.slice(0, n - 1).replace(/\s+\S*$/, '') + '…' : s);
// "AUTOGHINZANI BERGAMO SRL" → "Autoghinzani Bergamo Srl"
const titolo = (s) => pulito(s).toLowerCase().replace(/(^|[\s'.(-])(\p{L})/gu, (m, a, b) => a + b.toUpperCase());
function chi(mittente) {
  const s = pulito(mittente);
  const nome = /^"?([^"<]+?)"?\s*</.exec(s);
  if (nome) return nome[1].trim();
  const ind = /([^\s<@]+)@([^\s>]+)/.exec(s);
  if (!ind) return s || 'qualcuno';
  // giulia@studioagosti.it → studioagosti.it (giulia)
  return ind[2].replace(/^(mail|email|noreply|no-reply|txn-email\d*)\./, '') + (/^(noreply|no-reply|info|invoice|notifiche)/i.test(ind[1]) ? '' : ' (' + ind[1] + ')');
}
function dataLunga(iso) {
  const d = new Date(iso + 'T12:00:00');
  return d.getDate() + ' ' + MESI[d.getMonth()] + ' ' + d.getFullYear();
}
function mese(testo) {
  const m = new RegExp('\\b(' + MESI.join('|') + ')\\b', 'i').exec(testo);
  return m ? m[1].toLowerCase() : '';
}

// Ogni messaggio non scritto da Thomas è una notizia a sé: due fatture nello stesso thread sono due righe.
function analizza(thread, m) {
  const etichette = m.labelIds || [];
  if (etichette.some((l) => /PROMOTIONS|SOCIAL|SPAM|TRASH/.test(l))) return null;
  const oggetto = pulito(m.subject || thread.subject);
  // Le risposte automatiche (fuori sede, casella non presidiata) non sono notizie.
  if (/^(automatic reply|auto[- ]?reply|risposta automatica|out of office|fuori sede|assente)\b/i.test(oggetto)) return null;
  const anteprima = pulito(m.snippet);
  const testo = oggetto + ' ' + anteprima;
  if (!/fattur|nota di credito/i.test(testo)) return null;
  // Ricevuta dallo SdI tramite il gestionale (TeamSystem e simili).
  const sdi = /ricevuto da\s*["“”]?\s*(.+?)\s*["“”]?\s+sull.{0,40}?la fattura n\.?\s*([\w./-]+(?:\s*\/\s*\d+)?)\s+del\s+(\d{4}-\d{2}-\d{2})/i.exec(anteprima);
  if (sdi) {
    const [, da, numero, data] = sdi;
    return {
      id: m.id, thread: thread.id || m.threadId, tipo: 'ricevuta', mittente: chi(m.sender), oggetto,
      riga: 'è arrivata la fattura di ' + MESI[Number(data.slice(5, 7)) - 1] + ': n. ' + numero.replace(/\s+/g, ' ') + ' di ' + titolo(da) + ', del ' + dataLunga(data) + '.'
    };
  }
  const mm = mese(testo);
  return {
    id: m.id, thread: thread.id || m.threadId, tipo: 'email', mittente: chi(m.sender), oggetto,
    riga: 'è arrivata un\'email' + (mm ? ' sulla fattura di ' + mm : ' su una fattura') + ' da ' + chi(m.sender) + ': «' + breve(oggetto, 80) + '». ' + breve(anteprima, 160)
  };
}

const args = process.argv.slice(2);
if (args[0] === 'query') { console.log(QUERY); process.exit(0); }
const [fileThread, dirAgente, dirUscita, email] = args;
if (!fileThread || !dirAgente || !dirUscita || !email) {
  console.error('Uso: node posta.js <thread.json> <export-agente> <uscita> <email-di-thomas> | query');
  process.exit(1);
}
let thread = [];
try {
  const r = JSON.parse(fs.readFileSync(fileThread, 'utf8'));
  thread = Array.isArray(r) ? r : r.threads || (r.payload && r.payload.threads) || [];
} catch (e) {
  console.error('Risposta di Gmail non leggibile: ' + e.message);
  process.exit(2);
}
const visti = leggiCartella(path.join(dirAgente, 'posta'));
const io = String(email).toLowerCase();
const ora = new Date().toISOString();
const nuove = [];
for (const t of thread) {
  for (const m of (t.messages || []).filter((x) => x && x.id && !String(x.sender || '').toLowerCase().includes(io))) {
    if (visti[m.id]) continue;
    const a = analizza(t, m);
    if (!a) continue;
    nuove.push(a);
    scrivi(path.join(dirUscita, 'posta', a.id + '.json'), { visto: ora, thread: a.thread, tipo: a.tipo, mittente: a.mittente, oggetto: a.oggetto });
  }
}
// I messaggi visti da più di 10 giorni non servono più: la ricerca guarda solo gli ultimi 3 giorni.
const vecchi = Object.entries(visti).filter(([, v]) => String(v.visto || '') < new Date(Date.now() - 10 * 86400000).toISOString()).map(([id]) => id);
scrivi(path.join(dirUscita, 'posta-togli.json'), vecchi);
scrivi(path.join(dirUscita, 'righe', 'contabilita-posta.json'), {
  reparto: 'contabilita', addetto: 'posta',
  riepilogo: thread.length + (thread.length === 1 ? ' email controllata' : ' email controllate') + (nuove.length ? ', ' + nuove.length + (nuove.length === 1 ? ' fattura nuova' : ' fatture nuove') : ', nessuna fattura nuova'),
  righe: nuove.map((a) => a.riga)
});
console.log(JSON.stringify({ controllate: thread.length, nuove: nuove.length }));
