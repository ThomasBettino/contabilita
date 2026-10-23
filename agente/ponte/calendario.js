#!/usr/bin/env node
// Reparto Vendite, addetto Calendario: porta nel Google Calendar di Thomas gli appuntamenti e i test drive
// dell'app Andamento vendite, senza chiedere conferma, e tiene la mappa appuntamento → evento in calendario/<chiave>.
// Tocca solo gli eventi che ha creato o adottato lui (quelli nella mappa): mai gli altri eventi del calendario.
//
// Uso: node calendario.js piano <export-vendite> <export-agente> <eventi.json> <uscita>
//        <export-vendite>  appuntamenti/ e trattative/ di Andamento vendite
//        <export-agente>   calendario/ di Agente 1 (la mappa)
//        <eventi.json>     risposta di Google Calendar list_events sulla finestra stampata da `node calendario.js finestra`
//        scrive <uscita>/calendario-piano.json con le azioni da fare in Google Calendar
//      node calendario.js registra <uscita> <esiti.json>
//        <esiti.json>      [{n, ok, eventId?, errore?}] uno per azione del piano
//        scrive <uscita>/calendario/<chiave>.json (mappa da salvare), <uscita>/calendario-togli.json (chiavi da cancellare)
//        e <uscita>/righe/vendite-calendario.json per il rapporto di Agente 1
//      node calendario.js finestra
//        stampa {startTime, endTime} per list_events: da oggi a 60 giorni
process.env.TZ = 'Europe/Rome';

const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');

const GIORNI_FINESTRA = 60;
const DURATA = { Telefonata: 15, 'Perizia permuta': 30, 'Firma contratto': 45, 'Test drive': 45 };
const GG = ['domenica', 'lunedì', 'martedì', 'mercoledì', 'giovedì', 'venerdì', 'sabato'];
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
const pad = (n) => String(n).padStart(2, '0');
const giorno = (d) => d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
const locale = (d) => giorno(d) + 'T' + pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':00';
function finestra(ora) {
  const da = new Date(ora); da.setHours(0, 0, 0, 0);
  const a = new Date(da); a.setDate(a.getDate() + GIORNI_FINESTRA + 1);
  return { startTime: locale(da), endTime: locale(a) };
}
// "venerdì 23 ottobre alle 9:00"
function quando(data, ora) {
  const d = new Date(data + 'T12:00:00');
  return GG[d.getDay()] + ' ' + d.getDate() + ' ' + MESI[d.getMonth()] + (ora ? ' alle ' + Number(ora.slice(0, 2)) + ':' + ora.slice(3, 5) : '');
}
const pulito = (s) => String(s || '').replace(/\s+/g, ' ').trim();
const norm = (s) => pulito(s).toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
const firmaDi = (e) => crypto.createHash('sha1').update([e.summary, e.startTime, e.endTime, e.allDay ? 1 : 0, e.location || ''].join('|')).digest('hex').slice(0, 12);

// Gli impegni dell'app vendite da tenere in calendario: appuntamenti con data e test drive prenotati.
function impegni(dirVendite) {
  const out = {};
  for (const [id, a] of Object.entries(leggiCartella(path.join(dirVendite, 'appuntamenti')))) {
    if (!a || !a.data || !/^\d{4}-\d{2}-\d{2}$/.test(a.data)) continue;
    const tipo = pulito(a.tipo) || 'Appuntamento';
    const con = pulito(a.con) || 'cliente';
    out['app-' + id] = {
      chiave: 'app-' + id, tipo, con, data: a.data, ora: /^\d{2}:\d{2}$/.test(a.ora || '') ? a.ora : '', auto: pulito(a.auto),
      telefono: pulito(a.telefono), note: pulito(a.note),
      descr: tipo + ' con ' + con
    };
  }
  for (const [id, t] of Object.entries(leggiCartella(path.join(dirVendite, 'trattative')))) {
    if (!t || !t.tdData || !/^\d{4}-\d{2}-\d{2}$/.test(t.tdData) || t.stato === 'perso') continue;
    const con = pulito(t.nome) || 'cliente';
    out['td-' + id] = {
      chiave: 'td-' + id, tipo: 'Test drive', con, data: t.tdData, ora: /^\d{2}:\d{2}$/.test(t.tdOra || '') ? t.tdOra : '',
      auto: pulito([t.marca, t.modello].filter(Boolean).join(' ')), telefono: pulito(t.telefono), note: '',
      descr: 'test drive di ' + con
    };
  }
  return out;
}

function evento(i) {
  const e = { summary: i.tipo + ' · ' + i.con + (i.auto ? ' · ' + i.auto : '') };
  if (i.ora) {
    const inizio = new Date(i.data + 'T' + i.ora + ':00');
    const fine = new Date(inizio.getTime() + (DURATA[i.tipo] || 60) * 60000);
    e.startTime = locale(inizio);
    e.endTime = locale(fine);
  } else {
    const fine = new Date(i.data + 'T00:00:00'); fine.setDate(fine.getDate() + 1);
    e.allDay = true;
    e.startTime = i.data + 'T00:00:00';
    e.endTime = locale(fine);
  }
  if (i.tipo !== 'Telefonata') e.location = 'Concessionaria';
  e.description = ['Dall\'app Andamento vendite: messo in calendario da Agente 1.', i.telefono ? 'Telefono: ' + i.telefono : '', i.note ? 'Note: ' + i.note : ''].filter(Boolean).join('\n');
  return e;
}

// Ora locale di Roma di un evento di Google Calendar: "AAAA-MM-GGTHH:MM".
function inizioEvento(ev) {
  const s = ev && ev.start && (ev.start.dateTime || ev.start.date);
  if (!s) return '';
  if (!s.includes('T')) return s + 'T00:00';
  return locale(new Date(s)).slice(0, 16);
}

function piano([dirVendite, dirAgente, fileEventi, dirUscita]) {
  const ora = new Date();
  const fin = finestra(ora);
  const oggi = giorno(ora);
  const limite = fin.endTime.slice(0, 10);
  const mappa = leggiCartella(path.join(dirAgente, 'calendario'));
  let eventi = [];
  try {
    const r = JSON.parse(fs.readFileSync(fileEventi, 'utf8'));
    eventi = (Array.isArray(r) ? r : r.events || (r.payload && r.payload.events) || []).filter((e) => e && e.id && e.status !== 'cancelled');
  } catch (e) {
    console.error('Eventi di Google Calendar non leggibili: ' + e.message);
    process.exit(2);
  }
  const usati = new Set(Object.values(mappa).map((m) => m.eventId));
  const tutti = impegni(dirVendite);
  const azioni = [], adottati = [];
  let n = 0;

  for (const i of Object.values(tutti)) {
    if (i.data < oggi || i.data >= limite) continue;
    const e = evento(i);
    const m = mappa[i.chiave];
    const firma = firmaDi(e);
    if (m && m.eventId) {
      if (m.firma === firma) continue;
      azioni.push({ n: ++n, tipo: 'aggiorna', chiave: i.chiave, eventId: m.eventId, evento: e, firma,
        riga: 'l\'impegno ' + i.descr + ' è cambiato: ora è ' + quando(i.data, i.ora) + '. Ho aggiornato il tuo calendario.' });
      continue;
    }
    // Non ancora in mappa: se nel calendario c'è già un evento alla stessa ora con il suo nome, lo adotta invece di duplicarlo.
    if (i.data === oggi && i.ora && i.data + 'T' + i.ora < locale(ora).slice(0, 16)) continue;
    const parole = norm(i.con).split(/[^a-z0-9]+/).filter((p) => p.length >= 3);
    const gia = eventi.find((ev) => !usati.has(ev.id) && inizioEvento(ev) === (i.ora ? i.data + 'T' + i.ora : i.data + 'T00:00') &&
      parole.some((p) => norm(ev.summary).includes(p)));
    if (gia) {
      usati.add(gia.id);
      adottati.push({ chiave: i.chiave, eventId: gia.id });
      scrivi(path.join(dirUscita, 'calendario', i.chiave + '.json'), {
        eventId: gia.id, firma, titolo: e.summary, inizio: e.startTime, fine: e.endTime, adottato: true, aggiornato: ora.toISOString()
      });
      continue;
    }
    azioni.push({ n: ++n, tipo: 'crea', chiave: i.chiave, evento: e, firma,
      riga: 'c\'è ' + (i.tipo === 'Test drive' ? 'un test drive prenotato: ' + i.con + (i.auto ? ', ' + i.auto : '') : 'un nuovo impegno: ' + i.descr) + ', ' + quando(i.data, i.ora) + '. L\'ho messo nel tuo calendario.' });
  }

  // Impegni spariti o cancellati nell'app: l'evento futuro che aveva creato o adottato Agente 1 esce dal calendario.
  const togliSoloMappa = [];
  for (const [chiave, m] of Object.entries(mappa)) {
    const i = tutti[chiave];
    const futuro = String(m.inizio || '') >= locale(ora);
    if (i && i.data >= oggi) continue;
    if (!i && futuro && m.eventId) {
      azioni.push({ n: ++n, tipo: 'cancella', chiave, eventId: m.eventId, titolo: m.titolo || chiave,
        riga: (m.titolo ? '«' + m.titolo + '»' : 'un impegno') + ' è stato cancellato nell\'app: l\'ho tolto dal tuo calendario.' });
    } else if (!futuro) {
      // impegno passato: la mappa non serve più dopo 30 giorni
      if (String(m.inizio || '') < locale(new Date(ora.getTime() - 30 * 86400000))) togliSoloMappa.push(chiave);
    }
  }

  const out = { creato: ora.toISOString(), finestra: fin, azioni, adottati, togliSoloMappa };
  scrivi(path.join(dirUscita, 'calendario-piano.json'), out);
  console.log(JSON.stringify({ crea: azioni.filter((a) => a.tipo === 'crea').length, aggiorna: azioni.filter((a) => a.tipo === 'aggiorna').length,
    cancella: azioni.filter((a) => a.tipo === 'cancella').length, adottati: adottati.length, impegni: Object.keys(tutti).length }));
}

function registra([dirUscita, fileEsiti]) {
  const p = JSON.parse(fs.readFileSync(path.join(dirUscita, 'calendario-piano.json'), 'utf8'));
  let esiti = [];
  try { esiti = JSON.parse(fs.readFileSync(fileEsiti, 'utf8')); } catch (e) { esiti = []; }
  const perN = new Map(esiti.map((x) => [Number(x.n), x]));
  const ora = new Date().toISOString();
  const righe = [], togli = [...p.togliSoloMappa];
  let fatti = 0, falliti = 0;
  for (const a of p.azioni) {
    const x = perN.get(a.n);
    if (!x || !x.ok) {
      falliti++;
      righe.push('non sono riuscito a ' + (a.tipo === 'crea' ? 'mettere in calendario' : a.tipo === 'aggiorna' ? 'aggiornare in calendario' : 'togliere dal calendario') +
        ' «' + (a.evento ? a.evento.summary : a.titolo || a.chiave) + '»' + (x && x.errore ? ' (' + String(x.errore).slice(0, 120) + ')' : '') + ': riprovo al prossimo turno.');
      continue;
    }
    fatti++;
    righe.push(a.riga);
    if (a.tipo === 'cancella') { togli.push(a.chiave); continue; }
    scrivi(path.join(dirUscita, 'calendario', a.chiave + '.json'), {
      eventId: a.tipo === 'crea' ? String(x.eventId || '') : a.eventId, firma: a.firma, titolo: a.evento.summary,
      inizio: a.evento.startTime, fine: a.evento.endTime, aggiornato: ora
    });
  }
  scrivi(path.join(dirUscita, 'calendario-togli.json'), togli);
  const tot = p.azioni.length;
  scrivi(path.join(dirUscita, 'righe', 'vendite-calendario.json'), {
    reparto: 'vendite', addetto: 'calendario',
    riepilogo: tot ? fatti + (fatti === 1 ? ' modifica' : ' modifiche') + ' al calendario' + (falliti ? ', ' + falliti + ' da riprovare' : '') : 'calendario già allineato',
    righe
  });
  console.log(JSON.stringify({ fatti, falliti, togli: togli.length }));
}

const [cmd, ...args] = process.argv.slice(2);
if (cmd === 'piano' && args.length === 4) piano(args);
else if (cmd === 'registra' && args.length === 2) registra(args);
else if (cmd === 'finestra') console.log(JSON.stringify(finestra(new Date())));
else {
  console.error('Uso: node calendario.js piano <export-vendite> <export-agente> <eventi.json> <uscita> | registra <uscita> <esiti.json> | finestra');
  process.exit(1);
}
