#!/usr/bin/env node
// Reparto Telefono, addetto Notifiche: legge le notifiche del telefono Android di Thomas, che MacroDroid inoltra alla sua Gmail
// (oggetto "[Telefono] <app> | <titolo> | <ora>", testo = testo della notifica), e le passa ad Agente 1.
// Conta solo le email mandate da Thomas stesso; nasconde i codici di verifica. Nel rapporto racconta solo le chiamate perse
// e i messaggi dei clienti con una trattativa aperta: il resto lo tiene per lo specialista Telefono (sync/telefono).
//
// Uso: node telefono.js <thread.json> <export-agente> <export-vendite> <uscita> <email-di-thomas>
//   <thread.json>      risposta di Gmail search_threads con la query stampata da `node telefono.js query`
//   <export-agente>    cartella con sync/telefono.json (notifiche già viste), se c'è
//   <export-vendite>   cartella con trattative/*.json dell'app vendite, per riconoscere i clienti
//   scrive <uscita>/sync/telefono.json e <uscita>/righe/telefono-notifiche.json
// Uso: node telefono.js query    stampa la query da usare in search_threads
process.env.TZ = 'Europe/Rome';

const fs = require('node:fs');
const path = require('node:path');

const QUERY = 'from:me subject:Telefono newer_than:2d';
const ORE = 48;

function leggiCartella(dir) {
  const o = {};
  if (!dir || !fs.existsSync(dir)) return o;
  for (const f of fs.readdirSync(dir)) if (f.endsWith('.json')) {
    try { o[f.slice(0, -5)] = JSON.parse(fs.readFileSync(path.join(dir, f), 'utf8')); } catch (e) { /* file rotto: si salta */ }
  }
  return o;
}
function leggiFile(file) { try { return JSON.parse(fs.readFileSync(file, 'utf8')); } catch (e) { return null; } }
function scrivi(file, dati) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify(dati, null, 2) + '\n');
}
const entita = (s) => String(s || '').replace(/&#(\d+);/g, (_, n) => String.fromCharCode(Number(n))).replace(/&quot;/g, '"').replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>');
const pulito = (s) => entita(s).replace(/[͏​-‍﻿]/g, '').replace(/\s+/g, ' ').trim();
const breve = (s, n) => (s.length > n ? s.slice(0, n - 1).replace(/\s+\S*$/, '') + '…' : s);
const pad = (n) => String(n).padStart(2, '0');
const oraBreve = (iso) => { const d = new Date(iso); return pad(d.getHours()) + ':' + pad(d.getMinutes()); };
const parole = (s) => pulito(s).toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').split(/[^a-z0-9]+/).filter((p) => p.length >= 3);
// I codici di accesso e di verifica non escono dal telefono: si vede che è arrivato un codice, non il codice.
const senzaCodici = (s) => (/codic|code|otp|verific|password|pin\b|accesso|login|2fa|autenticaz/i.test(s) ? s.replace(/\b[A-Z0-9]{0,3}\d{4,8}\b/g, '••••') : s);

function notifica(m, t) {
  const oggetto = pulito(m.subject || t.subject);
  const r = /^\[telefono\]\s*(.*)$/i.exec(oggetto);
  if (!r) return null;
  const parti = r[1].split(/\s+\|\s+/);
  const app = (parti[0] || 'App').trim();
  // Le notifiche di Gmail e di MacroDroid non si inoltrano: creerebbero un giro senza fine.
  if (/^(gmail|macrodroid)$/i.test(app)) return null;
  const titolo = (parti[1] || '').trim();
  return { id: m.id, app, titolo: senzaCodici(titolo), testo: senzaCodici(breve(pulito(m.snippet), 220)), ora: new Date(m.date || Date.now()).toISOString() };
}

const persa = (n) => /telefono|phone|dialer|chiamat|call/i.test(n.app + ' ' + n.titolo + ' ' + n.testo) && /pers[ae]\b|missed|senza risposta|non rispost/i.test(n.titolo + ' ' + n.testo);
// "Chiamata persa" con il nome nel testo, oppure il nome nel titolo.
const chiChiama = (n) => (/^chiamat|^missed|^\d+ chiamat/i.test(n.titolo) ? n.testo : n.titolo) || 'un numero';

function clienti(dirVendite) {
  return Object.values(leggiCartella(path.join(dirVendite || '', 'trattative')))
    .filter((t) => t && t.nome && (t.stato === 'aperto' || (t.stato === 'venduto' && t.statoCliente !== 'consegnata')))
    .map((t) => ({ nome: pulito(t.nome), parole: parole(t.nome), auto: [t.marca, t.modello].filter(Boolean).join(' '), stato: t.stato }))
    .filter((c) => c.parole.length);
}
// Un cliente è riconosciuto se nome e cognome (tutte le parole del nome, almeno due) sono nel nome di chi scrive o chiama:
// un nome solo, come "Alessandro", potrebbe essere chiunque.
function cliente(chi, elenco) {
  const nel = new Set(parole(chi));
  return elenco.find((c) => c.parole.length >= 2 && c.parole.every((p) => nel.has(p)));
}
const scheda = (c) => c.nome + ' (' + (c.stato === 'aperto' ? 'preventivo' : 'vendita') + (c.auto ? ' ' + c.auto : '') + (c.stato === 'aperto' ? ' aperto' : ' da consegnare') + ')';

const args = process.argv.slice(2);
if (args[0] === 'query') { console.log(QUERY); process.exit(0); }
const [fileThread, dirAgente, dirVendite, dirUscita, email] = args;
if (!fileThread || !dirAgente || !dirUscita || !email) {
  console.error('Uso: node telefono.js <thread.json> <export-agente> <export-vendite> <uscita> <email-di-thomas> | query');
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
const io = String(email).toLowerCase();
const prima = leggiFile(path.join(dirAgente, 'sync', 'telefono.json')) || {};
const visti = new Set(prima.visti || []);
const ora = new Date();
const limite = new Date(ora.getTime() - ORE * 3600000).toISOString();

const tutte = new Map((prima.ultime || []).filter((n) => n.ora >= limite).map((n) => [n.id, n]));
const nuove = [];
for (const t of thread) {
  for (const m of t.messages || []) {
    if (!m || !m.id || !String(m.sender || '').toLowerCase().includes(io)) continue;
    const n = notifica(m, t);
    if (!n || n.ora < limite) continue;
    tutte.set(n.id, n);
    if (!visti.has(n.id)) { nuove.push(n); visti.add(n.id); }
  }
}
const ultime = [...tutte.values()].sort((a, b) => b.ora.localeCompare(a.ora)).slice(0, 30);
const elenco = clienti(dirVendite);
const righe = [];
for (const n of nuove.sort((a, b) => a.ora.localeCompare(b.ora))) {
  if (persa(n)) {
    const chi = chiChiama(n), c = cliente(chi, elenco);
    righe.push('hai una chiamata persa da ' + (c ? scheda(c) : chi) + ' alle ' + oraBreve(n.ora) + '.');
    continue;
  }
  const c = cliente(n.titolo, elenco);
  if (c) righe.push(scheda(c) + ' ti ha scritto su ' + n.app + ' alle ' + oraBreve(n.ora) + ': «' + breve(n.testo, 140) + '»');
}

const collegato = ultime.length > 0 || !!prima.ultima;
const perApp = {};
for (const n of ultime) perApp[n.app] = (perApp[n.app] || 0) + 1;
const testo = !collegato
  ? 'Il telefono non è ancora collegato: nessuna notifica inoltrata da MacroDroid alla Gmail di Thomas negli ultimi 2 giorni.'
  : 'NOTIFICHE DEL TELEFONO (ultime ' + ORE + ' ore, dalla più recente; ' + Object.entries(perApp).map(([a, k]) => a + ' ' + k).join(', ') + '):\n' +
    (ultime.length ? ultime.map((n) => '- ' + n.ora.slice(0, 10) + ' ' + oraBreve(n.ora) + ' ' + n.app + (n.titolo ? ' · ' + n.titolo : '') + (n.testo ? ': ' + n.testo : '')).join('\n') : '- nessuna');
scrivi(path.join(dirUscita, 'sync', 'telefono.json'), {
  aggiornato: ora.toISOString(), fonte: 'Notifiche del telefono (MacroDroid → Gmail)', collegato,
  ultima: ultime.length ? ultime[0].ora : prima.ultima || null, perApp, ultime, visti: [...visti].slice(-400), testo
});
scrivi(path.join(dirUscita, 'righe', 'telefono-notifiche.json'), {
  reparto: 'telefono', addetto: 'notifiche',
  riepilogo: collegato ? nuove.length + (nuove.length === 1 ? ' notifica nuova' : ' notifiche nuove') : 'telefono non ancora collegato',
  righe
});
console.log(JSON.stringify({ email: thread.length, nuove: nuove.length, righe: righe.length, collegato }));
