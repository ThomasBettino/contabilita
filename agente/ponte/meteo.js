#!/usr/bin/env node
// Reparto meteo di Agente 1: previsioni incrociate di più modelli meteo indipendenti.
// Interroga 5 modelli tramite Open-Meteo (ECMWF, ICON, GFS, Météo-France, ItaliaMeteo ICON-2I),
// MET Norway (yr.no), DWD MOSMIX (Bright Sky) e WorldWeatherOnline (wttr.in); 7Timer (GFS) sostituisce
// il GFS di Open-Meteo quando manca. Per ogni giorno prende la mediana dei numeri, il cielo più votato
// e misura quanto le fonti concordano.
//
// Uso: NODE_USE_ENV_PROXY=1 node meteo.js <uscita> [<export-ordini>]
//   <uscita>         scrive sync/meteo.json (solo per Bergamo, la città di casa) e, per ogni ordine meteo,
//                    ordini-meteo/<id>.json con esito e previsioni del suo luogo
//   <export-ordini>  cartella con ordini/<id>.json presi in carico. Ogni luogo viene verificato una volta,
//                    con il numero di giorni più alto chiesto per quel luogo. Senza ordini: Bergamo, 3 giorni.
// Uscita: 0 se almeno una verifica ha avuto dati, 3 se nessuna fonte ha risposto (sync/meteo.json non viene scritto).
// Per le prove: METEO_OPEN_METEO, METEO_GEOCODING, METEO_MET_NO, METEO_BRIGHTSKY, METEO_WTTR e METEO_7TIMER
// sostituiscono gli indirizzi dei servizi.
process.env.TZ = 'Europe/Rome';

const fs = require('node:fs');
const path = require('node:path');

const [dirUscita, dirOrdini] = process.argv.slice(2);
if (!dirUscita) {
  console.error('Uso: node meteo.js <uscita> [<export-ordini>]');
  process.exit(2);
}

const OPEN_METEO = process.env.METEO_OPEN_METEO || 'https://api.open-meteo.com';
const GEOCODING = process.env.METEO_GEOCODING || 'https://geocoding-api.open-meteo.com';
const MET_NO = process.env.METEO_MET_NO || 'https://api.met.no';
const BRIGHTSKY = process.env.METEO_BRIGHTSKY || 'https://api.brightsky.dev';
const WTTR = process.env.METEO_WTTR || 'https://wttr.in';
const SETTE_TIMER = process.env.METEO_7TIMER || 'https://www.7timer.info';
// MET Norway chiede un User-Agent che identifichi l'app.
const USER_AGENT = 'Agente1/1.0 github.com/ThomasBettino/contabilita';

const FONTI = [
  { id: 'ecmwf', nome: 'ECMWF (centro meteo europeo)', breve: 'ECMWF', modello: 'ecmwf_ifs025' },
  { id: 'icon', nome: 'ICON (servizio meteo tedesco DWD)', breve: 'ICON', modello: 'icon_seamless' },
  { id: 'gfs', nome: 'GFS (NOAA, Stati Uniti)', breve: 'GFS', modello: 'gfs_seamless' },
  { id: 'meteofrance', nome: 'Météo-France', breve: 'MÉTÉO-FR', modello: 'meteofrance_seamless' },
  { id: 'italiameteo', nome: 'ItaliaMeteo ICON-2I', breve: 'ITALIA', modello: 'italia_meteo_arpae_icon_2i' },
  { id: 'metno', nome: 'MET Norway (yr.no)', breve: 'YR.NO', tipo: 'metno' },
  { id: 'mosmix', nome: 'DWD MOSMIX (Bright Sky)', breve: 'MOSMIX', tipo: 'brightsky' },
  { id: 'wwo', nome: 'WorldWeatherOnline (wttr.in)', breve: 'WWO', tipo: 'wttr' },
  // Stesso modello del GFS di Open-Meteo: conta solo quando quello manca, mai tutti e due.
  { id: 'gfs7', nome: 'GFS via 7Timer', breve: 'GFS·7T', tipo: 'settetimer', riserva: 'gfs' }
];
const MINIMO_INCROCI = 3;
const MASSIMO_LUOGHI = 4;
const CASA = { nome: 'Bergamo', lat: 45.6983, lon: 9.6773, tz: 'Europe/Rome' };

// Cielo: dal più tranquillo al più severo. A parità di voti vince il più severo.
const CIELI = ['sereno', 'poco_nuvoloso', 'nuvoloso', 'coperto', 'nebbia', 'pioggia_debole', 'pioggia', 'neve', 'temporale'];
const NOME_CIELO = {
  sereno: 'sereno', poco_nuvoloso: 'poco nuvoloso', nuvoloso: 'nuvoloso', coperto: 'coperto', nebbia: 'nebbia',
  pioggia_debole: 'pioggia debole', pioggia: 'pioggia', neve: 'neve', temporale: 'temporali'
};
const BAGNATO = new Set(['pioggia_debole', 'pioggia', 'neve', 'temporale']);
const FASCE = [['mattina', 6, 12], ['pomeriggio', 12, 18], ['sera', 18, 24]];
const GIORNI_SETTIMANA = ['domenica', 'lunedì', 'martedì', 'mercoledì', 'giovedì', 'venerdì', 'sabato'];

function scrivi(file, dati) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify(dati, null, 2) + '\n');
}
const num = (x) => (typeof x === 'number' && Number.isFinite(x) ? x : null);
// Giorno (AAAA-MM-GG) e ora sull'orologio del luogo: così anche i giorni del cambio d'ora tornano giusti.
const giornoLocale = (d, tz) => new Intl.DateTimeFormat('en-CA', { timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit' }).format(d);
const oraLocale = (d, tz) => Number(new Intl.DateTimeFormat('en-GB', { timeZone: tz, hour: '2-digit', hourCycle: 'h23' }).format(d));
function piuGiorni(giorno, n) {
  const d = new Date(giorno + 'T12:00:00Z');
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}
function mediana(v) {
  const a = v.filter((x) => x !== null && x !== undefined).sort((x, y) => x - y);
  if (!a.length) return null;
  const m = Math.floor(a.length / 2);
  return a.length % 2 ? a[m] : (a[m - 1] + a[m]) / 2;
}
const fonti = (n) => n + (n === 1 ? ' fonte' : ' fonti');
const arrotonda = (x, cifre = 0) => (x === null ? null : Math.round(x * 10 ** cifre) / 10 ** cifre);

/* ---------- Luoghi e giorni dagli ordini ---------- */

function leggiOrdiniMeteo() {
  const dir = dirOrdini ? path.join(dirOrdini, 'ordini') : null;
  if (!dir || !fs.existsSync(dir)) return [];
  return fs.readdirSync(dir).filter((f) => f.endsWith('.json'))
    .map((f) => ({ id: f.slice(0, -5), ...JSON.parse(fs.readFileSync(path.join(dir, f), 'utf8')) }))
    .filter((o) => o.agente === 'meteo')
    .sort((a, b) => String(a.creato).localeCompare(String(b.creato)));
}
// Il luogo arriva da un modello linguistico: niente provincia o paese tra parentesi o dopo la virgola
// (il servizio cerca solo per nome), e solo lettere, spazi, apostrofi, trattini e punti.
function pulisciLuogo(x) {
  const s = String(x || '').split(/[,(/]/)[0].normalize('NFC').replace(/[^\p{L}\p{M} '’.-]/gu, ' ').replace(/\s+/g, ' ').trim().slice(0, 60);
  return s || CASA.nome;
}
const chiaveLuogo = (s) => pulisciLuogo(s).toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/[^a-z]/g, '');
function pulisciGiorni(x) {
  const n = Math.round(Number(x));
  return Number.isFinite(n) ? Math.min(5, Math.max(1, n)) : 3;
}

/* ---------- Rete ---------- */

const pausa = (ms) => new Promise((r) => setTimeout(r, ms));
// Il cloud esce su indirizzi condivisi: Open-Meteo a volte risponde 429 (limite giornaliero di quell'indirizzo)
// o non risponde affatto. Un nuovo tentativo di solito passa da un altro indirizzo.
async function prendiJson(url, tentativi = 3) {
  let ultimo;
  for (let i = 0; i < tentativi; i++) {
    if (i) await pausa(1500 * i);
    let r;
    try {
      r = await fetch(url, { headers: { 'user-agent': USER_AGENT, accept: 'application/json' }, signal: AbortSignal.timeout(15000) });
    } catch (e) {
      // Dietro il proxy dell'ambiente cloud un dominio non consentito arriva come errore di rete.
      ultimo = new Error(e && e.name === 'TimeoutError' ? 'nessuna risposta in 15 secondi' : 'rete bloccata o servizio giù');
      continue;
    }
    const testo = await r.text().catch(() => '');
    let j = null;
    try { j = JSON.parse(testo); } catch (e) { /* risposta non JSON */ }
    if (r.ok && j) return j;
    ultimo = new Error(r.ok ? 'risposta non JSON' : 'HTTP ' + r.status + (j && j.reason ? ': ' + String(j.reason).slice(0, 160) : ''));
    if (r.status >= 400 && r.status < 500 && r.status !== 429 && r.status !== 408) break; // richiesta sbagliata: inutile riprovare
  }
  throw ultimo;
}

async function cercaNome(nome) {
  const j = await prendiJson(GEOCODING + '/v1/search?count=1&language=it&format=json&name=' + encodeURIComponent(nome));
  const r = j && Array.isArray(j.results) ? j.results[0] : null;
  return r && num(r.latitude) !== null && num(r.longitude) !== null ? r : null;
}
async function trovaLuogo(nome) {
  if (chiaveLuogo(nome) === chiaveLuogo(CASA.nome)) return CASA;
  // Se il nome completo non c'è, riprova senza l'ultima parola ("Riva del Garda TN" → "Riva del Garda").
  let r = await cercaNome(nome);
  if (!r && nome.includes(' ')) r = await cercaNome(nome.replace(/\s+\S+$/, ''));
  if (!r) return null;
  let tz = 'Europe/Rome';
  try { if (r.timezone) { giornoLocale(new Date(), r.timezone); tz = r.timezone; } } catch (e) { /* fuso sconosciuto: resta quello di Roma */ }
  const etichetta = [r.name, r.country_code && r.country_code !== 'IT' ? r.country : null].filter(Boolean).join(', ');
  return { nome: String(etichetta || nome).replace(/[\u0000-\u001f]/g, '').slice(0, 60), lat: r.latitude, lon: r.longitude, tz };
}

/* ---------- Ore di ogni fonte: {giorno, ora, t, mm, prob, cielo, nubi, vento} ---------- */

// Codici WMO di Open-Meteo.
function cieloDaWmo(c, nubi) {
  if (c === null) return null;
  if (c >= 95) return 'temporale';
  if ((c >= 71 && c <= 77) || c === 85 || c === 86) return 'neve';
  if (c === 63 || c === 65 || c === 66 || c === 67 || c === 81 || c === 82) return 'pioggia';
  if ((c >= 51 && c <= 57) || c === 61 || c === 80) return 'pioggia_debole';
  if (c === 45 || c === 48) return 'nebbia';
  return cieloDaNubi(nubi, c);
}
function cieloDaNubi(nubi, wmo) {
  if (nubi !== null && nubi !== undefined) return nubi < 20 ? 'sereno' : nubi < 50 ? 'poco_nuvoloso' : nubi < 80 ? 'nuvoloso' : 'coperto';
  return ['sereno', 'poco_nuvoloso', 'nuvoloso', 'coperto'][Math.min(3, Math.max(0, wmo || 0))];
}
// Simboli di MET Norway (clearsky_day, lightrainshowers_night, heavyrainandthunder, ...).
function cieloDaSimbolo(s) {
  if (!s) return null;
  s = String(s).replace(/_(day|night|polartwilight)$/, '');
  if (/thunder/.test(s)) return 'temporale';
  if (/snow|sleet/.test(s)) return 'neve';
  if (/rain/.test(s)) return /^light/.test(s) ? 'pioggia_debole' : 'pioggia';
  if (s === 'fog') return 'nebbia';
  if (s === 'clearsky') return 'sereno';
  if (s === 'fair') return 'poco_nuvoloso';
  if (s === 'partlycloudy') return 'nuvoloso';
  if (s === 'cloudy') return 'coperto';
  return null;
}

// Orari in secondi Unix: Open-Meteo usa un solo scarto orario per tutta la serie, che sbaglia di un'ora
// dopo il cambio dell'ora legale. Giorno e ora li calcola questo script, sull'orologio del luogo.
const urlOpenMeteo = (modelli, luogo, giorni) => OPEN_METEO + '/v1/forecast?latitude=' + luogo.lat + '&longitude=' + luogo.lon +
  '&hourly=temperature_2m,precipitation,precipitation_probability,weather_code,cloud_cover,wind_speed_10m&models=' + modelli.join(',') +
  '&timezone=' + encodeURIComponent(luogo.tz) + '&timeformat=unixtime&forecast_days=' + giorni + '&wind_speed_unit=kmh';

// Prima una richiesta sola con tutti i modelli (più rapida e meno esposta ai limiti); se non passa, un modello alla volta.
async function tuttiOpenMeteo(luogo, giorni) {
  const fonti = FONTI.filter((f) => f.modello);
  const esito = {};
  try {
    const j = await prendiJson(urlOpenMeteo(fonti.map((f) => f.modello), luogo, giorni));
    for (const f of fonti) {
      try { esito[f.id] = { ore: oreOpenMeteo(f, j, luogo.tz) }; } catch (e) { esito[f.id] = { errore: e.message }; }
    }
    return esito;
  } catch (e) {
    console.error('Richiesta unica a Open-Meteo non riuscita (' + e.message + '): provo un modello alla volta.');
  }
  await Promise.all(fonti.map(async (f) => {
    try { esito[f.id] = { ore: oreOpenMeteo(f, await prendiJson(urlOpenMeteo([f.modello], luogo, giorni), 2), luogo.tz) }; } catch (e) { esito[f.id] = { errore: e.message }; }
  }));
  return esito;
}

function oreOpenMeteo(fonte, j, tz) {
  const h = j && j.hourly;
  if (!h || !Array.isArray(h.time)) throw new Error('risposta senza dati orari');
  // Con un solo modello i nomi sono semplici; con più modelli hanno il suffisso del modello.
  const col = (v) => (Array.isArray(h[v + '_' + fonte.modello]) ? h[v + '_' + fonte.modello] : Array.isArray(h[v]) ? h[v] : []);
  const T = col('temperature_2m'), P = col('precipitation'), PP = col('precipitation_probability'), C = col('weather_code'), N = col('cloud_cover'), V = col('wind_speed_10m');
  const ore = [];
  h.time.forEach((t, i) => {
    const d = typeof t === 'number' ? new Date(t * 1000) : null;
    if (!d || isNaN(d)) return;
    const temp = num(T[i]);
    if (temp === null) return; // ore oltre l'orizzonte del modello
    const nubi = num(N[i]);
    ore.push({ giorno: giornoLocale(d, tz), ora: oraLocale(d, tz), t: temp, mm: num(P[i]), prob: num(PP[i]), cielo: cieloDaWmo(num(C[i]), nubi), nubi, vento: num(V[i]) });
  });
  if (!ore.length) throw new Error('nessun dato per questo luogo');
  return ore;
}

async function oreMetNo(luogo) {
  const u = MET_NO + '/weatherapi/locationforecast/2.0/compact?lat=' + luogo.lat.toFixed(4) + '&lon=' + luogo.lon.toFixed(4);
  const j = await prendiJson(u);
  const serie = j && j.properties && j.properties.timeseries;
  if (!Array.isArray(serie)) throw new Error('risposta senza previsioni');
  const ore = [];
  for (const s of serie) {
    const d = new Date(s.time);
    if (isNaN(d) || !s.data) continue;
    const ist = (s.data.instant && s.data.instant.details) || {};
    const temp = num(ist.air_temperature);
    if (temp === null) continue;
    const n1 = s.data.next_1_hours, n6 = s.data.next_6_hours;
    // Dove la serie diventa ogni 6 ore, la pioggia di 6 ore conta una volta sola.
    const prossimo = n1 || n6;
    const simbolo = prossimo && prossimo.summary ? prossimo.summary.symbol_code : null;
    const nubi = num(ist.cloud_area_fraction);
    ore.push({
      giorno: giornoLocale(d, luogo.tz), ora: oraLocale(d, luogo.tz), t: temp,
      mm: prossimo && prossimo.details ? num(prossimo.details.precipitation_amount) : null,
      prob: prossimo && prossimo.details ? num(prossimo.details.probability_of_precipitation) : null,
      cielo: cieloDaSimbolo(simbolo) || (nubi !== null ? cieloDaNubi(nubi) : null), nubi,
      vento: num(ist.wind_speed) === null ? null : ist.wind_speed * 3.6
    });
  }
  return ore;
}

// DWD MOSMIX tramite Bright Sky: previsioni orarie della stazione più vicina (entro 50 km).
// Le ore passate di oggi arrivano come osservazioni di altre stazioni: si tengono solo le previsioni.
async function oreBrightSky(luogo, giorni) {
  const oggi = giornoLocale(new Date(), luogo.tz);
  const j = await prendiJson(BRIGHTSKY + '/weather?lat=' + luogo.lat.toFixed(4) + '&lon=' + luogo.lon.toFixed(4) +
    '&date=' + oggi + '&last_date=' + piuGiorni(oggi, giorni) + '&tz=' + encodeURIComponent(luogo.tz));
  const previsioni = new Set((j && Array.isArray(j.sources) ? j.sources : []).filter((x) => x.observation_type === 'forecast').map((x) => x.id));
  const ore = [];
  for (const w of (j && Array.isArray(j.weather) ? j.weather : [])) {
    if (!previsioni.has(w.source_id)) continue;
    const d = new Date(w.timestamp);
    const temp = num(w.temperature);
    if (isNaN(d) || temp === null) continue;
    const mm = num(w.precipitation), nubi = num(w.cloud_cover);
    const cond = w.condition;
    const cielo = cond === 'thunderstorm' || cond === 'hail' ? 'temporale' : cond === 'snow' || cond === 'sleet' ? 'neve'
      : cond === 'rain' ? (mm !== null && mm >= 1 ? 'pioggia' : 'pioggia_debole') : cond === 'fog' ? 'nebbia'
      : nubi !== null ? cieloDaNubi(nubi) : null;
    ore.push({ giorno: giornoLocale(d, luogo.tz), ora: oraLocale(d, luogo.tz), t: temp, mm, prob: num(w.precipitation_probability), cielo, nubi, vento: num(w.wind_speed) });
  }
  if (!ore.length) throw new Error('nessuna previsione per questo luogo');
  return ore;
}

// Codici di WorldWeatherOnline usati da wttr.in.
const WWO_TEMPORALE = new Set([200, 386, 389, 392, 395]);
const WWO_NEVE = new Set([179, 182, 185, 227, 230, 281, 284, 311, 314, 317, 320, 323, 326, 329, 332, 335, 338, 350, 362, 365, 368, 371, 374, 377]);
const WWO_PIOGGIA = new Set([299, 302, 305, 308, 356, 359]);
const WWO_DEBOLE = new Set([176, 263, 266, 293, 296, 353]);
const WWO_NEBBIA = new Set([143, 248, 260]);
// wttr.in: tre giorni, ogni tre ore, già nell'ora locale del luogo; ogni valore è una stringa.
async function oreWttr(luogo) {
  const j = await prendiJson(WTTR + '/' + luogo.lat.toFixed(4) + ',' + luogo.lon.toFixed(4) + '?format=j1');
  const ore = [];
  for (const g of (j && Array.isArray(j.weather) ? j.weather : [])) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(String(g.date))) continue;
    for (const h of (Array.isArray(g.hourly) ? g.hourly : [])) {
      const temp = num(Number(h.tempC)), ora = Math.floor(Number(h.time) / 100);
      if (temp === null || !(ora >= 0 && ora <= 23)) continue;
      const c = Number(h.weatherCode), nubi = num(Number(h.cloudcover)), mm = num(Number(h.precipMM));
      const cielo = WWO_TEMPORALE.has(c) ? 'temporale' : WWO_NEVE.has(c) ? 'neve' : WWO_PIOGGIA.has(c) ? 'pioggia'
        : WWO_DEBOLE.has(c) ? 'pioggia_debole' : WWO_NEBBIA.has(c) ? 'nebbia' : nubi !== null ? cieloDaNubi(nubi) : null;
      ore.push({ giorno: g.date, ora, t: temp, mm, prob: num(Number(h.chanceofrain)), cielo, nubi, vento: num(Number(h.windspeedKmph)) });
    }
  }
  if (!ore.length) throw new Error('risposta senza previsioni');
  return ore;
}

// 7Timer (prodotto CIVIL, modello GFS): ogni tre ore da 'init' (UTC). Nuvole, pioggia e vento sono classi:
// qui diventano il valore centrale della classe.
const NUBI_7T = [null, 3, 12, 25, 37, 50, 62, 75, 87, 97];
const MM_ORA_7T = [0, 0.1, 0.6, 2.5, 7, 13, 23, 40, 62, 80];
const VENTO_7T = [null, 1, 7, 20, 34, 50, 75, 103, 120];
async function ore7Timer(luogo) {
  const j = await prendiJson(SETTE_TIMER + '/bin/civil.php?lon=' + luogo.lon.toFixed(3) + '&lat=' + luogo.lat.toFixed(3) + '&ac=0&unit=metric&output=json&tzshift=0');
  const m = /^(\d{4})(\d{2})(\d{2})(\d{2})$/.exec(String(j && j.init));
  if (!m || !Array.isArray(j.dataseries)) throw new Error('risposta senza previsioni');
  const zero = Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4]);
  const ore = [];
  for (const x of j.dataseries) {
    const temp = num(x.temp2m), tp = num(x.timepoint);
    if (temp === null || tp === null) continue;
    const d = new Date(zero + tp * 3600000);
    const w = String(x.weather || '').replace(/(day|night)$/, '');
    const nubi = NUBI_7T[x.cloudcover] === undefined ? null : NUBI_7T[x.cloudcover];
    const mm = (MM_ORA_7T[x.prec_amount] || 0) * 3;
    const cielo = /^ts/.test(w) ? 'temporale' : /snow/.test(w) || x.prec_type === 'snow' || x.prec_type === 'icep' ? 'neve'
      : w === 'rain' ? 'pioggia' : /rain|shower/.test(w) ? 'pioggia_debole' : w === 'humid' ? 'nebbia'
      : w === 'clear' ? 'sereno' : w === 'pcloudy' ? 'poco_nuvoloso' : w === 'mcloudy' ? 'nuvoloso' : w === 'cloudy' ? 'coperto' : cieloDaNubi(nubi);
    ore.push({ giorno: giornoLocale(d, luogo.tz), ora: oraLocale(d, luogo.tz), t: temp, mm, prob: null, cielo, nubi,
      vento: x.wind10m && VENTO_7T[x.wind10m.speed] !== undefined ? VENTO_7T[x.wind10m.speed] : null });
  }
  if (!ore.length) throw new Error('risposta senza previsioni');
  return ore;
}

/* ---------- Riassunto di un intervallo di ore ---------- */

function cieloPrevalente(ore, sogliaPioggia, sogliaDebole) {
  const conta = (c) => ore.filter((o) => o.cielo === c).length;
  const mm = ore.reduce((s, o) => s + (o.mm || 0), 0);
  // Un'ora sola di temporale senza pioggia vera è rumore del modello.
  if (conta('temporale') >= 2 || (conta('temporale') >= 1 && mm >= sogliaDebole)) return 'temporale';
  if (conta('neve') >= 2) return 'neve';
  if (mm >= sogliaPioggia) return 'pioggia';
  if (mm >= sogliaDebole || conta('pioggia') + conta('pioggia_debole') >= Math.max(2, Math.ceil(ore.length / 3))) return 'pioggia_debole';
  if (conta('nebbia') >= Math.max(2, Math.ceil(ore.length / 3))) return 'nebbia';
  const nubi = ore.map((o) => o.nubi).filter((x) => x !== null);
  if (nubi.length) return cieloDaNubi(nubi.reduce((s, x) => s + x, 0) / nubi.length);
  const asciutti = ['sereno', 'poco_nuvoloso', 'nuvoloso', 'coperto'].map((c) => [c, conta(c)]).sort((a, b) => b[1] - a[1]);
  return asciutti[0][1] ? asciutti[0][0] : null;
}

// daOra: per oggi l'ora attuale. Minime e massime restano dell'intera giornata; cielo, pioggia e vento
// guardano solo le ore che restano, altrimenti la pioggia della notte passata pesa sulla giornata.
function riassumiGiorno(tutte, daOra) {
  if (tutte.length < 4) return null;
  const prima = Math.min(...tutte.map((o) => o.ora));
  const ultima = Math.max(...tutte.map((o) => o.ora));
  // Un modello che finisce a metà giornata (fine del suo orizzonte) non dice niente di affidabile su quel giorno.
  if (!daOra && ultima < 18) return null;
  const temp = tutte.map((o) => o.t);
  const restano = tutte.filter((o) => o.ora >= daOra);
  const ore = restano.length >= 3 ? restano : tutte.slice(-3);
  const diurne = ore.filter((o) => o.ora >= 7 && o.ora <= 20);
  const probs = ore.map((o) => o.prob).filter((x) => x !== null);
  const venti = ore.map((o) => o.vento).filter((x) => x !== null);
  const fasce = {};
  for (const [nome, da, a] of FASCE) {
    const f = tutte.filter((o) => o.ora >= da && o.ora < a);
    if (!f.length) continue;
    const pf = f.map((o) => o.prob).filter((x) => x !== null);
    fasce[nome] = {
      t: arrotonda(f.reduce((s, o) => s + o.t, 0) / f.length),
      cielo: cieloPrevalente(f, 2, 0.3),
      pioggia: pf.length ? Math.max(...pf) : null,
      mm: arrotonda(f.reduce((s, o) => s + (o.mm || 0), 0), 1)
    };
  }
  return {
    // Una fonte che parte da adesso (yr.no) non vede la notte né, di sera, il caldo del giorno:
    // quei valori non entrano nell'incrocio.
    min: prima <= 3 && ultima >= 20 ? arrotonda(Math.min(...temp)) : null,
    max: prima <= 13 && ultima >= 16 ? arrotonda(Math.max(...temp)) : null,
    cielo: cieloPrevalente(diurne.length >= 3 ? diurne : ore, 4, 0.5),
    pioggia: probs.length ? Math.max(...probs) : null,
    mm: arrotonda(ore.reduce((s, o) => s + (o.mm || 0), 0), 1),
    vento: venti.length ? arrotonda(Math.max(...venti)) : null,
    fasce
  };
}

/* ---------- Incrocio delle fonti ---------- */

// Prima si decide tra pioggia e asciutto a maggioranza di fonti (parità: pioggia), poi il tipo di cielo
// più votato dentro il gruppo vincente, così quattro fonti asciutte con nuvolosità diverse non perdono
// contro due che dicono pioggia debole.
function votaCielo(cieli) {
  const validi = cieli.filter(Boolean);
  if (!validi.length) return null;
  const bagnati = validi.filter((c) => BAGNATO.has(c));
  const gruppo = bagnati.length * 2 >= validi.length ? bagnati : validi.filter((c) => !BAGNATO.has(c));
  const voti = {};
  for (const c of gruppo) voti[c] = (voti[c] || 0) + 1;
  return Object.entries(voti).sort((a, b) => b[1] - a[1] || CIELI.indexOf(b[0]) - CIELI.indexOf(a[0]))[0][0];
}

function incrocia(giorno, perFonte) {
  const v = perFonte.filter((x) => x.dati);
  const n = v.length;
  const mins = v.map((x) => x.dati.min).filter((x) => x !== null), maxs = v.map((x) => x.dati.max).filter((x) => x !== null);
  const bagnate = v.filter((x) => BAGNATO.has(x.dati.cielo));
  const asciutte = v.filter((x) => x.dati.cielo && !BAGNATO.has(x.dati.cielo));
  // Con 5 fonti o più il valore più alto e il più basso non contano: una fonte fuori dal coro
  // non deve far sembrare discorde una previsione su cui le altre concordano.
  const centrali = (a) => (a.length >= 5 ? a.slice().sort((x, y) => x - y).slice(1, -1) : a);
  const cMax = centrali(maxs), cMin = centrali(mins);
  const scartoMax = cMax.length ? Math.max(...cMax) - Math.min(...cMax) : 0;
  const scartoMin = cMin.length ? Math.max(...cMin) - Math.min(...cMin) : 0;
  const minoranza = Math.min(bagnate.length, asciutte.length) / Math.max(1, bagnate.length + asciutte.length);
  let accordo;
  if (n < 2) accordo = 'una fonte';
  else if (scartoMax >= 5 || scartoMin >= 6 || minoranza >= 0.4) accordo = 'basso';
  else if (scartoMax >= 3 || scartoMin >= 4 || minoranza > 0) accordo = 'medio';
  else accordo = 'alto';

  const differenze = [];
  if (bagnate.length && asciutte.length) {
    const nomi = (a) => a.map((x) => x.fonte.breve).join(', ');
    differenze.push('pioggia per ' + nomi(bagnate) + ', asciutto per ' + nomi(asciutte));
  }
  if (scartoMax >= 3) differenze.push('massime da ' + Math.min(...cMax) + ' a ' + Math.max(...cMax) + ' °C');
  if (scartoMin >= 4) differenze.push('minime da ' + Math.min(...cMin) + ' a ' + Math.max(...cMin) + ' °C');

  const fasce = {};
  for (const [nome] of FASCE) {
    const f = v.map((x) => x.dati.fasce[nome]).filter(Boolean);
    if (!f.length) continue;
    fasce[nome] = {
      t: arrotonda(mediana(f.map((x) => x.t))), cielo: votaCielo(f.map((x) => x.cielo)),
      pioggia: arrotonda(mediana(f.map((x) => x.pioggia))), mm: arrotonda(mediana(f.map((x) => x.mm)), 1), fonti: f.length
    };
  }
  return {
    data: giorno,
    min: arrotonda(mediana(mins)), max: arrotonda(mediana(maxs)),
    cielo: votaCielo(v.map((x) => x.dati.cielo)),
    pioggia: arrotonda(mediana(v.map((x) => x.dati.pioggia))),
    mm: arrotonda(mediana(v.map((x) => x.dati.mm)), 1),
    vento: arrotonda(mediana(v.map((x) => x.dati.vento))),
    nFonti: n, verificato: n >= MINIMO_INCROCI, accordo, differenze,
    voti: { bagnato: bagnate.length, asciutto: asciutte.length },
    fasce,
    fonti: v.map((x) => ({ id: x.fonte.id, min: x.dati.min, max: x.dati.max, cielo: x.dati.cielo, pioggia: x.dati.pioggia, mm: x.dati.mm }))
  };
}

/* ---------- Testi ---------- */

function nomeGiorno(giorno, oggi) {
  const d = new Date(giorno + 'T12:00:00Z');
  const base = GIORNI_SETTIMANA[d.getUTCDay()] + ' ' + d.getUTCDate();
  if (giorno === oggi) return 'Oggi ' + base;
  if (giorno === piuGiorni(oggi, 1)) return 'Domani ' + base;
  return base.charAt(0).toUpperCase() + base.slice(1);
}
const gradi = (g) => (g.min === null ? '?' : g.min) + '–' + (g.max === null ? '?' : g.max) + ' °C';
function rigaGiorno(g, oggi) {
  const parti = [NOME_CIELO[g.cielo] || 'cielo incerto', gradi(g)];
  if (g.pioggia !== null) parti.push('pioggia ' + g.pioggia + '%');
  if (g.mm >= 0.5) parti.push(String(g.mm).replace('.', ',') + ' mm');
  if (g.vento !== null && g.vento >= 25) parti.push('vento fino a ' + g.vento + ' km/h');
  let r = nomeGiorno(g.data, oggi) + (g.daOra ? ' (cielo e pioggia dalle ' + g.daOra + ' in poi)' : '') + ': ' + parti.join(', ') + '.';
  const fasce = FASCE.filter(([f]) => g.fasce[f]).map(([f]) => f + ' ' + (NOME_CIELO[g.fasce[f].cielo] || '?') + ' ' + g.fasce[f].t + ' °C');
  if (fasce.length) r += ' ' + fasce.join(', ').replace(/^./, (c) => c.toUpperCase()) + '.';
  const accordo = { alto: 'Fonti concordi', medio: 'Fonti abbastanza concordi', basso: 'Fonti discordi', 'una fonte': 'Una sola fonte' }[g.accordo];
  r += ' ' + accordo + ' (' + fonti(g.nFonti) + ')' + (g.differenze.length ? ': ' + g.differenze.join('; ') : '') + '.';
  r += ' Per fonte: ' + g.fonti.map((f) => FONTI.find((x) => x.id === f.id).breve + ' ' + gradi(f).replace(' °C', '') + ' ' + (NOME_CIELO[f.cielo] || '?')).join('; ') + '.';
  return r;
}
function breveGiorno(g, oggi) {
  return nomeGiorno(g.data, oggi).split(' ')[0].toLowerCase() + ' ' + (NOME_CIELO[g.cielo] || '?') + ' ' + gradi(g);
}

/* ---------- Verifica di un luogo ---------- */

// Restituisce {previsioni} con la stessa forma di sync/meteo, oppure {errore} se nessuna fonte ha risposto.
async function verifica(luogo, giorni, idOrdini) {
  const adesso = new Date();
  const oggi = giornoLocale(adesso, luogo.tz);
  const oraAdesso = oraLocale(adesso, luogo.tz);
  const esito = (p) => p.then((ore) => ({ ore }), (e) => ({ errore: e.message }));
  const [openMeteo, altre] = await Promise.all([
    tuttiOpenMeteo(luogo, giorni),
    Promise.all([esito(oreMetNo(luogo)), esito(oreBrightSky(luogo, giorni)), esito(oreWttr(luogo)), esito(ore7Timer(luogo))])
  ]);
  const perTipo = { metno: altre[0], brightsky: altre[1], wttr: altre[2], settetimer: altre[3] };
  const risposte = FONTI.map((fonte) => ({ fonte, ...(fonte.modello ? openMeteo[fonte.id] : perTipo[fonte.tipo]) }))
    // Una fonte di riserva entra solo se la sua principale non ha dati: lo stesso modello non vale due incroci.
    .filter((r) => !r.fonte.riserva || !openMeteo[r.fonte.riserva] || !openMeteo[r.fonte.riserva].ore);

  const date = Array.from({ length: giorni }, (_, i) => piuGiorni(oggi, i));
  const fontiOk = [];
  const mancanti = [];
  const perGiorno = date.map(() => []);
  for (const r of risposte) {
    if (r.errore) { mancanti.push({ id: r.fonte.id, nome: r.fonte.nome, motivo: r.errore }); continue; }
    let utile = false;
    date.forEach((g, i) => {
      const dati = riassumiGiorno(r.ore.filter((o) => o.giorno === g), i === 0 ? oraAdesso : 0);
      if (dati) { utile = true; perGiorno[i].push({ fonte: r.fonte, dati }); }
    });
    if (utile) fontiOk.push(r.fonte); else mancanti.push({ id: r.fonte.id, nome: r.fonte.nome, motivo: 'nessun dato per questi giorni' });
  }
  if (!fontiOk.length) return { errore: mancanti[0] ? mancanti[0].motivo : 'nessun dato', mancanti };

  const giorniIncrociati = date.map((g, i) => (perGiorno[i].length ? Object.assign(incrocia(g, perGiorno[i]), i === 0 && oraAdesso > 0 ? { daOra: oraAdesso } : {}) : null)).filter(Boolean);
  const primo = giorniIncrociati[0];
  const verificato = !!primo && primo.data === oggi && primo.nFonti >= MINIMO_INCROCI;
  const ora = adesso.toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Rome' });
  const testo = [
    luogo.nome + ': previsioni incrociate di ' + (fontiOk.length === 1 ? 'un solo modello meteo' : fontiOk.length + ' modelli meteo indipendenti') + ' (' + fontiOk.map((f) => f.nome).join(', ') + '), calcolate oggi alle ' + ora + ' (ora italiana).' +
      (luogo.tz !== 'Europe/Rome' ? ' Giorni e ore sono quelli locali di ' + luogo.nome + '.' : '') +
      (mancanti.length ? ' Non hanno risposto: ' + mancanti.map((m) => m.nome).join(', ') + '.' : '') +
      (verificato ? '' : ' Meno di ' + MINIMO_INCROCI + ' fonti per oggi: previsione non verificata.'),
    ...giorniIncrociati.map((g) => rigaGiorno(g, oggi)),
    'Temperature: mediana delle fonti. Probabilità di pioggia: la più alta della giornata, mediana delle fonti che la danno.'
  ].join('\n');

  return {
    previsioni: {
      aggiornato: adesso.toISOString(),
      luogo: luogo.nome,
      testo,
      fonti: fontiOk.map((f) => f.nome),
      verifica: {
        nFonti: fontiOk.length,
        minimo: MINIMO_INCROCI,
        verificato,
        oggi,
        fuso: luogo.tz,
        coordinate: { lat: arrotonda(luogo.lat, 3), lon: arrotonda(luogo.lon, 3) },
        fonti: fontiOk.map((f) => ({ id: f.id, nome: f.nome, breve: f.breve })),
        mancanti: mancanti.map((m) => ({ id: m.id, nome: m.nome })),
        giorni: giorniIncrociati,
        ordini: idOrdini
      }
    },
    sintesi: luogo.nome + ', ' + (verificato ? 'verificato su ' + fonti(primo.nFonti) : 'solo ' + fonti(primo ? primo.nFonti : 0) + ' per oggi, ne servono almeno ' + MINIMO_INCROCI + ': non verificato') +
      ': ' + giorniIncrociati.slice(0, 2).map((g) => breveGiorno(g, oggi)).join(', ') + '.',
    verificato
  };
}

/* ---------- Esecuzione ---------- */

(async () => {
  const ordini = leggiOrdiniMeteo();
  // Un gruppo per luogo: ogni luogo si verifica una volta sola, con il numero di giorni più alto chiesto.
  const gruppi = new Map();
  for (const o of ordini) {
    const nome = pulisciLuogo(o.argomenti && o.argomenti.luogo);
    const k = chiaveLuogo(nome);
    const g = gruppi.get(k) || { nome, ordini: [], giorni: 1 };
    g.ordini.push(o);
    g.giorni = Math.max(g.giorni, pulisciGiorni(o.argomenti && o.argomenti.giorni));
    gruppi.set(k, g);
  }
  if (!ordini.length) gruppi.set(chiaveLuogo(CASA.nome), { nome: CASA.nome, ordini: [], giorni: 3 });

  const esiti = {};
  const scriviEsito = (o, stato, esito, previsioni) => {
    esiti[o.id] = { stato, esito };
    scrivi(path.join(dirUscita, 'ordini-meteo', o.id + '.json'), { stato, esito, eseguito: new Date().toISOString(), ...(previsioni ? { previsioni } : {}) });
  };
  const riepilogo = [];
  let qualcosa = false;
  let i = 0;
  for (const [k, g] of gruppi) {
    if (++i > MASSIMO_LUOGHI) {
      for (const o of g.ordini) scriviEsito(o, 'errore', 'Troppe località insieme: chiedimi ' + g.nome + ' tra poco.');
      continue;
    }
    let luogo;
    try {
      luogo = await trovaLuogo(g.nome);
    } catch (e) {
      for (const o of g.ordini) scriviEsito(o, 'errore', 'Il servizio meteo non ha risposto: ' + e.message + '.');
      riepilogo.push({ luogo: g.nome, errore: e.message });
      continue;
    }
    if (!luogo) {
      for (const o of g.ordini) scriviEsito(o, 'errore', 'Non trovo la località "' + g.nome + '".');
      riepilogo.push({ luogo: g.nome, trovato: false });
      continue;
    }
    const r = await verifica(luogo, g.giorni, g.ordini.map((o) => o.id));
    if (r.errore) {
      console.error('Nessuna fonte meteo per ' + luogo.nome + ': ' + r.mancanti.map((m) => m.nome + ' (' + m.motivo + ')').join('; '));
      for (const o of g.ordini) scriviEsito(o, 'errore', 'Nessuna fonte meteo ha risposto: ' + r.errore + '.');
      riepilogo.push({ luogo: luogo.nome, errore: r.errore });
      continue;
    }
    qualcosa = true;
    // sync/meteo resta la città di casa: le altre località viaggiano solo con il loro ordine.
    if (k === chiaveLuogo(CASA.nome)) scrivi(path.join(dirUscita, 'sync', 'meteo.json'), r.previsioni);
    for (const o of g.ordini) scriviEsito(o, r.verificato ? 'eseguito' : 'errore', r.verificato ? r.sintesi : 'Previsioni aggiornate ma ' + r.sintesi.replace(luogo.nome + ', ', ''), r.previsioni);
    const v = r.previsioni.verifica;
    riepilogo.push({
      luogo: luogo.nome, fuso: luogo.tz, fonti: v.fonti.map((f) => f.id), mancanti: v.mancanti.map((m) => m.id), verificato: v.verificato,
      giorni: v.giorni.map((d) => ({ data: d.data, cielo: d.cielo, min: d.min, max: d.max, pioggia: d.pioggia, nFonti: d.nFonti, accordo: d.accordo }))
    });
  }
  console.log(JSON.stringify({ verifiche: riepilogo, ordini: esiti }, null, 2));
  process.exit(qualcosa || !riepilogo.some((x) => x.errore) ? 0 : 3);
})().catch((e) => {
  console.error(e && e.stack ? e.stack : String(e));
  process.exit(1);
});
