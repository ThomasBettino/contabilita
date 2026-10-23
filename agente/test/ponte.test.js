#!/usr/bin/env node
// Prove degli script del turno di Agente 1, con dati inventati (nessun cliente vero).
// Uso: node agente/test/ponte.test.js        (esce con 1 se una prova fallisce)
// Le usa il Reparto Ricerca prima di ogni modifica: se una prova fallisce, la modifica non entra.
'use strict';
process.env.TZ = 'Europe/Rome';

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { execFileSync } = require('node:child_process');

const PONTE = path.join(__dirname, '..', 'ponte');
const ORARIO = path.join(__dirname, 'orario-finto.js');
let falliti = 0, fatti = 0;
function prova(nome, ok, dettagli) {
  fatti++;
  if (!ok) falliti++;
  console.log((ok ? '  ok   ' : '  FAIL ') + nome + (ok ? '' : ' -> ' + String(JSON.stringify(dettagli)).slice(0, 600)));
}
function cartella() { return fs.mkdtempSync(path.join(os.tmpdir(), 'agente1-test-')); }
function scrivi(file, dati) { fs.mkdirSync(path.dirname(file), { recursive: true }); fs.writeFileSync(file, typeof dati === 'string' ? dati : JSON.stringify(dati)); }
function leggi(file) { return JSON.parse(fs.readFileSync(file, 'utf8')); }
// Esegue uno script del ponte; con ora = "2026-10-23T05:07:00Z" finge che sia quell'ora.
function esegui(script, args, ora) {
  const pre = ora ? ['-r', ORARIO] : [];
  const env = Object.assign({}, process.env, { TZ: 'Europe/Rome' }, ora ? { ORARIO_FINTO: ora } : {});
  return execFileSync(process.execPath, pre.concat([path.join(PONTE, script)], args), { env, encoding: 'utf8' });
}
const pad = (n) => String(n).padStart(2, '0');
const giornoTra = (n) => { const d = new Date(); d.setDate(d.getDate() + n); return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()); };

console.log('Sintassi');
for (const f of fs.readdirSync(PONTE).filter((f) => f.endsWith('.js'))) {
  let ok = true;
  try { execFileSync(process.execPath, ['--check', path.join(PONTE, f)]); } catch (e) { ok = false; }
  prova(f + ' si legge', ok);
}

console.log('TURNO.md');
{
  const turno = fs.readFileSync(process.env.TURNO_MD || path.join(PONTE, 'TURNO.md'), 'utf8');
  const passi = turno.slice(turno.indexOf('## Passi'));
  const titoli = new Set([...passi.matchAll(/^\s*(?:\*\*)?(\d+[a-z]?)\. \*\*/gm)].map((m) => m[1]));
  const citati = [...new Set([...turno.matchAll(/passo (\d+[a-z]?)\b/g)].map((m) => m[1]))];
  const mancano = citati.filter((p) => !titoli.has(p));
  prova('ogni passo citato esiste', mancano.length === 0, { mancano, titoli: [...titoli] });
  const copiati = [...(turno.match(/^1\. \*\*Script\.\*\*[\s\S]*?\n1b\./m) || [''])[0].matchAll(/`?(\w+)\.js`/g)].map((m) => m[1]);
  const script = fs.readdirSync(PONTE).filter((f) => f.endsWith('.js')).map((f) => f.slice(0, -3));
  prova('il passo 1 copia tutti gli script del ponte', script.every((s) => copiati.includes(s)), { copiati, script });
  const usati = [...new Set([...turno.matchAll(/W\/ponte\/(\w+)\.js/g)].map((m) => m[1]))];
  prova('gli script usati esistono', usati.every((s) => script.includes(s)), usati.filter((s) => !script.includes(s)));
}

console.log('calendario.js');
{
  const W = cartella();
  const domani = giornoTra(1), dopo = giornoTra(3);
  scrivi(path.join(W, 'vendite/appuntamenti/a1.json'), { tipo: 'Consegna', con: 'Mario Bianchi', data: domani, ora: '09:00', auto: 'Citroën C3', fatto: false });
  scrivi(path.join(W, 'vendite/appuntamenti/a2.json'), { tipo: 'Appuntamento', con: 'Laura Verdi', data: dopo, ora: '15:30', auto: '', telefono: '3330000000', fatto: false });
  scrivi(path.join(W, 'vendite/appuntamenti/vecchio.json'), { tipo: 'Telefonata', con: 'Paolo Neri', data: giornoTra(-2), ora: '10:00', fatto: true });
  scrivi(path.join(W, 'vendite/trattative/t1.json'), { nome: 'Anna Rossi', marca: 'Citroën', modello: 'C5', tdData: dopo, tdOra: '11:00', stato: 'aperto' });
  // Laura Verdi è già nel calendario alla stessa ora: va adottata, non duplicata.
  scrivi(path.join(W, 'eventi.json'), { events: [{ id: 'ev-laura', summary: 'Appuntamento Verdi', start: { dateTime: dopo + 'T15:30:00+01:00' }, status: 'confirmed' }] });
  const fin = JSON.parse(esegui('calendario.js', ['finestra']));
  prova('finestra da oggi', fin.startTime.startsWith(giornoTra(0)) && fin.endTime > fin.startTime, fin);
  esegui('calendario.js', ['piano', path.join(W, 'vendite'), path.join(W, 'agente'), path.join(W, 'eventi.json'), path.join(W, 'out')]);
  const p = leggi(path.join(W, 'out/calendario-piano.json'));
  const crea = p.azioni.filter((a) => a.tipo === 'crea');
  prova('crea la consegna e il test drive', crea.length === 2 && crea.some((a) => a.chiave === 'app-a1' && a.evento.startTime === domani + 'T09:00:00') && crea.some((a) => a.chiave === 'td-t1' && /Test drive · Anna Rossi/.test(a.evento.summary)), p.azioni);
  prova('adotta l\'evento già presente', p.adottati.length === 1 && p.adottati[0].eventId === 'ev-laura', p.adottati);
  prova('ignora gli appuntamenti passati', !p.azioni.some((a) => a.chiave === 'app-vecchio'), p.azioni);
  scrivi(path.join(W, 'esiti.json'), crea.map((a, i) => ({ n: a.n, ok: true, eventId: 'nuovo-' + i })));
  esegui('calendario.js', ['registra', path.join(W, 'out'), path.join(W, 'esiti.json')]);
  const righe = leggi(path.join(W, 'out/righe/vendite-calendario.json'));
  prova('righe per il rapporto', righe.reparto === 'vendite' && righe.righe.length === 2 && /calendario/.test(righe.righe[0]), righe);
  // giro dopo: la mappa c'è, Mario spostato, Laura cancellata nell'app
  fs.cpSync(path.join(W, 'out/calendario'), path.join(W, 'agente/calendario'), { recursive: true });
  scrivi(path.join(W, 'vendite/appuntamenti/a1.json'), { tipo: 'Consegna', con: 'Mario Bianchi', data: domani, ora: '11:00', auto: 'Citroën C3', fatto: false });
  scrivi(path.join(W, 'vendite/appuntamenti/a2.json'), { tipo: 'Appuntamento', con: 'Laura Verdi', data: null, ora: '15:30', fatto: false });
  esegui('calendario.js', ['piano', path.join(W, 'vendite'), path.join(W, 'agente'), path.join(W, 'eventi.json'), path.join(W, 'out2')]);
  const p2 = leggi(path.join(W, 'out2/calendario-piano.json'));
  prova('sposta e cancella solo gli eventi suoi', p2.azioni.length === 2 && p2.azioni.some((a) => a.tipo === 'aggiorna' && a.eventId === 'nuovo-0' && a.evento.startTime === domani + 'T11:00:00') &&
    p2.azioni.some((a) => a.tipo === 'cancella' && a.eventId === 'ev-laura'), p2.azioni);
}

console.log('posta.js');
{
  const W = cartella();
  const q = esegui('posta.js', ['query']).trim();
  prova('query senza invii e promozioni', /-in:sent/.test(q) && /-category:promotions/.test(q), q);
  scrivi(path.join(W, 'thread.json'), { threads: [
    { id: 't1', messages: [{ id: 'm1', date: '2026-10-21T10:00:00Z', sender: 'noreply@gestionale.example', labelIds: ['INBOX'], subject: 'Nuova fattura ricevuta', snippet: 'Hai ricevuto da “AUTO ESEMPIO SRL ” sull&#39;azienda “ROSSI MARIO” la fattura n. 12 / 99 del 2026-10-09. A presto' }] },
    { id: 't2', messages: [{ id: 'm2', date: '2026-10-21T10:00:00Z', sender: 'io@example.com', labelIds: ['SENT'], subject: 'Fattura settembre', snippet: 'ti mando la fattura' }, { id: 'm3', date: '2026-10-21T11:00:00Z', sender: 'Studio Esempio <anna@studio.example>', labelIds: ['INBOX'], subject: 'R: Fattura settembre', snippet: 'Ciao, la fattura di settembre è pronta' }] },
    { id: 't3', messages: [{ id: 'm4', date: '2026-10-21T10:00:00Z', sender: 'shop@negozio.example', labelIds: ['CATEGORY_PROMOTIONS'], subject: 'Fattura gratis', snippet: 'promo' }] },
    { id: 't4', messages: [{ id: 'm5', date: '2026-10-21T10:00:00Z', sender: 'receipts@servizio.example', labelIds: ['INBOX'], subject: 'Your receipt', snippet: 'Thank you' }] },
    { id: 't5', messages: [{ id: 'm6', date: '2026-10-21T10:00:00Z', sender: 'ufficio@ditta.example', labelIds: ['INBOX'], subject: 'Automatic reply: Richiesta data fattura', snippet: 'Grazie per l\'e-mail. Questo indirizzo non è più presidiato.' }] }
  ] });
  esegui('posta.js', [path.join(W, 'thread.json'), path.join(W, 'agente'), path.join(W, 'out'), 'io@example.com']);
  const r = leggi(path.join(W, 'out/righe/contabilita-posta.json'));
  prova('trova la fattura SdI e quella del commercialista, senza risposte automatiche', r.righe.length === 2 && /fattura di ottobre: n\. 12 \/ 99 di Auto Esempio Srl/.test(r.righe[0]) && /settembre da Studio Esempio/.test(r.righe[1]), r.righe);
  fs.cpSync(path.join(W, 'out/posta'), path.join(W, 'agente/posta'), { recursive: true });
  esegui('posta.js', [path.join(W, 'thread.json'), path.join(W, 'agente'), path.join(W, 'out2'), 'io@example.com']);
  prova('non ripete i messaggi già visti', leggi(path.join(W, 'out2/righe/contabilita-posta.json')).righe.length === 0);
}

console.log('telefono.js');
{
  const W = cartella();
  prova('query solo delle email mandate da Thomas', /from:me/.test(esegui('telefono.js', ['query'])));
  scrivi(path.join(W, 'vendite/trattative/t1.json'), { nome: 'Bianchi Mario', marca: 'Citroën', modello: 'C3', stato: 'aperto' });
  scrivi(path.join(W, 'vendite/trattative/t2.json'), { nome: 'Alessandro', stato: 'aperto' });
  const ora = (min) => new Date(Date.now() - min * 60000).toISOString();
  const mia = (id, oggetto, testo, min, da) => ({ id, threads: undefined, messages: [{ id, date: ora(min), sender: da || 'Io <io@example.com>', subject: oggetto, snippet: testo }] });
  scrivi(path.join(W, 'thread.json'), { threads: [
    mia('n1', '[Telefono] WhatsApp | Mario Bianchi | 10:01', 'Buongiorno, la C3 è ancora disponibile?', 50),
    mia('n2', '[Telefono] Telefono|Chiamata persa|10:05', 'Laura Verdi', 40),
    mia('n3', '[Telefono] Banca | Codice di verifica | 10:06', 'Il tuo codice è 123456, non condividerlo', 39),
    mia('n4', '[Telefono] WhatsApp | Alessandro | 10:07', 'Ci vediamo stasera?', 38),
    mia('n5', '[Telefono] Gmail | Io | 10:08', '[Telefono] WhatsApp', 37),
    mia('n6', '[Telefono] WhatsApp | Mario Bianchi | 10:09', 'Scrivimi tu', 36, 'Estraneo <altro@example.com>')
  ] });
  esegui('telefono.js', [path.join(W, 'thread.json'), path.join(W, 'agente'), path.join(W, 'vendite'), path.join(W, 'out'), 'io@example.com']);
  const r = leggi(path.join(W, 'out/righe/telefono-notifiche.json'));
  const s = leggi(path.join(W, 'out/sync/telefono.json'));
  prova('racconta il cliente e la chiamata persa, non un nome solo', r.reparto === 'telefono' && r.righe.length === 2 && /Bianchi Mario \(preventivo Citroën C3 aperto\) ti ha scritto su WhatsApp/.test(r.righe[0]) && /chiamata persa da Laura Verdi/.test(r.righe[1]), r.righe);
  prova('nasconde i codici, salta Gmail e le email di altri', s.collegato && s.ultime.length === 4 && /••••/.test(s.testo) && !/123456/.test(s.testo) && !s.ultime.some((n) => n.app === 'Gmail' || n.id === 'n6'), s);
  fs.cpSync(path.join(W, 'out/sync'), path.join(W, 'agente/sync'), { recursive: true });
  esegui('telefono.js', [path.join(W, 'thread.json'), path.join(W, 'agente'), path.join(W, 'vendite'), path.join(W, 'out2'), 'io@example.com']);
  prova('non ripete le notifiche già viste', leggi(path.join(W, 'out2/righe/telefono-notifiche.json')).righe.length === 0 && leggi(path.join(W, 'out2/sync/telefono.json')).ultime.length === 4);
  scrivi(path.join(W, 'vuoto.json'), { threads: [] });
  esegui('telefono.js', [path.join(W, 'vuoto.json'), path.join(W, 'nessuno'), path.join(W, 'vendite'), path.join(W, 'out3'), 'io@example.com']);
  prova('senza MacroDroid dice che il telefono non è collegato', leggi(path.join(W, 'out3/sync/telefono.json')).collegato === false);
}

console.log('controllo.js');
{
  const W = cartella();
  scrivi(path.join(W, 'vendite/appuntamenti/a1.json'), { tipo: 'Consegna', con: 'Mario Bianchi', data: giornoTra(-3), ora: '09:00', fatto: false });
  scrivi(path.join(W, 'vendite/appuntamenti/a2.json'), { tipo: 'Appuntamento', con: 'Laura Verdi', clienteId: 't2', data: giornoTra(2), ora: '10:00', fatto: false });
  scrivi(path.join(W, 'vendite/trattative/t1.json'), { nome: 'Anna Rossi', stato: 'aperto', telefono: '333', richiamo: null });
  scrivi(path.join(W, 'vendite/trattative/t2.json'), { nome: 'Laura Verdi', stato: 'aperto', telefono: '333', richiamo: null });
  scrivi(path.join(W, 'vendite/trattative/t3.json'), { nome: 'Piero Blu', stato: 'venduto', formula: 'fd', margine: 0, dataVendita: giornoTra(-20), statoFin: 'attesa' });
  esegui('controllo.js', [path.join(W, 'vendite'), path.join(W, 'agente'), path.join(W, 'out')]);
  const r = leggi(path.join(W, 'out/righe/vendite-controllo.json'));
  const testo = r.righe.join(' | ');
  prova('segnala appuntamento passato, richiamo mancante, margine, finanziamento fermo', /Mario Bianchi/.test(testo) && /Anna Rossi/.test(testo) && !/Laura Verdi/.test(testo) && /margine/.test(testo) && /finanziamento/.test(testo), r.righe);
  fs.cpSync(path.join(W, 'out/sync'), path.join(W, 'agente/sync'), { recursive: true });
  esegui('controllo.js', [path.join(W, 'vendite'), path.join(W, 'agente'), path.join(W, 'out2')]);
  prova('non ripete le stesse segnalazioni', leggi(path.join(W, 'out2/righe/vendite-controllo.json')).righe.length === 0);
}

console.log('rapporto.js');
{
  const W = cartella();
  scrivi(path.join(W, 'righe/contabilita-posta.json'), { reparto: 'contabilita', addetto: 'posta', riepilogo: '1 fattura nuova', righe: ['è arrivata la fattura di ottobre.'] });
  scrivi(path.join(W, 'righe/ricerca-sviluppo.json'), { reparto: 'ricerca', addetto: 'sviluppatore', riepilogo: '1 miglioria', righe: ['ho reso più veloce il controllo delle vendite.'] });
  scrivi(path.join(W, 'out/notifiche/richiami.json'), { titolo: 'Richiami di oggi', testo: 'Mario Bianchi', fonte: 'Vendite' });
  const giorno = JSON.parse(esegui('rapporto.js', [W, path.join(W, 'u1')], '2026-10-23T13:07:00Z'));
  const email = leggi(path.join(W, 'u1/email.json'));
  prova('di giorno: notifica ed email con la voce di Agente 1', giorno.push && /Reparto Contabilità e mi ha detto che/.test(email.testo) && /Reparto Ricerca/.test(email.testo) && /Promemoria dei reparti/.test(email.testo), email.testo);
  prova('rapporto nell\'app', fs.readdirSync(path.join(W, 'u1/notifiche')).length === 1);
  const notte = JSON.parse(esegui('rapporto.js', [W, path.join(W, 'u2')], '2026-10-23T01:07:00Z'));
  prova('di notte niente notifica né email', notte.push === null && !fs.existsSync(path.join(W, 'u2/email.json')) && notte.accumulate === 3, notte);
  const M = cartella();
  scrivi(path.join(M, 'agente/sync/turno.json'), leggi(path.join(W, 'u2/sync/turno.json')));
  const mattino = JSON.parse(esegui('rapporto.js', [M, path.join(M, 'u')], '2026-10-23T05:07:00Z'));
  prova('al mattino racconta la notte e svuota', mattino.push && /stanotte/.test(leggi(path.join(M, 'u/email.json')).testo) && leggi(path.join(M, 'u/sync/turno.json')).accumulate.length === 0, mattino);
}

// Avvisi: Agente 1 deve poter chiudere (cancellare o segnare letto) un avviso per id o titolo.
(async () => {
  const html = fs.readFileSync(path.join(__dirname, '..', 'app', 'agente-1.html'), 'utf8');
  const m = html.match(/async function chiudiAvviso\(input\) \{[\s\S]*?\n  \}\n/);
  prova('avvisi: esiste lo strumento chiudi_avviso', !!m && /name: "chiudi_avviso"/.test(html) && /execute: chiudiAvviso/.test(html));
  if (m) {
    const fatto = [];
    const S = {
      notifiche: [{ id: 'a1', titolo: 'Fattura Verisure di settembre' }, { id: 'a2', titolo: 'Richiami di oggi' }],
      db: { doc: (p) => ({ delete: async () => fatto.push(['del', p]), update: async (d) => fatto.push(['upd', p, d]) }) }
    };
    const chiudiAvviso = require('node:vm').runInNewContext('(' + m[0] + ')', { S, String, Error });
    const r1 = await chiudiAvviso({ titolo: 'verisure' });
    const r2 = await chiudiAvviso({ id: 'a2', azione: 'letto' });
    const r3 = await chiudiAvviso({ titolo: 'inesistente' });
    S.notifiche = ['a', 'b', 'c', 'd'].map((x) => ({ id: 'r' + x, titolo: 'Richiamo ' + x }));
    const r4 = await chiudiAvviso({ titolo: 'richiamo' });
    prova('avvisi: cancella per titolo, segna letto per id, nessun falso positivo, chiede quale se sono troppi',
      r1.chiusi === 1 && r2.chiusi === 1 && r3.chiusi === 0 && r4.chiusi === 0 && r4.avvisi.length === 4 &&
      JSON.stringify(fatto) === JSON.stringify([['del', 'notifiche/a1'], ['upd', 'notifiche/a2', { letta: true }]]), fatto);
  }
  console.log(falliti ? falliti + ' prove fallite su ' + fatti : 'tutte le ' + fatti + ' prove superate');
  process.exit(falliti ? 1 : 0);
})();
