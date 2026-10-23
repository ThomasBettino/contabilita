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
const svuota = (el, ...nuovi) => el.replaceChildren(...nuovi.flat());

function leggiToken() { try { return localStorage.getItem("ada_token") || ""; } catch (e) { return ""; } }
function salvaToken(t) { try { localStorage.setItem("ada_token", t); } catch (e) { /* storage bloccato */ } }

async function api(path, dati) {
  const intest = { Authorization: "Bearer " + leggiToken() };
  const opz = { headers: intest };
  if (dati !== undefined) { opz.method = "POST"; opz.headers["Content-Type"] = "application/json"; opz.body = JSON.stringify(dati); }
  let r = await fetch(path, opz);
  if (r.status === 401) {
    const t = prompt("Inserisci il token di accesso di Ada");
    if (!t) throw new Error("Accesso negato");
    salvaToken(t); intest.Authorization = "Bearer " + t;
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
function bolla(ruolo, testo, extra) { return h("div", { class: "msg " + ruolo + (extra ? " " + extra : "") }, testo); }

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
  try {
    const { risposta } = await api("/api/chat", { messaggio: testo });
    pensa.className = "msg ada"; pensa.textContent = risposta;
  } catch (e) {
    pensa.className = "msg ada"; pensa.textContent = "Non riesco a rispondere: " + e.message;
  } finally {
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
    : s.segnalazioni_aperte ? `${s.segnalazioni_aperte} problemi da sistemare`
    : "Tutto sotto controllo" + ((s.telefono || {}).collegato ? "" : " · schermo non collegato");
  const tel = s.telefono || {};
  const stop = $("btn-stop");
  stop.hidden = !tel.collegato;
  $("btn-collega").hidden = !!tel.collegato;
  stop.className = "stop" + (tel.fermo ? " riattiva" : "");
  stop.textContent = tel.fermo ? "▶" : "⏹";
  stop.title = stop.ariaLabel = tel.fermo ? "Riattiva il telefono" : "Ferma subito il telefono";
  const n = s.approvazioni.length;
  $("badge-appr").hidden = $("pill-appr").hidden = !n;
  $("badge-appr").textContent = n;
  $("pill-appr").textContent = n + " da approvare";

  svuota($("team"), s.agenti.map((a) => h("button", { class: "card", type: "button", onclick: () => apriAgente(a) },
    h("span", { class: "stato" + (a.attivo ? " attivo" : "") }, a.attivo ? "al lavoro" : "pronto"),
    h("b", null, a.titolo), h("small", null, a.descrizione),
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
}

const STATO_FATTURA = { inviata: "Mandata a Giulia", fatturata: "Fatturata · attesa bonifico", incassata: "Bonifico arrivato" };
const soloHttps = (u) => typeof u === "string" && /^https:\/\//.test(u);

function disegnaFatture(f) {
  if (!f.configurato) {
    $("fatt-nota").textContent = "Archivio non collegato. Serve l'indirizzo e il codice dello script Google: vedi docs/FATTURE.md.";
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
  $("consumo").textContent = c ? `Consumo di oggi: ${fmt(c.totale)} di ${fmt(c.limite)} token per i lavori automatici (${c.chiamate} chiamate).` : "";
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
    h("div", null, h("span", { class: "tag " + (a.tipo === "pagamento" ? "bad" : "warn") }, a.tipo === "pagamento" ? "Soldi" : a.tipo === "prompt" ? "Modifica grande" : "Altro")),
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
let agenteAperto = null;
async function apriAgente(a) {
  agenteAperto = a.nome;
  $("dlg-titolo").textContent = a.titolo; $("dlg-descr").textContent = a.descrizione;
  $("dlg-prompt").textContent = "Carico…"; svuota($("dlg-migl"));
  $("dlg").showModal();
  try {
    const d = await api("/api/agenti/" + a.nome);
    $("dlg-prompt").textContent = d.prompt;
    svuota($("dlg-migl"), d.miglioramenti.map((m) => h("div", { class: "voce" },
      h("span", null, m.motivo), h("span", { class: "tag" }, m.stato))));
  } catch (e) { $("dlg-prompt").textContent = e.message; }
}
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
