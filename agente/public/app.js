// Interfaccia di Agente 1: chat scritta o vocale, notifiche e aggiornamento automatico.
const CHIAVE_CHAT = 'agente1-chat';
const CHIAVE_TOKEN = 'agente1-token';
const CHIAVE_VOCE = 'agente1-voce';
const RICONOSCIMENTO = window.SpeechRecognition || window.webkitSpeechRecognition;

const $ = (id) => document.getElementById(id);

// localStorage può essere bloccato (modalità privata): ogni accesso è protetto.
const memo = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* memoria piena o bloccata */ } }
};

let messaggi = caricaChat();
let voceAttiva = memo.get(CHIAVE_VOCE) === 'on';
let parlando = false;
let riconoscitore = null;
let versioneIniziale = null;
let notificheViste = null;

function caricaChat() {
  try { return JSON.parse(memo.get(CHIAVE_CHAT)) || []; } catch { return []; }
}

function salvaChat() {
  memo.set(CHIAVE_CHAT, JSON.stringify(messaggi.slice(-40)));
}

function stato(nome, testo) {
  document.body.dataset.stato = nome;
  $('stato').textContent = testo;
}

function mostra(ruolo, testo) {
  const voce = document.createElement('li');
  voce.className = `msg ${ruolo}`;
  voce.textContent = testo;
  $('chat').appendChild(voce);
  voce.scrollIntoView({ block: 'end', behavior: 'smooth' });
}

function ridisegna() {
  $('chat').innerHTML = '';
  if (!messaggi.length) mostra('assistant', 'Sono Agente 1. Dimmi cosa ti serve: contabilità, vendite, meteo o un riepilogo della giornata.');
  messaggi.forEach((m) => mostra(m.role, m.content));
}

function chiediToken() {
  $('velo-token').hidden = false;
  $('input-token').focus();
}

async function api(percorso, opzioni = {}) {
  const token = memo.get(CHIAVE_TOKEN);
  const r = await fetch(percorso, {
    ...opzioni,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {})
    }
  });
  if (r.status === 401) {
    chiediToken();
    throw new Error('Serve il codice di accesso');
  }
  const j = await r.json();
  if (!r.ok) throw new Error(j.errore || `Errore ${r.status}`);
  return j;
}

/* ---------- Conversazione ---------- */

async function invia(testo) {
  testo = testo.trim();
  if (!testo) return;

  messaggi.push({ role: 'user', content: testo });
  salvaChat();
  mostra('user', testo);
  stato('pensa', 'sto ragionando…');

  try {
    const { risposta } = await api('/api/chat', { method: 'POST', body: JSON.stringify({ messaggi }) });
    messaggi.push({ role: 'assistant', content: risposta });
    salvaChat();
    mostra('assistant', risposta);
    parla(risposta);
  } catch (e) {
    messaggi.pop(); // il messaggio non è arrivato: lo rimuovo dalla cronologia
    salvaChat();
    mostra('errore', e.message);
  } finally {
    if (!parlando) stato('ascolto', 'in ascolto');
  }
}

/* ---------- Voce in uscita (sintesi vocale del browser) ---------- */

function parla(testo) {
  if (!voceAttiva || !('speechSynthesis' in window)) return;
  const u = new SpeechSynthesisUtterance(testo);
  u.lang = 'it-IT';
  const voceItaliana = speechSynthesis.getVoices().find((v) => v.lang.startsWith('it'));
  if (voceItaliana) u.voice = voceItaliana;
  u.rate = 1.02;
  u.onstart = () => { parlando = true; stato('parla', 'parlo…'); };
  u.onend = () => { parlando = false; stato('ascolto', 'in ascolto'); };
  u.onerror = u.onend;
  speechSynthesis.cancel();
  speechSynthesis.speak(u);
}

function aggiornaPulsanteVoce() {
  $('btn-voce-uscita').textContent = voceAttiva ? 'Voce on' : 'Voce off';
  $('btn-voce-uscita').classList.toggle('attivo', voceAttiva);
}

/* ---------- Voce in ingresso (riconoscimento vocale del browser) ---------- */

function ascolta() {
  if (!RICONOSCIMENTO) {
    mostra('errore', 'Questo browser non supporta il riconoscimento vocale: usa Chrome o Edge, oppure scrivi.');
    return;
  }
  if (riconoscitore) {
    riconoscitore.stop();
    return;
  }
  const r = new RICONOSCIMENTO();
  r.lang = 'it-IT';
  r.interimResults = false;
  r.maxAlternatives = 1;
  r.onstart = () => {
    $('btn-voce').classList.add('attivo');
    stato('ascolta', 'ti ascolto…');
  };
  r.onresult = (e) => invia(e.results[0][0].transcript);
  r.onerror = (e) => mostra('errore', `Microfono: ${e.error}`);
  r.onend = () => {
    riconoscitore = null;
    $('btn-voce').classList.remove('attivo');
    if (document.body.dataset.stato === 'ascolta') stato('ascolto', 'in ascolto');
  };
  riconoscitore = r;
  r.start();
}

/* ---------- Notifiche e aggiornamenti ---------- */

function mostraAvviso(n) {
  const box = document.createElement('div');
  box.className = 'avviso';
  const titolo = document.createElement('strong');
  titolo.textContent = n.titolo;
  const testo = document.createElement('p');
  testo.textContent = n.testo;
  box.append(titolo, testo);
  $('avvisi').appendChild(box);
  setTimeout(() => box.remove(), 9000);

  if ('Notification' in window && Notification.permission === 'granted') {
    new Notification(n.titolo, { body: n.testo });
  }
}

async function controllaNotifiche() {
  try {
    const { notifiche } = await api('/api/notifiche');
    // Al primo controllo segno come viste quelle già presenti, senza mostrarle di nuovo.
    const primaVolta = notificheViste === null;
    notificheViste = notificheViste || new Set();
    for (const n of notifiche) {
      if (notificheViste.has(n.id)) continue;
      notificheViste.add(n.id);
      if (!primaVolta) mostraAvviso(n);
    }
  } catch { /* al prossimo giro */ }
}

// Quando il server viene aggiornato, la pagina si ricarica da sola. La chat è salvata nel browser e non si perde.
async function controllaVersione() {
  try {
    const r = await fetch('/api/versione', { cache: 'no-store' });
    const { versione } = await r.json();
    if (versioneIniziale === null) versioneIniziale = versione;
    else if (versione !== versioneIniziale) location.reload();
  } catch { /* offline: riprova al prossimo giro */ }
}

/* ---------- Eventi ---------- */

$('form').addEventListener('submit', (e) => {
  e.preventDefault();
  const testo = $('input').value;
  $('input').value = '';
  invia(testo);
});

$('btn-voce').addEventListener('click', ascolta);
$('orb').addEventListener('click', ascolta);

$('btn-voce-uscita').addEventListener('click', () => {
  voceAttiva = !voceAttiva;
  memo.set(CHIAVE_VOCE, voceAttiva ? 'on' : 'off');
  if (!voceAttiva && 'speechSynthesis' in window) speechSynthesis.cancel();
  aggiornaPulsanteVoce();
});

$('btn-notifiche').addEventListener('click', async () => {
  if (!('Notification' in window)) {
    mostra('errore', 'Questo browser non supporta le notifiche.');
    return;
  }
  const permesso = await Notification.requestPermission();
  $('btn-notifiche').textContent = permesso === 'granted' ? 'Notifiche attive' : 'Notifiche negate';
});

$('form-token').addEventListener('submit', (e) => {
  e.preventDefault();
  memo.set(CHIAVE_TOKEN, $('input-token').value.trim());
  $('velo-token').hidden = true;
  controllaNotifiche();
});

/* ---------- Avvio ---------- */

if (!RICONOSCIMENTO) $('btn-voce').disabled = true;
if ('Notification' in window && Notification.permission === 'granted') $('btn-notifiche').textContent = 'Notifiche attive';
aggiornaPulsanteVoce();
ridisegna();
stato('ascolto', 'in ascolto');
controllaVersione();
controllaNotifiche();
setInterval(controllaNotifiche, 30000);
setInterval(controllaVersione, 60000);
