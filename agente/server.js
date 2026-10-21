// Agente 1: server senza dipendenze esterne (richiede Node 18 o superiore).
// Il capo (Agente 1) riceve i messaggi dell'utente e delega agli specialisti definiti in agenti.json.
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const { execSync } = require('node:child_process');

const ROOT = __dirname;
const PUBBLICO = path.join(ROOT, 'public');
const DATI = path.join(ROOT, 'dati');
const MEMORIA = path.join(DATI, 'memoria.md');
const STORIA = path.join(DATI, 'miglioramenti.log');
const AGENTI_FILE = path.join(ROOT, 'agenti.json');

const PORTA = process.env.PORT || 3000;
const CHIAVE_API = process.env.ANTHROPIC_API_KEY;
const TOKEN_APP = process.env.AGENTE_TOKEN;
const MODELLO_CAPO = process.env.MODELLO_CAPO || 'claude-sonnet-5-5';
const MODELLO_AGENTI = process.env.MODELLO_AGENTI || 'claude-haiku-5-5';
const EMAIL_PROPRIETARIO = process.env.EMAIL_PROPRIETARIO;
const RESEND_KEY = process.env.RESEND_API_KEY;
const EMAIL_MITTENTE = process.env.EMAIL_MITTENTE || 'Agente 1 <onboarding@resend.dev>';
const BRAVE_KEY = process.env.BRAVE_API_KEY;
const CONTABILITA_URL = process.env.CONTABILITA_URL; // URL dello script Google della app di contabilità
const CONTABILITA_TOKEN = process.env.CONTABILITA_TOKEN;
const ENASARCO = Number(process.env.ENASARCO_PCT || 8.5);
const TASSE = Number(process.env.TASSE_PCT || 30);
const GIORNI_SCADENZA = Number(process.env.GIORNI_SCADENZA || 30);
const SOGLIA_BOLLO = 77.47;

const VERSIONE = gitVersione() || new Date().toISOString();
let notifiche = [];
let cacheFatture = { ora: 0, dati: null };

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.png': 'image/png',
  '.svg': 'image/svg+xml'
};

/* ---------- Utilità ---------- */

function gitVersione() {
  try {
    return execSync('git rev-parse --short HEAD', { cwd: ROOT, stdio: ['ignore', 'pipe', 'ignore'] }).toString().trim();
  } catch {
    return null;
  }
}

const leggiAgenti = () => JSON.parse(fs.readFileSync(AGENTI_FILE, 'utf8'));
const adesso = () => new Date().toLocaleString('it-IT', { dateStyle: 'full', timeStyle: 'short', timeZone: 'Europe/Rome' });
const arrotonda = (x) => Math.round(x * 100) / 100;
const giorniDa = (iso) => Math.floor((Date.now() - new Date(iso + 'T12:00:00').getTime()) / 86400000);

// Stessa lettura dei numeri usata nella app di contabilità (accetta 1.234,56 e 1234.56).
function leggiNumero(s) {
  if (typeof s === 'number') return s;
  const v = parseFloat(String(s || '').replace(/[^\d,.-]/g, '').replace(/\.(?=\d{3}(\D|$))/g, '').replace(',', '.'));
  return Number.isNaN(v) ? 0 : v;
}

function inviaJson(res, stato, corpo) {
  res.writeHead(stato, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' });
  res.end(JSON.stringify(corpo));
}

function leggiCorpo(req) {
  return new Promise((ok, ko) => {
    let dati = '';
    req.on('data', (c) => {
      dati += c;
      if (dati.length > 1e6) {
        req.destroy();
        ko(new Error('Richiesta troppo grande'));
      }
    });
    req.on('end', () => {
      try {
        ok(JSON.parse(dati || '{}'));
      } catch {
        ko(new Error('JSON non valido'));
      }
    });
  });
}

async function getJson(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`HTTP ${r.status} da ${new URL(url).host}`);
  return r.json();
}

/* ---------- Contabilità: stessi calcoli della app ---------- */

async function leggiFatture() {
  if (!CONTABILITA_URL) throw new Error('CONTABILITA_URL non impostata: collega lo script della app di contabilità');
  if (cacheFatture.dati && Date.now() - cacheFatture.ora < 60000) return cacheFatture.dati;
  const r = await fetch(CONTABILITA_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'text/plain;charset=utf-8' },
    body: JSON.stringify({ action: 'list', token: CONTABILITA_TOKEN })
  });
  const j = await r.json();
  if (!j.ok) throw new Error(j.error || 'Lo script della contabilità ha risposto con errore');
  cacheFatture = { ora: Date.now(), dati: j };
  return j;
}

function calcola(f) {
  const lordo = leggiNumero(f.lordo);
  const bollo = f.bollo !== undefined && f.bollo !== '' ? leggiNumero(f.bollo) : (lordo > SOGLIA_BOLLO ? 2 : 0);
  const enasarco = Math.round(lordo * ENASARCO) / 100;
  const netto = lordo - enasarco;
  const tasse = Math.round(netto * TASSE) / 100;
  return { enasarco, netto, tasse, bonifico: lordo + bollo - enasarco };
}

const scaduta = (f) => f.stato !== 'incassata' && !!f.data && giorniDa(f.data) > GIORNI_SCADENZA;

async function riepilogoFatture({ mese } = {}) {
  const { fatture = [], accantonamenti = {} } = await leggiFatture();
  const scope = mese ? fatture.filter((f) => String(f.data || '').startsWith(mese)) : fatture;
  const somma = (campo, lista) => arrotonda(lista.reduce((s, f) => s + calcola(f)[campo], 0));
  const perStato = {};
  for (const f of scope) perStato[f.stato || 'sconosciuto'] = (perStato[f.stato || 'sconosciuto'] || 0) + 1;
  return {
    periodo: mese || 'tutto',
    numero_fatture: scope.length,
    per_stato: perStato,
    da_incassare_bonifico: somma('bonifico', scope.filter((f) => f.stato !== 'incassata')),
    incassato_bonifico: somma('bonifico', scope.filter((f) => f.stato === 'incassata')),
    enasarco_totale: somma('enasarco', scope),
    tasse_da_accantonare: somma('tasse', scope),
    scadute: scope.filter(scaduta).map((f) => ({
      numero: f.numero,
      data: f.data,
      lordo: leggiNumero(f.lordo),
      giorni_di_ritardo: giorniDa(f.data) - GIORNI_SCADENZA
    })),
    accantonato_nel_mese: mese ? accantonamenti[mese] ?? 0 : null
  };
}

async function elencoFatture({ stato, limite = 20 } = {}) {
  const { fatture = [] } = await leggiFatture();
  return fatture
    .filter((f) => !stato || f.stato === stato)
    .sort((a, b) => String(b.data || '').localeCompare(String(a.data || '')))
    .slice(0, Math.min(Number(limite) || 20, 50))
    .map((f) => ({
      numero: f.numero,
      data: f.data,
      stato: f.stato,
      lordo: leggiNumero(f.lordo),
      descrizione: f.descrizione,
      scaduta: scaduta(f)
    }));
}

/* ---------- Vendite: legge dati/vendite.csv (colonne separate da ;) ---------- */

function riepilogoVendite({ mese } = {}) {
  const file = path.join(DATI, 'vendite.csv');
  if (!fs.existsSync(file)) {
    return { errore: 'Manca dati/vendite.csv. Esporta le vendite con colonne: data;prodotto;importo;canale' };
  }
  const [intestazioni, ...righe] = fs.readFileSync(file, 'utf8').trim().split(/\r?\n/).map((r) => r.split(';').map((c) => c.trim()));
  const iData = intestazioni.indexOf('data');
  const iImporto = intestazioni.indexOf('importo');
  const iCanale = intestazioni.indexOf('canale');
  if (iData < 0 || iImporto < 0) return { errore: 'Il file deve avere almeno le colonne data e importo', colonne: intestazioni };

  const perMese = {};
  const perCanale = {};
  let conteggio = 0;
  for (const r of righe) {
    if (!r[iData] || (mese && !r[iData].startsWith(mese))) continue;
    const importo = leggiNumero(r[iImporto]);
    const m = r[iData].slice(0, 7);
    const canale = (iCanale >= 0 && r[iCanale]) || 'non indicato';
    perMese[m] = arrotonda((perMese[m] || 0) + importo);
    perCanale[canale] = arrotonda((perCanale[canale] || 0) + importo);
    conteggio++;
  }
  return {
    periodo: mese || 'tutto',
    numero_vendite: conteggio,
    per_mese: Object.fromEntries(Object.entries(perMese).sort()),
    per_canale: perCanale
  };
}

/* ---------- Meteo e ricerca web ---------- */

async function meteo({ citta }) {
  const geo = await getJson(`https://geocoding-api.open-meteo.com/v1/search?name=${encodeURIComponent(citta)}&count=1&language=it`);
  const luogo = geo.results?.[0];
  if (!luogo) return { errore: `Città "${citta}" non trovata` };
  const f = await getJson(
    `https://api.open-meteo.com/v1/forecast?latitude=${luogo.latitude}&longitude=${luogo.longitude}` +
    '&current=temperature_2m,apparent_temperature,precipitation,wind_speed_10m,weather_code' +
    '&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max&timezone=auto&forecast_days=3'
  );
  return { luogo: `${luogo.name}, ${luogo.country}`, adesso: f.current, previsioni: f.daily, unita: f.current_units };
}

async function cercaWeb({ query }) {
  if (!BRAVE_KEY) return { errore: 'Ricerca web non configurata: manca BRAVE_API_KEY' };
  const r = await fetch(`https://api.search.brave.com/res/v1/web/search?q=${encodeURIComponent(query)}&count=5&search_lang=it`, {
    headers: { 'X-Subscription-Token': BRAVE_KEY, Accept: 'application/json' }
  });
  if (!r.ok) return { errore: `Ricerca web: HTTP ${r.status}` };
  const j = await r.json();
  return { risultati: (j.web?.results || []).map((x) => ({ titolo: x.title, url: x.url, descrizione: x.description })) };
}

/* ---------- Azioni del capo ---------- */

async function delega({ agente, compito }) {
  const specialista = leggiAgenti()[agente];
  if (!specialista || agente === 'capo') return { errore: `Specialista "${agente}" non disponibile` };
  const risposta = await esegui({
    modello: MODELLO_AGENTI,
    system: `${specialista.prompt}\n\nData e ora attuali: ${adesso()}.`,
    nomi: specialista.strumenti,
    handlers: Object.fromEntries(specialista.strumenti.map((n) => [n, STRUMENTI[n]])),
    messaggi: [{ role: 'user', content: compito }],
    maxGiri: 6
  });
  return { specialista: specialista.nome, risposta };
}

function notifica({ titolo, testo }) {
  notifiche.push({
    id: Date.now() + Math.random(),
    titolo: String(titolo).slice(0, 120),
    testo: String(testo).slice(0, 1000),
    ora: new Date().toISOString()
  });
  notifiche = notifiche.slice(-50);
  return { inviata: true };
}

// Invia solo al proprietario, indicato in EMAIL_PROPRIETARIO: l'agente non può scrivere ad altri.
async function inviaEmail({ oggetto, testo }) {
  if (!EMAIL_PROPRIETARIO) return { errore: 'EMAIL_PROPRIETARIO non impostata' };
  if (!RESEND_KEY) return { errore: 'Invio email non configurato: manca RESEND_API_KEY' };
  const r = await fetch('https://api.resend.com/emails', {
    method: 'POST',
    headers: { Authorization: `Bearer ${RESEND_KEY}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ from: EMAIL_MITTENTE, to: [EMAIL_PROPRIETARIO], subject: oggetto, text: testo })
  });
  if (!r.ok) return { errore: `Invio email fallito: HTTP ${r.status} ${await r.text()}` };
  return { inviata: true };
}

function ricorda({ fatto }) {
  fs.appendFileSync(MEMORIA, `- ${new Date().toISOString().slice(0, 10)}: ${String(fatto).slice(0, 500)}\n`);
  return { ricordato: true };
}

// Riscrive il prompt di uno specialista e registra il precedente nel log, così si può tornare indietro.
function miglioraAgente({ agente, nuovo_prompt, motivo }) {
  const agenti = leggiAgenti();
  if (agente === 'capo' || !agenti[agente]) return { errore: `Non posso migliorare "${agente}"` };
  const precedente = agenti[agente].prompt;
  agenti[agente].prompt = String(nuovo_prompt);
  fs.writeFileSync(AGENTI_FILE, JSON.stringify(agenti, null, 2) + '\n');
  fs.appendFileSync(STORIA, `\n## ${new Date().toISOString()} · ${agente}\nMotivo: ${motivo}\nPrompt precedente:\n${precedente}\n`);
  return { migliorato: agente };
}

/* ---------- Schemi degli strumenti e loop con Claude ---------- */

const SCHEMI = {
  riepilogo_fatture: {
    name: 'riepilogo_fatture',
    description: 'Calcola su tutte le fatture, o su un mese, bonifici da incassare, Enasarco, tasse da accantonare e fatture scadute. Usalo per ogni cifra di contabilità.',
    input_schema: { type: 'object', properties: { mese: { type: 'string', description: 'Mese AAAA-MM, opzionale' } } }
  },
  elenco_fatture: {
    name: 'elenco_fatture',
    description: 'Elenca le fatture più recenti, filtrabili per stato: inviata, fatturata o incassata.',
    input_schema: {
      type: 'object',
      properties: { stato: { type: 'string' }, limite: { type: 'integer', description: 'Massimo 50' } }
    }
  },
  riepilogo_vendite: {
    name: 'riepilogo_vendite',
    description: 'Totali delle vendite per mese e per canale, dal file dati/vendite.csv.',
    input_schema: { type: 'object', properties: { mese: { type: 'string', description: 'Mese AAAA-MM, opzionale' } } }
  },
  meteo: {
    name: 'meteo',
    description: 'Meteo attuale e previsioni a 3 giorni per una città.',
    input_schema: { type: 'object', properties: { citta: { type: 'string' } }, required: ['citta'] }
  },
  cerca_web: {
    name: 'cerca_web',
    description: 'Cerca informazioni aggiornate sul web. Restituisce titoli, link e descrizioni.',
    input_schema: { type: 'object', properties: { query: { type: 'string' } }, required: ['query'] }
  },
  delega: {
    name: 'delega',
    description: 'Affida un compito a uno specialista e ricevi la sua risposta.',
    input_schema: {
      type: 'object',
      properties: {
        agente: { type: 'string', enum: ['contabilita', 'vendite', 'meteo'] },
        compito: { type: 'string', description: 'Richiesta chiara e completa, con il periodo se serve' }
      },
      required: ['agente', 'compito']
    }
  },
  notifica: {
    name: 'notifica',
    description: "Invia una notifica all'utente nell'app. Usala per avvisi importanti.",
    input_schema: {
      type: 'object',
      properties: { titolo: { type: 'string' }, testo: { type: 'string' } },
      required: ['titolo', 'testo']
    }
  },
  invia_email: {
    name: 'invia_email',
    description: "Invia un'email al proprietario. Usala solo se l'utente lo chiede esplicitamente.",
    input_schema: {
      type: 'object',
      properties: { oggetto: { type: 'string' }, testo: { type: 'string' } },
      required: ['oggetto', 'testo']
    }
  },
  ricorda: {
    name: 'ricorda',
    description: 'Salva in memoria una preferenza o un fatto utile su cui tornare in futuro.',
    input_schema: { type: 'object', properties: { fatto: { type: 'string' } }, required: ['fatto'] }
  },
  migliora_agente: {
    name: 'migliora_agente',
    description: "Riscrive il prompt di uno specialista (contabilita, vendite, meteo) quando sbaglia o l'utente chiede un cambiamento. Spiega il motivo.",
    input_schema: {
      type: 'object',
      properties: {
        agente: { type: 'string', enum: ['contabilita', 'vendite', 'meteo'] },
        nuovo_prompt: { type: 'string' },
        motivo: { type: 'string' }
      },
      required: ['agente', 'nuovo_prompt', 'motivo']
    }
  }
};

const STRUMENTI = {
  riepilogo_fatture: riepilogoFatture,
  elenco_fatture: elencoFatture,
  riepilogo_vendite: riepilogoVendite,
  meteo,
  cerca_web: cercaWeb
};

const STRUMENTI_CAPO = ['delega', 'notifica', 'invia_email', 'ricorda', 'migliora_agente'];
const HANDLER_CAPO = { delega, notifica, invia_email: inviaEmail, ricorda, migliora_agente: miglioraAgente };

async function chiamaClaude({ model, system, tools, messages }) {
  if (!CHIAVE_API) throw new Error('ANTHROPIC_API_KEY non impostata sul server');
  const r = await fetch('https://api.anthropic.com/v1/messages', {
    method: 'POST',
    headers: { 'x-api-key': CHIAVE_API, 'anthropic-version': '2023-06-01', 'content-type': 'application/json' },
    body: JSON.stringify({ model, max_tokens: 2048, system, tools, messages })
  });
  const j = await r.json();
  if (!r.ok) throw new Error(`API Claude ${r.status}: ${j.error?.message || ''}`);
  return j;
}

// Ciclo agentico: il modello chiama strumenti finché non risponde con testo.
async function esegui({ modello, system, nomi, handlers, messaggi, maxGiri }) {
  const conversazione = [...messaggi];
  for (let giro = 0; giro < maxGiri; giro++) {
    const r = await chiamaClaude({
      model: modello,
      system,
      tools: nomi.map((n) => SCHEMI[n]),
      messages: conversazione
    });
    conversazione.push({ role: 'assistant', content: r.content });
    const richieste = r.content.filter((b) => b.type === 'tool_use');
    if (r.stop_reason !== 'tool_use' || richieste.length === 0) {
      return r.content.filter((b) => b.type === 'text').map((b) => b.text).join('\n').trim();
    }
    const esiti = [];
    for (const richiesta of richieste) {
      let esito;
      try {
        esito = await handlers[richiesta.name](richiesta.input);
      } catch (e) {
        esito = { errore: e.message };
      }
      esiti.push({ type: 'tool_result', tool_use_id: richiesta.id, content: JSON.stringify(esito).slice(0, 20000) });
    }
    conversazione.push({ role: 'user', content: esiti });
  }
  return 'Non sono riuscito a concludere entro il limite di passaggi.';
}

async function chat(messaggi) {
  const capo = leggiAgenti().capo;
  const memoria = fs.existsSync(MEMORIA) ? fs.readFileSync(MEMORIA, 'utf8').slice(-4000) : '';
  return esegui({
    modello: MODELLO_CAPO,
    system: `${capo.prompt}\n\nData e ora attuali: ${adesso()}.\n\nCose da ricordare sull'utente:\n${memoria || '(nessuna ancora)'}`,
    nomi: STRUMENTI_CAPO,
    handlers: HANDLER_CAPO,
    messaggi,
    maxGiri: 10
  });
}

/* ---------- Server HTTP ---------- */

async function gestisciApi(req, res, url) {
  if (req.method === 'GET' && url.pathname === '/api/versione') return inviaJson(res, 200, { versione: VERSIONE });
  if (TOKEN_APP && req.headers.authorization !== `Bearer ${TOKEN_APP}`) return inviaJson(res, 401, { errore: 'Accesso richiesto' });

  if (req.method === 'GET' && url.pathname === '/api/notifiche') return inviaJson(res, 200, { notifiche });

  if (req.method === 'POST' && url.pathname === '/api/chat') {
    const { messaggi } = await leggiCorpo(req);
    const pulita = (Array.isArray(messaggi) ? messaggi : [])
      .filter((m) => (m.role === 'user' || m.role === 'assistant') && typeof m.content === 'string' && m.content.trim())
      .slice(-20);
    while (pulita[0]?.role === 'assistant') pulita.shift();
    if (!pulita.length || pulita[pulita.length - 1].role !== 'user') return inviaJson(res, 400, { errore: 'Messaggio mancante' });
    return inviaJson(res, 200, { risposta: await chat(pulita) });
  }

  inviaJson(res, 404, { errore: 'Non trovato' });
}

function servi(res, pathname) {
  const relativo = pathname === '/' ? 'index.html' : pathname.slice(1);
  const file = path.normalize(path.join(PUBBLICO, relativo));
  if (!file.startsWith(PUBBLICO + path.sep) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) {
    res.writeHead(404);
    return res.end('Non trovato');
  }
  res.writeHead(200, { 'Content-Type': MIME[path.extname(file)] || 'application/octet-stream', 'Cache-Control': 'no-cache' });
  fs.createReadStream(file).pipe(res);
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://localhost');
  try {
    if (url.pathname.startsWith('/api/')) return await gestisciApi(req, res, url);
    return servi(res, url.pathname);
  } catch (e) {
    inviaJson(res, 500, { errore: e.message });
  }
});

if (require.main === module) {
  fs.mkdirSync(DATI, { recursive: true });
  if (!CHIAVE_API) console.warn('Attenzione: ANTHROPIC_API_KEY non impostata, la chat non risponderà.');
  server.listen(PORTA, () => console.log(`Agente 1 in ascolto su http://localhost:${PORTA} (versione ${VERSIONE})`));
}

module.exports = { STRUMENTI, SCHEMI };
