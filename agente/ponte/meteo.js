#!/usr/bin/env node
// Reparto meteo di Agente 1: previsioni incrociate di più modelli meteo indipendenti.
// Interroga 5 modelli tramite Open-Meteo (ECMWF, ICON, GFS, Météo-France, ItaliaMeteo ICON-2I)
// e il servizio di MET Norway (yr.no), poi per ogni giorno prende la mediana dei numeri,
// il cielo più votato e misura quanto le fonti concordano.
//
// Uso: NODE_USE_ENV_PROXY=1 node meteo.js <uscita> [<export-ordini>]
//   <uscita>         scrive sync/meteo.json e, per ogni ordine meteo, ordini-meteo/<id>.json
//   <export-ordini>  cartella con ordini/<id>.json presi in carico: luogo e giorni vengono
//                    dall'ordine meteo più recente (argomenti.luogo, argomenti.giorni)
// Uscita: 0 se almeno una fonte ha risposto, 3 se nessuna fonte è raggiungibile
//         (in quel caso sync/meteo.json non viene scritto).
// Per le prove: METEO_OPEN_METEO, METEO_GEOCODING e METEO_MET_NO sostituiscono gli indirizzi dei servizi.
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
// MET Norway chiede un User-Agent che identifichi l'app.
const USER_AGENT = 'Agente1/1.0 github.com/ThomasBettino/contabilita';

const FONTI = [
  { id: 'ecmwf', nome: 'ECMWF (centro meteo europeo)', breve: 'ECMWF', modello: 'ecmwf_ifs025' },
  { id: 'icon', nome: 'ICON (servizio meteo tedesco DWD)', breve: 'ICON', modello: 'icon_seamless' },
  { id: 'gfs', nome: 'GFS (NOAA, Stati Uniti)', breve: 'GFS', modello: 'gfs_seamless' },
  { id: 'meteofrance', nome: 'Météo-France', breve: 'MÉTÉO-FR', modello: 'meteofrance_seamless' },
  { id: 'italiameteo', nome: 'ItaliaMeteo ICON-2I', breve: 'ITALIA', modello: 'italia_meteo_arpae_icon_2i' },
  { id: 'metno', nome: 'MET Norway (yr.no)', breve: 'YR.NO' }
];
const MINIMO_INCROCI = 3;

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
const giornoLocale = (d) => {
  const p = new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Rome', year: 'numeric', month: '2-digit', day: '2-digit' }).format(d);
  return p; // AAAA-MM-GG
};
const oraLocale = (d) => Number(new Intl.DateTimeFormat('en-GB', { timeZone: 'Europe/Rome', hour: '2-digit', hourCycle: 'h23' }).format(d));
function piuGiorni(giorno, n) {
  const d = new Date(giorno + 'T12:00:00Z');
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}
function mediana(v) {
  const a = v.filter((x) => x !== null).sort((x, y) => x - y);
  if (!a.length) return null;
  const m = Math.floor(a.length / 2);
  return a.length % 2 ? a[m] : (a[m - 1] + a[m]) / 2;
}
const fonti = (n) => n + (n === 1 ? ' fonte' : ' fonti');
const arrotonda = (x, cifre = 0) => (x === null ? null : Math.round(x * 10 ** cifre) / 10 ** cifre);

/* ---------- Luogo e giorni dall'ordine ---------- */

function leggiOrdiniMeteo() {
  const dir = dirOrdini ? path.join(dirOrdini, 'ordini') : null;
  if (!dir || !fs.existsSync(dir)) return [];
  return fs.readdirSync(dir).filter((f) => f.endsWith('.json'))
    .map((f) => ({ id: f.slice(0, -5), ...JSON.parse(fs.readFileSync(path.join(dir, f), 'utf8')) }))
    .filter((o) => o.agente === 'meteo')
    .sort((a, b) => String(a.creato).localeCompare(String(b.creato)));
}
// Il luogo arriva da un modello linguistico: solo lettere, spazi, apostrofi, trattini e punti.
function pulisciLuogo(x) {
  const s = String(x || '').normalize('NFC').replace(/[^\p{L}\p{M} '’.-]/gu, ' ').replace(/\s+/g, ' ').trim().slice(0, 60);
  return s || 'Bergamo';
}
const chiaveLuogo = (s) => pulisciLuogo(s).toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/[^a-z]/g, '');
function pulisciGiorni(x) {
  const n = Math.round(Number(x));
  return Number.isFinite(n) ? Math.min(5, Math.max(1, n)) : 3;
}

/* ---------- Rete ---------- */

async function prendiJson(url, intestazioni) {
  let r;
  try {
    r = await fetch(url, { headers: { 'user-agent': USER_AGENT, accept: 'application/json', ...(intestazioni || {}) }, signal: AbortSignal.timeout(20000) });
  } catch (e) {
    // Dietro il proxy dell'ambiente cloud un dominio non consentito arriva come errore di rete.
    throw new Error(e && e.name === 'TimeoutError' ? 'nessuna risposta in 20 secondi' : 'rete bloccata o servizio giù');
  }
  const testo = await r.text();
  let j = null;
  try { j = JSON.parse(testo); } catch (e) { /* risposta non JSON */ }
  if (!r.ok) throw new Error('HTTP ' + r.status + (j && j.reason ? ': ' + String(j.reason).slice(0, 160) : ''));
  if (!j) throw new Error('risposta non JSON');
  return j;
}

async function trovaLuogo(nome) {
  if (chiaveLuogo(nome) === 'bergamo') return { nome: 'Bergamo', lat: 45.6983, lon: 9.6773 };
  const u = GEOCODING + '/v1/search?count=1&language=it&format=json&name=' + encodeURIComponent(nome);
  const j = await prendiJson(u);
  const r = j && Array.isArray(j.results) ? j.results[0] : null;
  if (!r || num(r.latitude) === null || num(r.longitude) === null) return null;
  const etichetta = [r.name, r.country_code && r.country_code !== 'IT' ? r.country : null].filter(Boolean).join(', ');
  return { nome: pulisciLuogo(etichetta || nome), lat: r.latitude, lon: r.longitude };
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
  if (nubi !== null) return nubi < 20 ? 'sereno' : nubi < 50 ? 'poco_nuvoloso' : nubi < 80 ? 'nuvoloso' : 'coperto';
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

async function oreOpenMeteo(fonte, luogo, giorni) {
  const variabili = 'temperature_2m,precipitation,precipitation_probability,weather_code,cloud_cover,wind_speed_10m';
  const u = OPEN_METEO + '/v1/forecast?latitude=' + luogo.lat + '&longitude=' + luogo.lon +
    '&hourly=' + variabili + '&models=' + fonte.modello + '&timezone=Europe%2FRome&forecast_days=' + giorni + '&wind_speed_unit=kmh';
  const j = await prendiJson(u);
  const h = j && j.hourly;
  if (!h || !Array.isArray(h.time)) throw new Error('risposta senza dati orari');
  // Con un solo modello i nomi sono semplici; con più modelli hanno il suffisso del modello.
  const col = (v) => (Array.isArray(h[v]) ? h[v] : Array.isArray(h[v + '_' + fonte.modello]) ? h[v + '_' + fonte.modello] : []);
  const T = col('temperature_2m'), P = col('precipitation'), PP = col('precipitation_probability'), C = col('weather_code'), N = col('cloud_cover'), V = col('wind_speed_10m');
  const ore = [];
  h.time.forEach((t, i) => {
    const m = /^(\d{4}-\d{2}-\d{2})T(\d{2}):/.exec(String(t));
    if (!m) return;
    const temp = num(T[i]);
    if (temp === null) return; // ore oltre l'orizzonte del modello
    const nubi = num(N[i]);
    ore.push({ giorno: m[1], ora: Number(m[2]), t: temp, mm: num(P[i]), prob: num(PP[i]), cielo: cieloDaWmo(num(C[i]), nubi), nubi, vento: num(V[i]) });
  });
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
    if (isNaN(d)) continue;
    const ist = (s.data && s.data.instant && s.data.instant.details) || {};
    const temp = num(ist.air_temperature);
    if (temp === null) continue;
    const n1 = s.data.next_1_hours, n6 = s.data.next_6_hours;
    // Dove la serie diventa ogni 6 ore, la pioggia di 6 ore conta una volta sola.
    const prossimo = n1 || n6;
    const simbolo = prossimo && prossimo.summary ? prossimo.summary.symbol_code : null;
    const nubi = num(ist.cloud_area_fraction);
    ore.push({
      giorno: giornoLocale(d), ora: oraLocale(d), t: temp,
      mm: prossimo && prossimo.details ? num(prossimo.details.precipitation_amount) : null,
      prob: prossimo && prossimo.details ? num(prossimo.details.probability_of_precipitation) : null,
      cielo: cieloDaSimbolo(simbolo) || (nubi !== null ? cieloDaNubi(nubi) : null), nubi,
      vento: num(ist.wind_speed) === null ? null : ist.wind_speed * 3.6
    });
  }
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

function riassumiGiorno(ore) {
  if (ore.length < 4) return null;
  const temp = ore.map((o) => o.t);
  // Una fonte che parte da adesso (yr.no) non vede la notte né, di sera, il caldo del giorno:
  // quei valori non entrano nell'incrocio.
  const prima = Math.min(...ore.map((o) => o.ora));
  const diurne = ore.filter((o) => o.ora >= 7 && o.ora <= 20);
  const probs = ore.map((o) => o.prob).filter((x) => x !== null);
  const venti = ore.map((o) => o.vento).filter((x) => x !== null);
  const fasce = {};
  for (const [nome, da, a] of FASCE) {
    const f = ore.filter((o) => o.ora >= da && o.ora < a);
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
    min: prima <= 3 ? arrotonda(Math.min(...temp)) : null, max: prima <= 13 ? arrotonda(Math.max(...temp)) : null,
    cielo: cieloPrevalente(diurne.length >= 3 ? diurne : ore, 4, 0.5),
    pioggia: probs.length ? Math.max(...probs) : null,
    mm: arrotonda(ore.reduce((s, o) => s + (o.mm || 0), 0), 1),
    vento: venti.length ? arrotonda(Math.max(...venti)) : null,
    fasce
  };
}

/* ---------- Incrocio delle fonti ---------- */

function votaCielo(cieli) {
  const voti = {};
  for (const c of cieli) if (c) voti[c] = (voti[c] || 0) + 1;
  const ordine = Object.entries(voti).sort((a, b) => b[1] - a[1] || CIELI.indexOf(b[0]) - CIELI.indexOf(a[0]));
  return ordine.length ? ordine[0][0] : null;
}

function incrocia(giorno, perFonte) {
  const v = perFonte.filter((x) => x.dati);
  const n = v.length;
  const mins = v.map((x) => x.dati.min).filter((x) => x !== null), maxs = v.map((x) => x.dati.max).filter((x) => x !== null);
  const bagnate = v.filter((x) => BAGNATO.has(x.dati.cielo));
  const asciutte = v.filter((x) => x.dati.cielo && !BAGNATO.has(x.dati.cielo));
  const scartoMax = maxs.length ? Math.max(...maxs) - Math.min(...maxs) : 0;
  const scartoMin = mins.length ? Math.max(...mins) - Math.min(...mins) : 0;
  const scarto = Math.max(scartoMax, scartoMin);
  const minoranza = Math.min(bagnate.length, asciutte.length) / Math.max(1, bagnate.length + asciutte.length);
  let accordo;
  if (n < 2) accordo = 'una fonte';
  else if (scarto >= 5 || minoranza >= 0.4) accordo = 'basso';
  else if (scarto >= 3 || minoranza > 0) accordo = 'medio';
  else accordo = 'alto';

  const differenze = [];
  if (bagnate.length && asciutte.length) {
    const nomi = (a) => a.map((x) => x.fonte.breve).join(', ');
    differenze.push('pioggia per ' + nomi(bagnate) + ', asciutto per ' + nomi(asciutte));
  }
  if (scartoMax >= 3) differenze.push('massime da ' + Math.min(...maxs) + ' a ' + Math.max(...maxs) + ' °C');
  if (scartoMin >= 3) differenze.push('minime da ' + Math.min(...mins) + ' a ' + Math.max(...mins) + ' °C');

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
  let r = nomeGiorno(g.data, oggi) + ': ' + parti.join(', ') + '.';
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

/* ---------- Esecuzione ---------- */

(async () => {
  const ordini = leggiOrdiniMeteo();
  const ultimo = ordini[ordini.length - 1];
  const richiesto = pulisciLuogo(ultimo && ultimo.argomenti ? ultimo.argomenti.luogo : 'Bergamo');
  const giorni = pulisciGiorni(ultimo && ultimo.argomenti ? ultimo.argomenti.giorni : 3);
  const adesso = new Date();
  const oggi = giornoLocale(adesso);
  const esiti = {};
  const chiudi = (stato, esito, filtro) => { for (const o of ordini) if (!esiti[o.id] && (!filtro || filtro(o))) esiti[o.id] = { stato, esito }; };
  const scriviEsiti = () => {
    for (const o of ordini) {
      const e = esiti[o.id] || { stato: 'errore', esito: 'Verifica non eseguita.' };
      scrivi(path.join(dirUscita, 'ordini-meteo', o.id + '.json'), { stato: e.stato, esito: e.esito, eseguito: new Date().toISOString() });
    }
  };

  // Gli ordini per un altro luogo restano da rifare: questo giro verifica il luogo dell'ordine più recente.
  chiudi('errore', 'In questo giro ho verificato ' + richiesto + ': chiedimi di nuovo la verifica per l\'altro luogo.',
    (o) => chiaveLuogo(o.argomenti && o.argomenti.luogo) !== chiaveLuogo(richiesto));

  let luogo;
  try {
    luogo = await trovaLuogo(richiesto);
  } catch (e) {
    console.error('Ricerca del luogo non riuscita: ' + e.message);
    chiudi('errore', 'Il servizio meteo non ha risposto: ' + e.message + '.');
    scriviEsiti();
    process.exit(3);
  }
  if (!luogo) {
    chiudi('errore', 'Non trovo la località "' + richiesto + '".');
    scriviEsiti();
    console.log(JSON.stringify({ luogo: richiesto, trovato: false }));
    process.exit(0);
  }

  const risposte = await Promise.all(FONTI.map(async (fonte) => {
    try {
      const ore = fonte.modello ? await oreOpenMeteo(fonte, luogo, giorni) : await oreMetNo(luogo);
      return { fonte, ore };
    } catch (e) {
      return { fonte, errore: e.message };
    }
  }));

  const date = Array.from({ length: giorni }, (_, i) => piuGiorni(oggi, i));
  const fontiOk = [];
  const mancanti = [];
  const perGiorno = date.map(() => []);
  for (const r of risposte) {
    if (r.errore) { mancanti.push({ id: r.fonte.id, nome: r.fonte.nome, motivo: r.errore }); continue; }
    let utile = false;
    date.forEach((g, i) => {
      const dati = riassumiGiorno(r.ore.filter((o) => o.giorno === g));
      if (dati) { utile = true; perGiorno[i].push({ fonte: r.fonte, dati }); }
    });
    if (utile) fontiOk.push(r.fonte); else mancanti.push({ id: r.fonte.id, nome: r.fonte.nome, motivo: 'nessun dato per questi giorni' });
  }

  if (!fontiOk.length) {
    console.error('Nessuna fonte meteo raggiungibile: ' + mancanti.map((m) => m.nome + ' (' + m.motivo + ')').join('; '));
    chiudi('errore', 'Nessuna fonte meteo ha risposto: ' + (mancanti[0] ? mancanti[0].motivo : 'errore') + '.');
    scriviEsiti();
    process.exit(3);
  }

  const giorniIncrociati = date.map((g, i) => (perGiorno[i].length ? incrocia(g, perGiorno[i]) : null)).filter(Boolean);
  const primo = giorniIncrociati[0];
  const verificato = !!primo && primo.nFonti >= MINIMO_INCROCI;
  const ora = adesso.toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' });
  const testo = [
    luogo.nome + ': previsioni incrociate di ' + (fontiOk.length === 1 ? 'un solo modello meteo' : fontiOk.length + ' modelli meteo indipendenti') + ' (' + fontiOk.map((f) => f.nome).join(', ') + '), calcolate oggi alle ' + ora + '.' +
      (mancanti.length ? ' Non hanno risposto: ' + mancanti.map((m) => m.nome).join(', ') + '.' : '') +
      (verificato ? '' : ' Meno di ' + MINIMO_INCROCI + ' fonti per oggi: previsione non verificata.'),
    ...giorniIncrociati.map((g) => rigaGiorno(g, oggi)),
    'Temperature: mediana delle fonti. Probabilità di pioggia: la più alta della giornata, mediana delle fonti che la danno.'
  ].join('\n');

  const sync = {
    aggiornato: adesso.toISOString(),
    luogo: luogo.nome,
    testo,
    fonti: fontiOk.map((f) => f.nome),
    verifica: {
      nFonti: fontiOk.length,
      minimo: MINIMO_INCROCI,
      verificato,
      coordinate: { lat: arrotonda(luogo.lat, 3), lon: arrotonda(luogo.lon, 3) },
      fonti: fontiOk.map((f) => ({ id: f.id, nome: f.nome, breve: f.breve })),
      mancanti: mancanti.map((m) => ({ id: m.id, nome: m.nome })),
      giorni: giorniIncrociati,
      ordini: ordini.filter((o) => !esiti[o.id]).map((o) => o.id)
    }
  };
  scrivi(path.join(dirUscita, 'sync', 'meteo.json'), sync);

  const sintesi = giorniIncrociati.slice(0, 2).map((g) => breveGiorno(g, oggi)).join(', ');
  if (verificato) chiudi('eseguito', luogo.nome + ', verificato su ' + fonti(primo.nFonti) + ': ' + sintesi + '.');
  else chiudi('errore', 'Solo ' + fonti(primo ? primo.nFonti : 0) + ' su ' + FONTI.length + ' per oggi: ne servono almeno ' + MINIMO_INCROCI + '. Previsioni aggiornate ma non verificate: ' + sintesi + '.');
  scriviEsiti();

  console.log(JSON.stringify({
    luogo: luogo.nome, fonti: fontiOk.map((f) => f.id), mancanti, verificato,
    giorni: giorniIncrociati.map((g) => ({ data: g.data, cielo: g.cielo, min: g.min, max: g.max, pioggia: g.pioggia, nFonti: g.nFonti, accordo: g.accordo })),
    ordini: esiti
  }, null, 2));
})().catch((e) => {
  console.error(e && e.stack ? e.stack : String(e));
  process.exit(1);
});
