#!/usr/bin/env node
// Backup giornaliero di Agente 1.
// Raccoglie gli export (file JSON scritti da ArtifactData con out_dir) di Andamento vendite, Un passo alla volta
// e Agente 1 in un solo backup, diviso in parti da scrivere in backup/parte-<n> più l'indice backup/indice.
// Ogni giorno il nuovo backup sovrascrive quello del giorno prima. Il codice dello script della contabilità non viene copiato.
//
// Uso: node backup.js <uscita> <nome-fonte>=<cartella-export> [<nome-fonte>=<cartella-export> ...]
//   esempio: node backup.js W/out "Andamento vendite=W/vendite" "Un passo alla volta=W/stelle" "Agente 1=W/a1"
process.env.TZ = 'Europe/Rome';

const fs = require('node:fs');
const path = require('node:path');

const PARTE = 180000; // caratteri per documento: il limite di un documento del database è 256 KiB

const [dirUscita, ...fonti] = process.argv.slice(2);
if (!dirUscita || !fonti.length) {
  console.error('Uso: node backup.js <uscita> <nome-fonte>=<cartella-export> [...]');
  process.exit(1);
}

// Ogni file <collezione>/<id>.json diventa backup[fonte][collezione][id].
function leggiExport(radice) {
  const out = {};
  const giro = (dir) => {
    if (!fs.existsSync(dir)) return;
    for (const voce of fs.readdirSync(dir, { withFileTypes: true })) {
      const pieno = path.join(dir, voce.name);
      if (voce.isDirectory()) { giro(pieno); continue; }
      if (!voce.name.endsWith('.json')) continue;
      const collezione = path.relative(radice, dir).split(path.sep).join('/');
      const id = voce.name.slice(0, -5);
      let doc = JSON.parse(fs.readFileSync(pieno, 'utf8'));
      if (/^data\/users\/[^/]+$/.test(collezione) && id === 'contabilita') doc = { url: doc.url ? '(salvato)' : null, nota: 'il codice di accesso non viene copiato nel backup' };
      (out[collezione] = out[collezione] || {})[id] = doc;
    }
  };
  giro(radice);
  return out;
}

const ora = new Date();
const giorno = ora.getFullYear() + '-' + String(ora.getMonth() + 1).padStart(2, '0') + '-' + String(ora.getDate()).padStart(2, '0');
const backup = { app: 'Agente 1', creato: ora.toISOString(), giorno, fonti: {} };
const conteggi = {};
for (const coppia of fonti) {
  const i = coppia.indexOf('=');
  if (i < 1) { console.error('Fonte non valida: ' + coppia); process.exit(1); }
  const nome = coppia.slice(0, i);
  const dati = leggiExport(coppia.slice(i + 1));
  backup.fonti[nome] = dati;
  conteggi[nome] = Object.fromEntries(Object.entries(dati).map(([c, docs]) => [c, Object.keys(docs).length]));
}

const testo = JSON.stringify(backup);
const parti = [];
for (let i = 0; i < testo.length; i += PARTE) parti.push(testo.slice(i, i + PARTE));

const scrivi = (nome, dati) => {
  const file = path.join(dirUscita, 'backup', nome + '.json');
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify(dati) + '\n');
};
parti.forEach((t, i) => scrivi('parte-' + (i + 1), { n: i + 1, testo: t }));
scrivi('indice', { giorno, creato: backup.creato, parti: parti.length, caratteri: testo.length, conteggi });

console.log(JSON.stringify({ giorno, parti: parti.length, caratteri: testo.length, conteggi }, null, 2));
