"use strict";

const $ = (id) => document.getElementById(id);
const eur = (n) => new Intl.NumberFormat("it-IT", { style: "currency", currency: "EUR" }).format(n || 0);
const quando = (ts) => new Date(ts * 1000).toLocaleString("it-IT", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

/* Elementi creati con textContent: nessun testo di Ada o dei dati finisce mai come HTML. */
function h(tag, attrs, ...figli) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v);
  }
  for (const f of figli.flat()) if (f != null) el.append(f.nodeType ? f : document.createTextNode(String(f)));
  return el;
}
const svuota = (el, ...nuovi) => el.replaceChildren(...nuovi.flat().filter((x) => x != null && x !== false));

function leggiToken() { try { return localStorage.getItem("ada_token") || ""; } catch (e) { return ""; } }
function salvaToken(t) { try { localStorage.setItem("ada_token", t); } catch (e) { /* storage bloccato */ } }

let richiestaToken = null;
function chiediToken() {  // più chiamate insieme fanno una sola domanda
  richiestaToken ||= Promise.resolve().then(() => {
    const t = prompt("Inserisci il token di accesso di Ada");
    richiestaToken = null;
    if (t) salvaToken(t.trim());
    return t ? t.trim() : "";
  });
  return richiestaToken;
}

async function api(path, dati) {
  const opz = { headers: { Authorization: "Bearer " + leggiToken() } };
  if (dati !== undefined) { opz.method = "POST"; opz.headers["Content-Type"] = "application/json"; opz.body = JSON.stringify(dati); }
  let r = await fetch(path, opz);
  if (r.status === 401) {
    const t = await chiediToken();
    if (!t) throw new Error("Accesso negato");
    opz.headers.Authorization = "Bearer " + t;
    r = await fetch(path, opz);
  }
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.errore || "Errore " + r.status);
  return j;
}

let toastT;
function toast(msg) {
  const t = $("toast"); t.textContent = msg; t.classList.add("su");
  clearTimeout(toastT); toastT = setTimeout(() => t.classList.remove("su"), 3200);
}

/* ---------- navigazione ---------- */
function vai(nome) {
  document.querySelectorAll(".vista").forEach((v) => (v.hidden = v.id !== "v-" + nome));
  document.querySelectorAll(".barra button").forEach((b) => b.classList.toggle("attiva", b.dataset.vai === nome));
  if (nome === "ada") scorriChat();
}
document.querySelectorAll("[data-vai]").forEach((b) => b.addEventListener("click", () => vai(b.dataset.vai)));

/* ---------- chat ---------- */
function scorriChat() { const m = $("msgs"); m.scrollTop = m.scrollHeight; }
/* Grassetto (**testo**) ed elenchi (- voce), costruiti come elementi: niente HTML dal testo. */
function testoRicco(testo) {
  const frag = document.createDocumentFragment();
  const righe = String(testo).split("\n");
  righe.forEach((riga, i) => {
    const m = riga.match(/^\s*[-*]\s+(.*)$/);
    if (m) frag.append("• ");
    (m ? m[1] : riga).split(/(\*\*[^*]+\*\*)/).forEach((parte) => {
      if (/^\*\*[^*]+\*\*$/.test(parte)) frag.append(h("strong", null, parte.slice(2, -2)));
      else if (parte) frag.append(parte);
    });
    if (i < righe.length - 1) frag.append("\n");
  });
  return frag;
}
function bolla(ruolo, testo, extra) {
  return h("div", { class: "msg " + ruolo + (extra ? " " + extra : "") }, ruolo === "ada" && !extra ? testoRicco(testo) : testo);
}

async function caricaChat() {
  const { messaggi } = await api("/api/chat");
  svuota($("msgs"), messaggi.length
    ? messaggi.map((m) => bolla(m.ruolo, m.testo))
    : h("div", { class: "vuoto" }, "Ciao, sono Ada. Gestisco io il team: dimmi cosa ti serve, oppure chiedimi come sta andando tutto."));
  scorriChat();
}

async function manda(testo) {
  testo = testo.trim();
  if (!testo) return;
  const inp = $("testo"), btn = $("invia"), msgs = $("msgs");
  inp.value = ""; inp.disabled = btn.disabled = true;
  msgs.querySelector(".vuoto")?.remove();
  msgs.append(bolla("utente", testo));
  const pensa = bolla("ada", "Ci penso…", "pensa");
  msgs.append(pensa); scorriChat();
  $("orb").classList.add("pensa");
  // mentre aspetta, la bolla dice cosa sta facendo (chi lavora e quale strumento sta usando)
  const segui = setInterval(async () => {
    try {
      const { lavori } = await api("/api/lavori");
      if (!lavori.length) return;
      pensa.textContent = lavori.map((l) => `${l.titolo}: ${l.cosa}` + (l.passo ? ` · ${NOMI_STRUMENTI[l.passo] || l.passo}` : "")).join("\n");
      scorriChat();
    } catch (e) { /* si riprova al prossimo giro */ }
  }, 1500);
  try {
    const { risposta } = await api("/api/chat", { messaggio: testo });
    pensa.className = "msg ada"; pensa.replaceChildren(testoRicco(risposta));
  } catch (e) {
    pensa.className = "msg ada"; pensa.textContent = "Non riesco a rispondere: " + e.message;
  } finally {
    clearInterval(segui);
    $("orb").classList.remove("pensa");
    inp.disabled = btn.disabled = false; scorriChat();
    aggiorna();
  }
}
$("form-chat").addEventListener("submit", (e) => { e.preventDefault(); manda($("testo").value); });
$("sugg").addEventListener("click", (e) => { if (e.target.tagName === "BUTTON") manda(e.target.textContent); });

/* ---------- stato ---------- */
let titoli = {};
const nome = (id) => titoli[id] || id;

function disegna(s) {
  titoli = Object.fromEntries(s.agenti.map((a) => [a.nome, a.titolo]));
  $("orb").classList.toggle("spenta", !s.ada.cervello);
  $("stato-ada").textContent = !s.ada.cervello
    ? "Cervello non collegato"
    : s.approvazioni.length ? `${s.approvazioni.length} cose aspettano te`
    : s.segnalazioni_aperte ? `${s.segnalazioni_aperte} ${s.segnalazioni_aperte === 1 ? "problema da sistemare" : "problemi da sistemare"}`
    : "Tutto sotto controllo" + ((s.telefono || {}).collegato ? "" : " · schermo non collegato");
  const tel = s.telefono || {};
  const stop = $("btn-stop");
  stop.hidden = !(tel.collegato || tel.fermo);  // fermo ma scollegato: il tasto per riattivare deve restare
  $("btn-collega").hidden = !!tel.collegato || !!tel.fermo;
  stop.className = "stop" + (tel.fermo ? " riattiva" : "");
  stop.textContent = tel.fermo ? "▶ Riattiva" : "⏹";
  stop.title = stop.ariaLabel = tel.fermo ? "Riattiva il telefono" : "Ferma subito il telefono";
  const n = s.approvazioni.length;
  $("badge-appr").hidden = $("pill-appr").hidden = !n;
  $("badge-appr").textContent = n;
  $("pill-appr").textContent = n + " da approvare";

  svuota($("team"), s.agenti.map((a) => h("button", { class: "card", type: "button", onclick: () => apriAgente(a) },
    h("div", { class: "riga-alto" }, h("span", { class: "icona", "aria-hidden": "true" }, ICONE_AGENTE[a.nome] || "🤖"),
      h("span", { class: "stato" + (a.attivo ? " attivo" : "") }, a.attivo ? "al lavoro" : "pronto")),
    h("b", null, a.titolo),
    a.in_corso ? h("small", { class: "cosa" }, a.in_corso.cosa) : h("small", null, a.descrizione),
    h("div", null,
      a.segnalazioni_aperte ? h("span", { class: "tag warn" }, a.segnalazioni_aperte + (a.segnalazioni_aperte === 1 ? " segnalazione " : " segnalazioni ")) : null,
      a.versioni ? h("span", { class: "tag ok" }, "v" + (a.versioni + 1)) : null))));

  svuota($("appr"), n ? s.approvazioni.map(cartaApprovazione) : h("div", { class: "vuoto" }, "Niente da approvare. Ti avviso io quando serve."));
  svuota($("migl"), s.miglioramenti.length ? s.miglioramenti.map(cartaMiglioramento) : h("div", { class: "vuoto" }, "Ancora nessun miglioramento: partirò quando emergono problemi."));
  svuota($("att"), s.attivita.length ? s.attivita.map((x) => h("div", { class: "voce" },
    h("span", null, h("b", null, nome(x.agente)), " · ", x.azione, x.dettaglio ? " — " + x.dettaglio : ""),
    h("span", { class: "meta" }, quando(x.ts)))) : h("div", { class: "vuoto" }, "Nessuna attività registrata."));
  disegnaSoldi(s.soldi);
  disegnaRoutine(s.routine || [], s.consumo);
  disegnaFatture(s.fatture || {});
  disegnaIdee(s.idee || []);
  disegnaAggiornamento(s.token_attivo, s.versione);
}

const STATO_IDEA = { proposta: ["in attesa del tuo ok", "warn"], approvata: ["approvata: da realizzare", "ok"],
  fatta: ["realizzata", "ok"], rifiutata: ["rifiutata", "bad"] };

function disegnaIdee(idee) {
  svuota($("idee"), idee.length ? idee.map((i) => {
    const [testo, colore] = STATO_IDEA[i.stato] || [i.stato, ""];
    const copia = async () => {
      try { await navigator.clipboard.writeText(i.brief); toast("Testo copiato: incollalo a chi sviluppa"); }
      catch (e) { toast("Non riesco a copiare: apri l'idea e selezionala a mano"); }
    };
    const fatta = async () => {
      try { await api(`/api/idee/${i.id}/fatta`, {}); toast("Segnata come realizzata"); aggiorna(); } catch (e) { toast(e.message); }
    };
    return h("div", { class: "voce" },
      h("div", null, h("span", { class: "tag " + colore }, testo)),
      h("b", null, i.titolo), h("span", null, i.descrizione),
      h("span", { class: "meta" }, `Perché: ${i.motivo} · ${quando(i.ts)}`),
      i.stato === "approvata" ? h("div", { class: "azioni ripiega" },
        h("button", { class: "secondario", type: "button", onclick: copia }, "Copia il testo per lo sviluppo"),
        h("button", { class: "secondario", type: "button", onclick: fatta }, "Fatta")) : null);
  }) : h("div", { class: "vuoto" }, "Ancora nessuna idea: ogni mattina Ada ne valuta una nuova."));
}

function disegnaAggiornamento(tokenAttivo, v) {
  v = v || {};
  $("versione").textContent = v.id && v.id !== "?" ? `Versione ${v.id} · ${v.data} · ${v.titolo}` : "Versione non leggibile.";
  $("btn-aggiorna").disabled = !tokenAttivo;
  $("agg-nota").textContent = tokenAttivo
    ? "Scarica l'ultima versione, la collauda e riavvia Ada; se i test falliscono torna da sola a quella di prima."
    : "Per aggiornare dall'app serve prima un token di accesso: vedi docs/AVVIO.md.";
}

$("btn-aggiorna").addEventListener("click", async (e) => {
  if (!confirm("Scarico l'ultima versione, la collaudo e riavvio Ada. Se i test falliscono torno alla versione di prima. Procedo?")) return;
  e.target.disabled = true; toast("Aggiorno… può volerci un minuto");
  try {
    const r = await api("/api/aggiorna", {});
    toast(r.messaggio);
    if (r.cambiato) setTimeout(() => location.reload(), 6000);  // il tempo di riavviarsi
  } catch (err) { toast(err.message); }
  finally { e.target.disabled = false; }
});

const STATO_FATTURA = { inviata: "Mandata a Giulia", fatturata: "Fatturata · attesa bonifico", incassata: "Bonifico arrivato" };
const soloHttps = (u) => typeof u === "string" && /^https:\/\//.test(u);

function disegnaFatture(f) {
  $("form-fatture").hidden = !!f.configurato || !f.token_attivo;
  $("fatt-archivio").hidden = !f.configurato;
  if (!f.configurato) {
    $("fatt-nota").textContent = f.token_attivo
      ? "Archivio non collegato. Incolla qui sotto l'indirizzo e il codice segreto dello script Google (in Contabilità Smart: Avvisi, Impostazioni)."
      : "Per collegare l'archivio dall'app serve prima un token di accesso: vedi docs/FATTURE.md.";
    svuota($("fatt-tessere")); svuota($("fatt-lista")); $("btn-sync-fatture").hidden = true;
    return;
  }
  $("btn-sync-fatture").hidden = false;
  const r = f.riepilogo;
  $("fatt-nota").textContent = r.fatture
    ? `Mese ${r.mese} · ${r.fatture} fatture · imponibile ${eur(r.imponibile)}` + (r.scadute ? ` · ${r.scadute} in ritardo` : "")
    : `Nessuna fattura nel mese ${r.mese}.`;
  svuota($("fatt-tessere"),
    [["Arrivato", r.incassato, "pos"], ["Da incassare", r.da_incassare, ""], ["Da accantonare", r.mancano, r.mancano > 0 ? "neg" : "pos"]]
      .map(([t, v, c]) => h("div", { class: "tessera" }, h("small", null, t), h("b", { class: "importo " + c }, eur(v)))));
  svuota($("fatt-lista"), f.elenco.length ? f.elenco.map((x) => {
    const stato = x.scaduta ? `Scaduta da ${x.giorni_scaduta} gg` : (STATO_FATTURA[x.stato] || x.stato);
    const incassata = x.stato === "incassata";
    const alterna = async () => {
      try { const j = await api("/api/fatture/" + encodeURIComponent(x.id), { incassata: !incassata }); toast(j.messaggio); aggiorna(); }
      catch (e) { toast(e.message); }
    };
    return h("div", { class: "voce" },
      h("div", null, h("span", { class: "tag " + (incassata ? "ok" : x.scaduta ? "bad" : "warn") }, stato)),
      h("div", { class: "riga" }, h("b", null, `Fattura ${x.numero || "senza numero"}`), h("span", { class: "importo" }, eur(x.calc.bonifico))),
      h("span", null, x.descrizione || ""),
      h("span", { class: "meta" }, `${x.data || ""} · imponibile ${eur(x.calc.lordo)}` + (x.dataIncasso ? ` · bonifico arrivato il ${x.dataIncasso}` : " · a destra il bonifico atteso")),
      x.daVerificare ? h("span", { class: "attenzione" }, "Da controllare: non tutti gli importi sono stati letti dal file Word.") : null,
      h("div", null, soloHttps(x.pdfUrl) ? h("a", { href: x.pdfUrl, target: "_blank", rel: "noopener" }, "PDF") : null,
        soloHttps(x.docxUrl) ? h("a", { href: x.docxUrl, target: "_blank", rel: "noopener" }, "File Word") : null),
      h("div", { class: "azioni" }, h("button", { class: "secondario", type: "button", onclick: alterna }, incassata ? "Annulla incasso" : "Segna incassata")));
  }) : h("div", { class: "vuoto" }, "L'archivio è vuoto: le fatture arrivano da sole quando mandi la mail a Giulia."));
}

$("form-fatture").addEventListener("submit", async (e) => {
  e.preventDefault();
  const url = $("fatt-url").value.trim(), token = $("fatt-token").value.trim();
  if (!url || !token) return;
  const btn = e.target.querySelector("button"); btn.disabled = true; toast("Provo il collegamento…");
  try {
    const j = await api("/api/impostazioni/fatture", { url, token });
    $("fatt-token").value = ""; $("fatt-url").value = "";
    toast(`Collegato: ${j.totale} fatture nell'archivio`); aggiorna();
  } catch (err) { toast(err.message); }
  finally { btn.disabled = false; }
});

$("seg-soldi").addEventListener("click", (e) => {
  const v = e.target.dataset?.s; if (!v) return;
  $("seg-soldi").querySelectorAll("button").forEach((b) => b.classList.toggle("on", b === e.target));
  $("soldi-conto").hidden = v !== "conto"; $("soldi-fatture").hidden = v !== "fatture";
});
$("btn-sync-fatture").addEventListener("click", async (e) => {
  e.target.disabled = true; toast("Aggiorno l'archivio…");
  try { const j = await api("/api/fatture/sincronizza", {}); toast(`Archivio: ${j.totale} fatture (${j.nuove} nuove). ${j.incassi}`.slice(0, 140)); aggiorna(); caricaChat(); }
  catch (err) { toast(err.message); }
  finally { e.target.disabled = false; }
});

const quandoRoutine = (r) => r.ora ? `ogni giorno alle ${r.ora}`
  : r.ogni_min % 60 === 0 ? `ogni ${r.ogni_min / 60} ${r.ogni_min === 60 ? "ora" : "ore"}` : `ogni ${r.ogni_min} minuti`;

function disegnaRoutine(routine, c) {
  const fmt = (n) => new Intl.NumberFormat("it-IT").format(n);
  $("consumo").textContent = c ? `Consumo di oggi: ${fmt(c.totale)} token in tutto (${c.chiamate} chiamate). Lavori automatici: ${fmt(c.automatici)} su un tetto di ${fmt(c.limite)}; la tua chat non lo consuma.` : "";
  svuota($("routine"), routine.map((r) => {
    const esegui = async (e) => {
      e.target.disabled = true; toast("Ada ci sta lavorando…");
      try { const x = await api(`/api/routine/${r.id}/esegui`, {}); toast(x.esito.slice(0, 120)); caricaChat(); }
      catch (err) { toast(err.message); }
      finally { e.target.disabled = false; aggiorna(); }
    };
    const alterna = async () => { try { await api("/api/routine/" + r.id, { attiva: !r.attiva }); aggiorna(); } catch (err) { toast(err.message); } };
    return h("div", { class: "voce" },
      h("div", null, h("span", { class: "tag " + (r.attiva ? "ok" : "") }, r.attiva ? "attiva" : "spenta"), " ",
        h("span", { class: "tag" }, quandoRoutine(r))),
      h("b", null, r.nome.replace(/_/g, " ")), h("span", null, r.descrizione),
      r.ultima ? h("span", { class: "meta" }, `Ultima: ${quando(r.ultima)} · ${r.esito || ""}`) : h("span", { class: "meta" }, "Mai eseguita"),
      h("div", { class: "azioni" },
        h("button", { class: "secondario", type: "button", onclick: esegui }, "Esegui ora"),
        h("button", { class: "secondario", type: "button", onclick: alterna }, r.attiva ? "Disattiva" : "Attiva")));
  }));
}

const stelle = (n) => (n == null ? "" : "★ " + String(n).replace(".", ","));
const migliaia = (n) => (n == null ? "" : new Intl.NumberFormat("it-IT").format(n) + " recensioni");

function cartaOpzione(o, i, scelta, azione) {
  const etic = { economica: "La più economica", meglio_recensita: "La meglio recensita", consigliata: "Consigliata" }[o.etichetta];
  return h("div", { class: "opz" + (scelta === i ? " scelta" : "") },
    etic ? h("div", null, h("span", { class: "tag ok" }, etic)) : null,
    h("b", null, o.nome),
    h("div", { class: "riga" }, h("span", { class: "prezzo" }, eur(o.prezzo_totale)),
      h("span", { class: "meta" }, [stelle(o.stelle), migliaia(o.recensioni)].filter(Boolean).join(" · "))),
    o.venditore ? h("span", { class: "meta" }, "Venduto da " + o.venditore) : null,
    o.motivo ? h("span", null, o.motivo) : null,
    azione ? h("div", { class: "azioni" }, azione) : null);
}

function cartaAcquisto(a) {
  const d = a.dettaglio || {}, opz = d.opzioni || [];
  const chiama = (path, dati, msg) => async () => {
    try { await api(path, dati); toast(msg); aggiorna(); } catch (e) { toast(e.message); }
  };
  const annulla = h("button", { class: "no-btn", type: "button", onclick: chiama(`/api/approvazioni/${a.id}/chiudi`, { esito: "annullato" }, "Acquisto annullato") }, "Annulla");
  let corpo;
  if (a.stato === "in_attesa") {
    corpo = [h("div", { class: "opzioni" }, opz.map((o, i) => cartaOpzione(o, i, null,
        h("button", { class: "ok-btn", type: "button", onclick: chiama("/api/approvazioni/" + a.id, { esito: "approva", opzione: i }, "Opzione scelta") }, "Scelgo questa")))),
      h("div", { class: "azioni" }, h("button", { class: "no-btn", type: "button", onclick: chiama("/api/approvazioni/" + a.id, { esito: "rifiuta" }, "Nessuna scelta") }, "Nessuna di queste"))];
  } else {
    const o = opz[d.scelta];
    corpo = [h("div", { class: "opzioni" }, o ? cartaOpzione(o, d.scelta, d.scelta) : null)];
    if (a.stato === "scelta") corpo.push(
      h("div", { class: "attenzione" }, "Se autorizzi, Ada porta l'ordine alla schermata finale e si ferma. L'ultimo tasto lo premi tu."),
      h("div", { class: "azioni" },
        h("button", { class: "ok-btn", type: "button", onclick: chiama(`/api/approvazioni/${a.id}/autorizza`, {}, "Autorizzato: Ada ci lavora") }, "Autorizza Ada a preparare l'ordine"), annulla));
    else if (a.stato === "autorizzata") corpo.push(h("div", { class: "lavoro" }, "Ada sta preparando l'ordine sul telefono…"), h("div", { class: "azioni" }, annulla));
    else if (a.stato === "pronto") corpo.push(
      h("div", { class: "attenzione" }, "Pronto: l'ordine è alla schermata finale sul telefono. Premi tu «Acquista ora». " + (d.nota || "")),
      h("div", { class: "azioni" },
        h("button", { class: "ok-btn", type: "button", onclick: chiama(`/api/approvazioni/${a.id}/chiudi`, { esito: "comprato" }, "Segnato come comprato") }, "Fatto, l'ho comprato"), annulla));
  }
  return h("div", { class: "voce" },
    h("div", null, h("span", { class: "tag warn" }, "Acquisto")), h("b", null, a.titolo), corpo,
    h("span", { class: "meta" }, quando(a.ts)));
}

function cartaApprovazione(a) {
  if (a.tipo === "acquisto") return cartaAcquisto(a);
  const d = a.dettaglio || {};
  const decidi = (esito) => async () => {
    try { await api("/api/approvazioni/" + a.id, { esito }); toast(esito === "approva" ? "Approvato" : "Rifiutato"); aggiorna(); }
    catch (e) { toast(e.message); }
  };
  return h("div", { class: "voce" },
    h("div", null, h("span", { class: "tag " + (a.tipo === "pagamento" ? "bad" : "warn") },
      { pagamento: "Soldi", prompt: "Modifica grande", idea: "Idea", incasso: "Incasso" }[a.tipo] || "Altro")),
    h("b", null, a.titolo),
    d.testo ? h("span", null, d.testo) : d.motivo ? h("span", null, d.motivo) : null,
    d.importo != null ? h("span", { class: "importo" }, eur(d.importo)) : null,
    h("span", { class: "meta" }, quando(a.ts)),
    h("div", { class: "azioni" },
      h("button", { class: "ok-btn", type: "button", onclick: decidi("approva") }, "Approva"),
      h("button", { class: "no-btn", type: "button", onclick: decidi("rifiuta") }, "Rifiuta")));
}

function cartaMiglioramento(m) {
  const colore = { applicato: "ok", annullato: "", rifiutato: "bad", in_attesa: "warn" }[m.stato] || "";
  const annulla = async () => {
    try { await api(`/api/miglioramenti/${m.id}/annulla`, {}); toast("Modifica annullata"); aggiorna(); }
    catch (e) { toast(e.message); }
  };
  return h("div", { class: "voce" },
    h("div", null, h("span", { class: "tag " + colore }, m.stato.replace("_", " ")), " ", h("span", { class: "tag" }, m.tipo)),
    h("b", null, nome(m.agente)), h("span", null, m.motivo), h("span", { class: "meta" }, quando(m.ts)),
    m.stato === "applicato" ? h("div", { class: "azioni" }, h("button", { class: "secondario", type: "button", onclick: annulla }, "Annulla modifica")) : null);
}

function disegnaSoldi(s) {
  $("soldi-periodo").textContent = s.movimenti
    ? `Mese ${s.periodo} · ${s.movimenti} movimenti letti dalle notifiche Revolut`
    : "Ancora nessun movimento: appena lo script legge le notifiche di Revolut compaiono qui.";
  svuota($("tessere"),
    [["Entrate", s.entrate, "pos"], ["Uscite", s.uscite, "neg"], ["Saldo", s.saldo, s.saldo >= 0 ? "pos" : "neg"]]
      .map(([t, v, c]) => h("div", { class: "tessera" }, h("small", null, t), h("b", { class: "importo " + c }, eur(v)))));
  const max = Math.max(1, ...s.per_categoria.map((c) => c.totale));
  svuota($("cat"), s.per_categoria.map((c) => {
    const i = h("i"); i.style.width = Math.round((c.totale / max) * 100) + "%";
    return h("div", { class: "barra-riga" }, h("div", null, h("span", null, c.nome), h("b", null, eur(c.totale))), h("div", { class: "traccia" }, i));
  }));
  svuota($("esercenti"), s.top_esercenti.map((e) => h("div", { class: "voce" }, h("span", null, e.nome), h("span", { class: "importo neg" }, eur(e.totale)))));
  svuota($("ultimi"), s.ultimi.map((m) => h("div", { class: "voce" },
    h("span", null, m.controparte || "(senza nome)", h("br"), h("span", { class: "meta" }, m.quando)),
    h("span", { class: "importo " + (m.importo < 0 ? "neg" : "pos") }, eur(m.importo)))));
}

$("btn-collega").addEventListener("click", async (e) => {
  const porta = prompt("Con il wifi acceso e il Debug wireless attivo, lascia vuoto per cercare la porta da solo, oppure scrivi la porta che vedi in Debug wireless (5 cifre)", "");
  if (porta === null) return;
  e.target.disabled = true; toast("Mi collego al telefono…");
  try { const r = await api("/api/telefono/collega", { porta: porta.trim() }); toast(r.messaggio); aggiorna(); }
  catch (err) { toast(err.message); }
  finally { e.target.disabled = false; }
});

$("btn-stop").addEventListener("click", async () => {
  const ferma = !$("btn-stop").classList.contains("riattiva");
  try { await api("/api/telefono", { fermo: ferma }); toast(ferma ? "Telefono fermato: Ada non tocca più nulla" : "Telefono riattivato"); aggiorna(); }
  catch (e) { toast(e.message); }
});

/* ---------- dettaglio agente ---------- */
const ICONE_AGENTE = { ada: "✨", contabilita_piva: "🧾", contabilita_privata: "💳", quotidiano: "🗓️", sviluppo: "🛠️",
  clienti_vendite: "🤝", acquisti: "🛒", revisore: "🔍" };
const NOMI_STRUMENTI = {
  riepilogo_spese: "Legge le spese", riepilogo_fatture: "Legge le fatture", annota_segnalazione: "Annota i problemi",
  richiedi_approvazione: "Chiede il tuo ok", telefono_collega: "Collega lo schermo", telefono_schermo: "Guarda lo schermo",
  telefono_tocca: "Tocca lo schermo", telefono_scrivi: "Scrive sullo schermo", telefono_scorri: "Scorre le pagine",
  telefono_vai: "Indietro e home", telefono_apri: "Apre app e pagine", proponi_acquisto: "Propone acquisti",
  acquisto_pronto: "Prepara l'ordine", delega: "Affida compiti al team", migliora_prompt: "Migliora i prompt",
  chiudi_segnalazione: "Chiude le segnalazioni", gestisci_routine: "Gestisce le routine", stato_sistema: "Controlla lo stato",
  fattura_incassata: "Segna le fatture incassate", proponi_idea: "Propone funzioni nuove", regola_categoria: "Impara le categorie di spesa",
};
const FRASI_ATTIVITA = {
  lavoro: "Ha ricevuto un compito", risposta: "Ha risposto", errore: "Ha avuto un errore", segnalazione: "Ha segnalato un problema",
  "prompt migliorato": "Ha migliorato un prompt", "richiesta approvazione": "Ha chiesto il tuo ok", "proposta acquisto": "Ha proposto un acquisto",
  "idea proposta": "Ha proposto una funzione nuova", "proposta modifica grande": "Ha proposto una modifica grande",
  "fattura archiviata": "Ha archiviato una fattura", "fattura incassata": "Ha segnato una fattura incassata",
  "regola categoria": "Ha imparato una categoria", "ordine pronto": "Ha preparato un ordine", routine: "Ha eseguito una routine",
  "routine creata": "Ha creato una routine", "routine modificata": "Ha modificato una routine",
};
const durata = (da) => { const s = Math.max(0, Math.floor(Date.now() / 1000 - da)); return s < 60 ? `${s} s` : `${Math.floor(s / 60)} min`; };

let agenteAperto = null, timerAgente = null;

function disegnaAgente(d) {
  const lavora = !!d.in_corso;
  $("ag-avatar").classList.toggle("lavora", lavora);
  $("ag-emoji").textContent = ICONE_AGENTE[d.nome] || "🤖";
  $("dlg-titolo").textContent = d.titolo; $("dlg-descr").textContent = d.descrizione;
  const ora = $("ag-ora"); ora.classList.toggle("lavora", lavora);
  const ultima = d.attivita[0];
  svuota(ora,
    h("b", null, lavora ? "Sta lavorando adesso" : "Adesso"),
    lavora
      ? [h("span", null, d.in_corso.cosa), h("small", { class: "meta puntini" }, `da ${durata(d.in_corso.da)}`)]
      : [h("span", null, "In attesa di un compito."), ultima ? h("small", { class: "meta" }, `Ultima attività: ${quando(ultima.ts)}`) : null]);
  svuota($("ag-storia"), d.attivita.length ? d.attivita.map((a) =>
    h("div", { class: "fatto" + (a.azione === "errore" ? " errore" : "") },
      (FRASI_ATTIVITA[a.azione] || a.azione) + (a.dettaglio ? `: ${a.dettaglio}` : ""),
      h("small", null, quando(a.ts)))) : h("div", { class: "meta fatto" }, "Ancora nessuna attività."));
  svuota($("ag-strumenti"), d.strumenti.map((t) => h("span", { class: "tag" }, NOMI_STRUMENTI[t] || t)));
  $("ag-segn").hidden = !d.segnalazioni.length;
  svuota($("ag-segn-lista"), d.segnalazioni.map((x) => h("div", { class: "voce" }, h("span", null, x.problema), h("span", { class: "meta" }, quando(x.ts)))));
  $("dlg-prompt").textContent = d.prompt;
  svuota($("dlg-migl"), d.miglioramenti.map((m) => h("div", { class: "voce" }, h("span", null, m.motivo), h("span", { class: "tag" }, m.stato.replace("_", " ")))));
}

async function ricaricaAgente() {
  if (!agenteAperto) return;
  try { disegnaAgente(await api("/api/agenti/" + agenteAperto)); } catch (e) { /* si riprova al prossimo giro */ }
}

async function apriAgente(a) {
  agenteAperto = a.nome;
  disegnaAgente({ nome: a.nome, titolo: a.titolo, descrizione: a.descrizione, in_corso: a.in_corso, attivita: [], strumenti: [],
                  segnalazioni: [], prompt: "Carico…", miglioramenti: [] });
  $("dlg").showModal();
  await ricaricaAgente();
  clearInterval(timerAgente);
  timerAgente = setInterval(ricaricaAgente, 3000);  // il popup resta vivo mentre è aperto
}
$("dlg").addEventListener("close", () => { clearInterval(timerAgente); agenteAperto = null; });

$("form-feedback").addEventListener("submit", async (e) => {
  e.preventDefault();
  const testo = $("fb-testo").value.trim();
  if (!testo || !agenteAperto) return;
  try { await api("/api/feedback", { agente: agenteAperto, testo }); $("fb-testo").value = ""; $("dlg").close(); toast("Segnalato. Ada se ne occupa."); aggiorna(); }
  catch (err) { toast(err.message); }
});

$("btn-ciclo").addEventListener("click", async (e) => {
  e.target.disabled = true; $("orb").classList.add("pensa"); toast("Ada sta rivedendo il team…");
  try { const r = await api("/api/ciclo", {}); toast(r.risposta.slice(0, 120)); caricaChat(); }
  catch (err) { toast(err.message); }
  finally { e.target.disabled = false; $("orb").classList.remove("pensa"); aggiorna(); }
});

async function aggiorna() {
  try { disegna(await api("/api/stato")); }
  catch (e) { $("stato-ada").textContent = "Non riesco a raggiungere Ada"; }
}

caricaChat().catch(() => {});
aggiorna();
setInterval(() => { if (!document.hidden) aggiorna(); }, 20000);
