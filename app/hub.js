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
    else if (v === false || v == null) continue;  // attributo booleano spento: non va scritto (disabled="false" disabiliterebbe)
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const f of figli.flat()) if (f != null) el.append(f.nodeType ? f : document.createTextNode(String(f)));
  return el;
}
const svuota = (el, ...nuovi) => el.replaceChildren(...nuovi.flat(Infinity).filter((x) => x != null && x !== false));

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
/* Sotto la risposta: cosa ha fatto Ada per arrivarci, così si vede che ha lavorato. */
function blocchiAzioni(azioni) {
  if (!azioni || !azioni.length) return null;
  return h("div", { class: "fatto-tool" }, azioni.map((a) => h("span", { class: "riga-tool" }, "✓ ",
    h("b", null, NOMI_STRUMENTI[a.nome] || a.nome), a.esito ? " — " + a.esito.split("\n")[0].slice(0, 110) : "")));
}
function bolla(ruolo, testo, extra, azioni) {
  return h("div", { class: "msg " + ruolo + (extra ? " " + extra : "") },
    ruolo === "ada" && !extra ? testoRicco(testo) : testo, blocchiAzioni(azioni));
}

async function caricaChat() {
  const { messaggi } = await api("/api/chat");
  svuota($("msgs"), messaggi.length
    ? messaggi.map((m) => bolla(m.ruolo, m.testo, null, m.azioni))
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
    const { risposta, azioni } = await api("/api/chat", { messaggio: testo });
    pensa.className = "msg ada"; pensa.replaceChildren(testoRicco(risposta), blocchiAzioni(azioni));
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

/* ---------- schede del registro ---------- */
const SCHEDE_REGISTRO = ["lavoro", "routine", "prove", "idee", "modifiche", "storico"];
function mostraRegistro(scheda, ricorda = true) {
  if (!SCHEDE_REGISTRO.includes(scheda)) scheda = "lavoro";
  SCHEDE_REGISTRO.forEach((n) => { $("reg-" + n).hidden = n !== scheda; });
  document.querySelectorAll("#seg-registro button").forEach((b) => {
    b.classList.toggle("on", b.dataset.r === scheda); b.setAttribute("aria-selected", String(b.dataset.r === scheda));
  });
  $("v-registro").scrollTop = 0;
  if (ricorda) { try { localStorage.setItem("ada_registro", scheda); } catch (e) { /* storage bloccato */ } }
}
$("seg-registro").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) mostraRegistro(b.dataset.r); });
try { mostraRegistro(localStorage.getItem("ada_registro") || "lavoro", false); } catch (e) { mostraRegistro("lavoro", false); }

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
  disegnaModifiche(s.miglioramenti);
  disegnaStorico(s.attivita);
  tokenAttivo = !!s.token_attivo;
  disegnaSoldi(s.soldi);
  disegnaMovimentiNote();
  caricaMovimenti();
  const nAg = ((s.agenda || {}).scaduti || 0) + ((s.vendite || {}).in_coda || 0);
  $("badge-agenda").hidden = !nAg; $("badge-agenda").textContent = nAg;
  caricaAgenda(); caricaVendite();
  $("soldi-lettura").textContent = s.lettura || "";
  disegnaRitmo(s.ritmo || {}, s.token_attivo);
  disegnaCollaudi(s.collaudi || []);
  disegnaStudio(s.appunti || [], s.libri || []);
  disegnaRoutine(s.routine || [], s.consumo);
  for (const [nome, prefisso] of [["collaudo", "Prossimo collaudo"], ["studio", "Prossimo studio"], ["lettura", "Prossima lettura"]]) {
    impostaTimer($("timer-" + nome), (s.routine || []).find((r) => r.nome === nome), prefisso);
  }
  ticTimer();
  disegnaFatture(s.fatture || {});
  disegnaIdee(s.idee || []);
  disegnaAggiornamento(s.token_attivo, s.versione);
}

const STATO_IDEA = { proposta: ["in attesa del tuo ok", "warn"], approvata: ["approvata: da realizzare", "ok"],
  fatta: ["realizzata", "ok"], rifiutata: ["rifiutata", "bad"] };

function cartaIdea(i) {
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
}

/* Un gruppo di schede con titolo e conteggio; chiuso = ripiegato in un «dettagli». */
function gruppo(titolo, elementi, schede, chiuso) {
  if (!elementi.length) return null;
  const lista = h("div", { class: "lista" }, elementi.map(schede));
  const testa = `${titolo} (${elementi.length})`;
  return chiuso ? h("details", { class: "gruppo" }, h("summary", null, testa), lista) : h("div", { class: "blocco" }, h("h3", null, testa), lista);
}

function disegnaIdee(idee) {
  const di = (stati) => idee.filter((i) => stati.includes(i.stato));
  const attesa = di(["proposta"]).length;
  $("num-idee").hidden = !attesa; $("num-idee").textContent = attesa;
  svuota($("idee"), idee.length ? [
    gruppo("Da decidere", di(["proposta"]), cartaIdea),
    gruppo("Da realizzare", di(["approvata"]), cartaIdea),
    gruppo("Già chiuse", di(["fatta", "rifiutata"]), cartaIdea, true)]
    : h("div", { class: "vuoto" }, "Ancora nessuna idea: ogni mattina Ada ne valuta una nuova."));
}

function disegnaModifiche(migl) {
  const di = (stati) => migl.filter((m) => stati.includes(m.stato));
  svuota($("migl"), migl.length ? [
    gruppo("In attesa del tuo ok", di(["in_attesa"]), cartaMiglioramento),
    gruppo("Attive: si possono annullare", di(["applicato"]), cartaMiglioramento),
    gruppo("Annullate o rifiutate", di(["annullato", "rifiutato"]), cartaMiglioramento, true)]
    : h("div", { class: "vuoto" }, "Ancora nessuna modifica: Ada interviene quando emergono problemi."));
}

function disegnaStorico(attivita) {
  svuota($("att"), attivita.length ? attivita.map((x) => h("div", { class: "voce" },
    h("span", null, h("b", null, nome(x.agente)), " · ", (FRASI_ATTIVITA[x.azione] || x.azione), x.dettaglio ? " — " + x.dettaglio : ""),
    h("span", { class: "meta" }, quando(x.ts)))) : h("div", { class: "vuoto" }, "Nessuna attività registrata."));
}

function disegnaAggiornamento(tokenAttivo, v) {
  v = v || {};
  $("versione").textContent = v.id && v.id !== "?" ? `Versione ${v.id} · ${v.data} · ${v.titolo}` : "Versione non leggibile.";
  $("btn-aggiorna").disabled = !tokenAttivo;
  $("agg-nota").textContent = tokenAttivo
    ? "Scarica l'ultima versione, la collauda e riavvia Ada; se i test falliscono torna da sola a quella di prima."
    : "Per aggiornare dall'app serve prima un token di accesso: in Termux scrivi «sh scripts/token.sh» (vedi docs/AVVIO.md).";
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
      : "Per collegare l'archivio dall'app serve prima un token di accesso: in Termux scrivi «sh scripts/token.sh» (vedi docs/FATTURE.md).";
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

function disegnaRitmo(r, tokenAttivo) {
  const opzioni = r.opzioni || {};
  svuota($("ritmo"), Object.entries(opzioni).map(([k, o]) => h("button", {
    type: "button", role: "tab", class: k === r.scelto ? "on" : "", "aria-selected": String(k === r.scelto), disabled: !tokenAttivo,
    onclick: async () => {
      if (k === r.scelto) return;
      if (k === "intenso" && !confirm("Il ritmo intenso usa molti token: Ada lavora di continuo e il tetto giornaliero sale a 5 volte. Lo attivo?")) return;
      try { await api("/api/ritmo", { ritmo: k }); toast("Ritmo: " + o.etichetta); aggiorna(); } catch (e) { toast(e.message); }
    } }, o.etichetta)));
  const scelto = opzioni[r.scelto];
  $("ritmo-nota").textContent = !Object.keys(opzioni).length ? "Ada gira ancora con la versione vecchia: riavviala per vedere i ritmi (vedi docs/AVVIO.md, «Se il telefono si spegne o si riavvia»)."
    : !tokenAttivo ? "Per cambiare il ritmo serve prima un token di accesso: in Termux scrivi «sh scripts/token.sh» (vedi docs/AVVIO.md)."
    : scelto ? scelto.descrizione : "";
}

function disegnaCollaudi(collaudi) {
  svuota($("collaudi"), collaudi.length ? collaudi.map((c) => {
    const colore = c.voto >= 8 ? "ok" : c.voto >= 6 ? "warn" : "bad";
    return h("div", { class: "voce" },
      h("div", null, h("span", { class: "tag " + colore }, `${c.voto}/10`), " ", h("span", { class: "tag" }, c.categoria)),
      h("span", null, "«" + c.richiesta + "»"),
      c.problemi.length ? h("ul", { class: "elenco" }, c.problemi.map((p) => h("li", null, p))) : h("span", { class: "meta" }, "Nessun problema trovato."),
      h("details", null, h("summary", null, "Mostra il dialogo"), h("pre", { class: "trascrizione" }, c.trascrizione)),
      h("span", { class: "meta" }, quando(c.ts)));
  }) : h("div", { class: "vuoto" }, "Ancora nessun collaudo: il primo parte da solo, oppure usa «Esegui ora» sulla routine."));
}

function disegnaStudio(appunti, libri) {
  $("libri-nota").textContent = libri.length
    ? "Libri in lettura: " + libri.map((l) => `${l.nome} (${l.percentuale}%)`).join(" · ")
    : "Nessun libro: copia file .txt, .md o .epub nella cartella ~/ada/libri e Ada li legge a pezzi. Le lezioni sono la sua conoscenza, non citazioni dai libri.";
  svuota($("appunti"), appunti.length ? appunti.map((a) => h("div", { class: "voce" },
    h("div", null, h("span", { class: "tag" }, a.tipo)),
    h("b", null, a.titolo),
    h("details", null, h("summary", null, "Leggi gli appunti"), h("pre", { class: "trascrizione" }, a.testo)),
    h("span", { class: "meta" }, quando(a.ts))))
    : h("div", { class: "vuoto" }, "Ancora nessun appunto."));
}

/* ---------- timer tra un lavoro e l'altro ---------- */
const due = (n) => String(n).padStart(2, "0");
const tra = (s) => s >= 3600 ? `${Math.floor(s / 3600)} h ${due(Math.floor(s % 3600 / 60))} min`
  : s >= 600 ? `${Math.floor(s / 60)} min`
  : s >= 60 ? `${Math.floor(s / 60)} min ${due(s % 60)} s` : `${s} s`;
function oraDi(ts) {
  const d = new Date(ts * 1000), oggi = new Date().toDateString() === d.toDateString();
  return d.toLocaleString("it-IT", oggi ? { hour: "2-digit", minute: "2-digit" } : { weekday: "short", hour: "2-digit", minute: "2-digit" });
}
function impostaTimer(el, r, prefisso) {
  if (!el) return;
  if (r && r.attiva) {
    el.dataset.prossima = r.prossima; el.dataset.durata = r.ogni_min ? r.ogni_min * 60 : 86400; el.dataset.prefisso = prefisso;
  } else {
    delete el.dataset.prossima;
    const testo = el.querySelector(".timer-testo") || el;
    testo.textContent = r ? `${prefisso}: in pausa.` : "";
  }
}
function ticTimer() {
  const adesso = Date.now() / 1000;
  document.querySelectorAll("[data-prossima]").forEach((el) => {
    const prossima = +el.dataset.prossima, resta = Math.max(0, Math.floor(prossima - adesso));
    (el.querySelector(".timer-testo") || el).textContent = resta
      ? `${el.dataset.prefisso}: tra ${tra(resta)} (${oraDi(prossima)})` : `${el.dataset.prefisso}: sta per partire…`;
    const barra = el.querySelector(".timer-barra span");
    if (barra) barra.style.width = Math.min(100, Math.max(0, 100 * (1 - resta / +el.dataset.durata))) + "%";
  });
}
setInterval(() => { if (!document.hidden) ticTimer(); }, 1000);

const quandoRoutine = (r) => r.ora ? `ogni giorno alle ${r.ora}`
  : r.ogni_min % 60 === 0 ? `ogni ${r.ogni_min / 60} ${r.ogni_min === 60 ? "ora" : "ore"}` : `ogni ${r.ogni_min} minuti`;

function timerRoutine(r) {
  const el = h("div", { class: "timer" }, h("span", { class: "timer-testo meta" }), h("div", { class: "timer-barra" }, h("span")));
  impostaTimer(el, r, "Prossima esecuzione");
  return el;
}

const ETICHETTE_ROUTINE = {
  notifiche: "Lettura notifiche Revolut", fatture: "Archivio fatture e bonifici", miglioria_quotidiana: "Miglioria del giorno",
  miglioramento: "Correzione dei prompt", collaudo: "Collaudo di Ada", studio: "Studio dei grandi pensatori", lettura: "Lettura dei tuoi libri",
  riepilogo_sera: "Riepilogo della sera", promemoria_approvazioni: "Promemoria delle approvazioni",
  agenda: "Avvisi dell'agenda", agenda_mattina: "Agenda del mattino",
};
const GRUPPI_ROUTINE = [
  ["Soldi", ["notifiche", "fatture"]],
  ["Agenda", ["agenda", "agenda_mattina"]],
  ["Ada che migliora sé stessa", ["miglioria_quotidiana", "miglioramento", "collaudo", "studio", "lettura"]],
  ["Riepiloghi e promemoria", ["riepilogo_sera", "promemoria_approvazioni"]],
];

function cartaRoutine(r) {
  const esegui = async (e) => {
    e.target.disabled = true; toast("Ada ci sta lavorando…");
    try { const x = await api(`/api/routine/${r.id}/esegui`, {}); toast(x.esito.slice(0, 120)); caricaChat(); }
    catch (err) { toast(err.message); }
    finally { e.target.disabled = false; aggiorna(); }
  };
  const alterna = async () => { try { await api("/api/routine/" + r.id, { attiva: !r.attiva }); aggiorna(); } catch (err) { toast(err.message); } };
  return h("div", { class: "voce" },
    h("div", { class: "riga" }, h("b", null, ETICHETTE_ROUTINE[r.nome] || r.nome.replace(/_/g, " ")),
      h("span", null, h("span", { class: "tag " + (r.attiva ? "ok" : "") }, r.attiva ? "attiva" : "spenta"), " ", h("span", { class: "tag" }, quandoRoutine(r)))),
    h("span", { class: "meta" }, r.descrizione),
    timerRoutine(r),
    r.ultima ? h("span", { class: "meta" }, `Ultima: ${quando(r.ultima)} · ${r.esito || ""}`) : h("span", { class: "meta" }, "Mai eseguita"),
    h("div", { class: "azioni" },
      h("button", { class: "secondario", type: "button", onclick: esegui }, "Esegui ora"),
      h("button", { class: "secondario", type: "button", onclick: alterna }, r.attiva ? "Disattiva" : "Attiva")));
}

function disegnaRoutine(routine, c) {
  const fmt = (n) => new Intl.NumberFormat("it-IT").format(n);
  const perc = c && c.limite ? Math.min(100, Math.round(100 * c.automatici / c.limite)) : 0;
  const barra = h("i"); barra.style.width = perc + "%";
  svuota($("consumo"), c ? [
    h("div", { class: "riga" }, h("span", null, "Lavori automatici"), h("b", null, `${fmt(c.automatici)} / ${fmt(c.limite)} token`)),
    h("div", { class: "traccia" }, barra),
    h("span", { class: "meta" }, `Con la tua chat oggi: ${fmt(c.totale)} token in ${c.chiamate} chiamate. La chat non ha tetto e non lo consuma.`)] : null);
  const usate = new Set(GRUPPI_ROUTINE.flatMap(([, nomi]) => nomi));
  const gruppi = [...GRUPPI_ROUTINE.map(([titolo, nomi]) => [titolo, routine.filter((r) => nomi.includes(r.nome))]),
    ["Create da Ada", routine.filter((r) => !usate.has(r.nome))]];
  svuota($("routine"), gruppi.map(([titolo, elenco]) => gruppo(titolo, elenco, cartaRoutine)));
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
}

/* ---------- movimenti a mano ed estratto conto ---------- */
let tokenAttivo = false;
const due2 = (n) => String(n).padStart(2, "0");
const meseDi = (d) => `${d.getFullYear()}-${due2(d.getMonth() + 1)}`;
const oggiLocale = () => { const d = new Date(); return `${meseDi(d)}-${due2(d.getDate())}`; };
let meseMov = meseDi(new Date());
const ORIGINI = { notifica: "da notifica", manuale: "a mano", estratto: "da estratto" };
const breve = (q) => { const m = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}:\d{2})/.exec(q); return m ? `${m[3]}/${m[2]} ${m[4]}` : q; };
const giorno = (iso) => iso.split("-").reverse().slice(0, 2).join("/") + "/" + iso.slice(2, 4);

function preparaMovimenti() {
  const mesi = Array.from({ length: 12 }, (_, i) => { const d = new Date(); d.setDate(1); d.setMonth(d.getMonth() - i); return d; });
  svuota($("mov-mese"), mesi.map((d) => h("option", { value: meseDi(d), selected: meseDi(d) === meseMov },
    d.toLocaleString("it-IT", { month: "long", year: "numeric" }))));
  $("mov-data").value = $("mov-data").max = oggiLocale();
}
preparaMovimenti();

function rigaMovimento(m) {
  const riga = h("div", { class: "voce movimento" },
    h("div", { class: "riga" },
      h("span", null, m.controparte || "(senza nome)", h("br"), h("span", { class: "meta" }, `${breve(m.quando)} · ${ORIGINI[m.origine] || m.origine}`)),
      h("span", { class: "importo " + (m.importo < 0 ? "neg" : "pos") }, eur(m.importo))),
    h("button", { class: "x", type: "button", disabled: !tokenAttivo, title: "Togli questo movimento", "aria-label": "Togli " + (m.controparte || "movimento"),
      onclick: async () => {
        if (!confirm(`Tolgo «${m.controparte || "senza nome"}» di ${eur(m.importo)}?`)) return;
        try { await api("/api/movimenti/rimuovi", { chiave: m.chiave }); riga.remove(); toast("Movimento tolto"); caricaMovimenti(); aggiorna(); }
        catch (e) { toast(e.message); }
      } }, "✕"));
  return riga;
}

async function caricaMovimenti() {
  try {
    const j = await api("/api/movimenti?mese=" + meseMov);
    svuota($("movimenti"), j.movimenti.length ? j.movimenti.map(rigaMovimento) : h("div", { class: "vuoto" }, "Nessun movimento in questo mese."));
  } catch (e) { /* lo stato in alto già dice che Ada non risponde */ }
}

function disegnaMovimentiNote() {
  $("mov-nota").textContent = tokenAttivo
    ? "Ada legge solo le notifiche di Revolut: qui puoi aggiungere un pagamento che manca o togliere uno sbagliato."
    : "Per aggiungere o togliere movimenti serve prima il token di accesso: in Termux scrivi «sh scripts/token.sh» (vedi docs/AVVIO.md).";
  $("estratto-nota").textContent = tokenAttivo
    ? "Carica l'estratto in CSV (in Revolut: Conti, tre puntini, Estratto, formato Excel o CSV). Ada aggiunge ciò che manca e ti mostra ciò che ha nel conto ma non trova nell'estratto: così i conti tornano. I PDF non si leggono."
    : "Per caricare un estratto serve prima il token di accesso (vedi sopra).";
  $("btn-mov-nuovo").disabled = $("btn-estratto").disabled = !tokenAttivo;
  if (!tokenAttivo) $("form-mov").hidden = true;
}

$("mov-mese").addEventListener("change", (e) => { meseMov = e.target.value; caricaMovimenti(); });
$("btn-mov-nuovo").addEventListener("click", () => { $("form-mov").hidden = !$("form-mov").hidden; if (!$("form-mov").hidden) $("mov-importo").focus(); });
$("mov-tipo").addEventListener("click", (e) => {
  if (!e.target.dataset.t) return;
  $("mov-tipo").querySelectorAll("button").forEach((b) => b.classList.toggle("on", b === e.target));
});
$("form-mov").addEventListener("submit", async (e) => {
  e.preventDefault();
  const tipo = $("mov-tipo").querySelector("button.on").dataset.t;
  try {
    await api("/api/movimenti", { tipo, importo: $("mov-importo").value, controparte: $("mov-desc").value, data: $("mov-data").value });
    toast(tipo === "uscita" ? "Uscita aggiunta" : "Entrata aggiunta");
    $("mov-importo").value = $("mov-desc").value = ""; $("form-mov").hidden = true;
    if ($("mov-data").value.slice(0, 7) !== meseMov) { meseMov = $("mov-data").value.slice(0, 7); preparaMovimenti(); }
    caricaMovimenti(); aggiorna();
  } catch (err) { toast(err.message); }
});

function mostraEsitoEstratto(r) {
  const ignorate = Object.entries(r.ignorate).map(([motivo, n]) => `${n} ${motivo}`).join(", ");
  svuota($("estratto-esito"),
    h("div", { class: "voce" },
      h("div", null, h("span", { class: "tag ok" }, "Estratto letto")),
      h("b", null, `Dal ${giorno(r.periodo[0])} al ${giorno(r.periodo[1])}: ${r.righe} movimenti`),
      h("span", null, `${r.presenti} c'erano già, ${r.nuovi} aggiunti.` + (ignorate ? ` Non importati: ${ignorate}.` : "")),
      h("span", { class: "meta" }, "I movimenti aggiunti dall'estratto non fanno scattare avvisi né cambiano le fatture da incassare.")),
    r.totale_da_controllare
      ? [h("h3", null, `Da controllare (${r.totale_da_controllare})`),
         h("p", { class: "nota" }, "Sono nel conto di Ada ma nell'estratto, in quel periodo, non ci sono: possono essere doppioni o pagamenti ancora in sospeso. Togli quelli sbagliati."),
         h("div", { class: "lista compatta" }, r.da_controllare.map(rigaMovimento))]
      : h("p", { class: "nota" }, "Tutto torna: ogni movimento del periodo è anche nell'estratto."));
}

$("btn-estratto").addEventListener("click", () => $("estratto-file").click());
$("estratto-file").addEventListener("change", async (e) => {
  const f = e.target.files[0]; e.target.value = "";
  if (!f) return;
  if (f.size > 2500000) { toast("Il file è troppo grande: carica un periodo più corto."); return; }
  toast("Leggo l'estratto…");
  try {
    const buf = await f.arrayBuffer();
    let testo;
    try { testo = new TextDecoder("utf-8", { fatal: true }).decode(buf); } catch (x) { testo = new TextDecoder("windows-1252").decode(buf); }
    mostraEsitoEstratto(await api("/api/estratto", { nome: f.name, testo }));
    caricaMovimenti(); aggiorna();
  } catch (err) {
    svuota($("estratto-esito"), h("div", { class: "voce" }, h("div", null, h("span", { class: "tag bad" }, "Non riuscito")), h("span", null, err.message)));
  }
});

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

/* ---------- agenda e reparto vendite ---------- */
const GIORNI_IT = ["domenica", "lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato"];
function etichettaGiorno(iso, oggi) {
  const d = new Date(iso + "T12:00:00"), delta = Math.round((d - new Date(oggi + "T12:00:00")) / 864e5);
  return (delta === 0 ? "Oggi" : delta === 1 ? "Domani" : delta === -1 ? "Ieri" : GIORNI_IT[d.getDay()]) + ` ${d.getDate()}/${d.getMonth() + 1}`;
}
const piuGiorni = (iso, n) => { const d = new Date(iso + "T12:00:00"); d.setDate(d.getDate() + n); return `${d.getFullYear()}-${due2(d.getMonth() + 1)}-${due2(d.getDate())}`; };

function cartaVoce(v, oggi) {
  const agisci = (azione, extra, msg) => async () => {
    try { await api("/api/agenda/" + v.id, { azione, ...extra }); if (msg) toast(msg); caricaAgenda(); aggiorna(); }
    catch (e) { toast(e.message); }
  };
  const scaduta = v.giorno < oggi;
  return h("div", { class: "voce agenda" + (v.stato === "fatto" ? " fatta" : "") },
    h("div", { class: "riga" },
      h("span", null, h("b", { class: "ora" }, v.ora || "tutto il giorno"), " ", h("b", null, v.titolo)),
      h("span", null, h("span", { class: "tag " + (v.tipo === "evento" ? "ok" : "") }, v.tipo === "evento" ? "appuntamento" : "promemoria"),
        v.ripeti ? [" ", h("span", { class: "tag" }, v.ripeti)] : null)),
    v.note ? h("span", { class: "meta" }, v.note) : null,
    v.preavviso ? h("span", { class: "meta" }, `Avviso ${v.preavviso >= 1440 ? v.preavviso / 1440 + " giorno" : v.preavviso >= 60 ? v.preavviso / 60 + " ora" : v.preavviso + " minuti"} prima`) : null,
    v.stato === "fatto" ? null : h("div", { class: "azioni ripiega" },
      h("button", { class: "secondario", type: "button", onclick: agisci("fatto", {}, "Fatto") }, "✓ Fatto"),
      h("button", { class: "secondario", type: "button", onclick: agisci("sposta", { quando: piuGiorni(scaduta ? oggi : v.giorno, 1) + (v.ora ? " " + v.ora : "") }, "Spostato a domani") }, "Domani"),
      h("button", { class: "secondario", type: "button", onclick: () => { if (confirm(`Tolgo «${v.titolo}» dall'agenda?`)) agisci("elimina", {}, "Tolto")(); } }, "Elimina")));
}

async function caricaAgenda() {
  try {
    const j = await api("/api/agenda?giorni=30");
    const giorni = {};
    j.prossimi.forEach((v) => (giorni[v.giorno] ||= []).push(v));
    svuota($("agenda-lista"),
      j.scaduti.length ? h("div", { class: "blocco" }, h("h3", null, `Da chiudere o spostare (${j.scaduti.length})`),
        h("div", { class: "lista" }, j.scaduti.map((v) => cartaVoce(v, j.oggi)))) : null,
      Object.keys(giorni).sort().map((g) => h("div", { class: "blocco" }, h("h3", null, etichettaGiorno(g, j.oggi)),
        h("div", { class: "lista" }, giorni[g].map((v) => cartaVoce(v, j.oggi))))),
      !j.scaduti.length && !j.prossimi.length ? h("div", { class: "vuoto" }, "Niente in agenda nei prossimi 30 giorni.") : null,
      j.fatti.length ? h("details", { class: "gruppo" }, h("summary", null, `Fatti di recente (${j.fatti.length})`),
        h("div", { class: "lista" }, j.fatti.map((v) => cartaVoce(v, j.oggi)))) : null);
  } catch (e) { /* lo stato in alto già dice che Ada non risponde */ }
}

const proximaOra = () => { const d = new Date(); d.setHours(d.getHours() + 1, 0, 0, 0); return `${due2(d.getHours())}:00`; };
$("ag-data").value = $("ag-data").min = oggiLocale();
$("ag-ora").value = proximaOra();
$("btn-ag-nuovo").addEventListener("click", () => { $("form-ag").hidden = !$("form-ag").hidden; $("ag-data").value = oggiLocale(); $("ag-ora").value = proximaOra(); if (!$("form-ag").hidden) $("ag-titolo").focus(); });
$("ag-tipo").addEventListener("click", (e) => {
  if (!e.target.dataset.t) return;
  $("ag-tipo").querySelectorAll("button").forEach((b) => b.classList.toggle("on", b === e.target));
});
$("ag-tutto").addEventListener("change", () => { $("ag-ora").hidden = $("ag-tutto").checked; });
$("form-ag").addEventListener("submit", async (e) => {
  e.preventDefault();
  const tutto = $("ag-tutto").checked;
  try {
    await api("/api/agenda", { titolo: $("ag-titolo").value, quando: $("ag-data").value + (tutto ? "" : " " + $("ag-ora").value),
      tipo: $("ag-tipo").querySelector("button.on").dataset.t, ripeti: $("ag-ripeti").value, preavviso_min: tutto ? 0 : +$("ag-preavviso").value });
    toast("In agenda"); $("ag-titolo").value = ""; $("form-ag").hidden = true; caricaAgenda(); aggiorna();
  } catch (err) { toast(err.message); }
});

let urlVendite = "";
async function caricaVendite() {
  let j;
  try { j = await api("/api/vendite"); } catch (e) { return; }
  urlVendite = j.url;
  $("form-vendite").hidden = !!j.url && $("vendite-cambia").dataset.aperto !== "1";
  $("vendite-apri").hidden = $("vendite-cambia").hidden = !j.url;
  if (j.url) $("vendite-apri").href = j.url;
  $("vendite-nota").textContent = j.url
    ? "Quando racconti una vendita, un preventivo o una chiamata, il reparto vendite aggiorna l'app dal telefono. Se lo schermo non è collegato, l'aggiornamento resta qui in coda."
    : "Incolla il link dell'app «Andamento vendite» (lo trovi nel menu Condividi dell'app): serve ad Ada per aprirla e aggiornarla.";
  svuota($("vendite-coda"), j.coda.length ? [h("h3", null, `Da riportare nell'app (${j.coda.length})`), j.coda.map((c) => h("div", { class: "voce" },
    h("b", null, c.riassunto),
    h("span", { class: "meta" }, "Frase per il Coach dell'app: " + c.frase),
    h("div", { class: "azioni ripiega" },
      h("button", { class: "primario", type: "button", onclick: async () => {
        try { await navigator.clipboard.writeText(c.frase); toast("Frase copiata: incollala nel Coach dell'app"); } catch (e) { toast("Non riesco a copiare: selezionala a mano"); }
        if (urlVendite) window.open(urlVendite, "_blank", "noopener");
      } }, "Copia e apri l'app"),
      h("button", { class: "secondario", type: "button", onclick: async () => { try { await api("/api/vendite/coda/" + c.id, { azione: "fatto" }); toast("Segnato come riportato"); caricaVendite(); aggiorna(); } catch (e) { toast(e.message); } } }, "Fatto"),
      h("button", { class: "secondario", type: "button", onclick: async () => { try { await api("/api/vendite/coda/" + c.id, { azione: "elimina" }); caricaVendite(); aggiorna(); } catch (e) { toast(e.message); } } }, "Elimina")))
  )] : h("div", { class: "vuoto" }, j.url ? "Niente da riportare: l'app è aggiornata." : ""));
}
$("vendite-cambia").addEventListener("click", () => { $("vendite-cambia").dataset.aperto = "1"; $("form-vendite").hidden = false; $("vendite-url").value = urlVendite; $("vendite-url").focus(); });
$("form-vendite").addEventListener("submit", async (e) => {
  e.preventDefault();
  try { await api("/api/vendite/impostazioni", { url: $("vendite-url").value }); toast("Link salvato"); $("vendite-cambia").dataset.aperto = ""; caricaVendite(); aggiorna(); }
  catch (err) { toast(err.message); }
});

/* ---------- dettaglio agente ---------- */
const ICONE_AGENTE = { ada: "✨", contabilita_piva: "🧾", contabilita_privata: "💳", quotidiano: "🗓️", sviluppo: "🛠️",
  clienti_vendite: "🤝", acquisti: "🛒", revisore: "🔍", collaudatore: "🎭" };
const NOMI_STRUMENTI = {
  riepilogo_spese: "Legge le spese", aggiungi_regola_prompt: "Aggiunge una regola a un prompt", riepilogo_fatture: "Legge le fatture", annota_segnalazione: "Annota i problemi",
  richiedi_approvazione: "Chiede il tuo ok", telefono_collega: "Collega lo schermo", telefono_schermo: "Guarda lo schermo",
  telefono_tocca: "Tocca lo schermo", telefono_scrivi: "Scrive sullo schermo", telefono_scorri: "Scorre le pagine",
  telefono_vai: "Indietro e home", telefono_apri: "Apre app e pagine", agenda_aggiungi: "Aggiunge promemoria e eventi", agenda_elenco: "Legge l'agenda",
  agenda_cambia: "Sposta o chiude voci dell'agenda", avvisa_utente: "Manda notifiche sul telefono", vendite_coda: "Mette in coda gli aggiornamenti dell'app vendite", proponi_acquisto: "Propone acquisti",
  acquisto_pronto: "Prepara l'ordine", delega: "Affida compiti al team", migliora_prompt: "Migliora i prompt",
  chiudi_segnalazione: "Chiude le segnalazioni", gestisci_routine: "Gestisce le routine", stato_sistema: "Controlla lo stato",
  fattura_incassata: "Segna le fatture incassate", proponi_idea: "Propone funzioni nuove", regola_categoria: "Impara le categorie di spesa",
};
const FRASI_ATTIVITA = {
  lavoro: "Ha ricevuto un compito", risposta: "Ha risposto", errore: "Ha avuto un errore", segnalazione: "Ha segnalato un problema",
  "prompt migliorato": "Ha migliorato un prompt", "richiesta approvazione": "Ha chiesto il tuo ok", "proposta acquisto": "Ha proposto un acquisto",
  "idea proposta": "Ha proposto una funzione nuova", "segnalazione chiusa": "Ha chiuso una segnalazione", "proposta modifica grande": "Ha proposto una modifica grande",
  "fattura archiviata": "Ha archiviato una fattura", "fattura incassata": "Ha segnato una fattura incassata",
  "regola categoria": "Ha imparato una categoria", "ordine pronto": "Ha preparato un ordine", routine: "Ha eseguito una routine",
  "routine creata": "Ha creato una routine", "routine modificata": "Ha modificato una routine",
  collaudo: "Ha fatto un collaudo", "appunti (lezione)": "Ha studiato una lezione", "appunti (lettura)": "Ha letto un pezzo di libro",
  "ritmo di lavoro": "Ha scelto il ritmo di lavoro", agenda: "Ha usato l'agenda", "notifica inviata": "Ha mandato una notifica",
  "coda vendite": "Ha messo in coda un aggiornamento dell'app vendite", "app vendite": "Impostazioni dell'app vendite",
  "movimento aggiunto": "Ha aggiunto un movimento", "movimento rimosso": "Ha tolto un movimento", "estratto conto": "Ha caricato un estratto conto",
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
  svuota($("ag-strumenti"), d.strumenti.length ? d.strumenti.map((t) => h("span", { class: "tag" }, NOMI_STRUMENTI[t] || t))
    : h("span", { class: "tag" }, "Parla soltanto: nessuno strumento"));
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
