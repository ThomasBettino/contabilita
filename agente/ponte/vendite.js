#!/usr/bin/env node
// Ponte vendite di Agente 1.
// Legge i documenti esportati dall'artefatto "Andamento vendite" e scrive il riepilogo
// che lo specialista vendite di Agente 1 legge, più gli avvisi nuovi da notificare.
//
// Uso: node vendite.js <cartella-vendite> <cartella-agente> <cartella-uscita>
//   <cartella-vendite>  export di trattative/, giorni/, mesi/, appuntamenti/ e config/impostazioni.json
//   <cartella-agente>   export di notifiche/ di Agente 1, per non ripetere avvisi già inviati
//   <cartella-uscita>   qui vengono scritti sync/vendite.json e notifiche/<id>.json
process.env.TZ = 'Europe/Rome';

const fs = require('node:fs');
const path = require('node:path');

const [dirVendite, dirAgente, dirUscita] = process.argv.slice(2);
if (!dirVendite || !dirAgente || !dirUscita) {
  console.error('Uso: node vendite.js <cartella-vendite> <cartella-agente> <cartella-uscita>');
  process.exit(1);
}

function leggiCollezione(dir) {
  const o = {};
  if (!fs.existsSync(dir)) return o;
  for (const f of fs.readdirSync(dir)) {
    if (f.endsWith('.json')) o[f.slice(0, -5)] = JSON.parse(fs.readFileSync(path.join(dir, f), 'utf8'));
  }
  return o;
}

function leggiDoc(file) {
  return fs.existsSync(file) ? JSON.parse(fs.readFileSync(file, 'utf8')) : {};
}

function scrivi(file, dati) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify(dati, null, 2) + '\n');
}

/* ---------- Logica copiata da Andamento vendite (v21), per avere gli stessi numeri ---------- */

const MESI=["Gennaio","Febbraio","Marzo","Aprile","Maggio","Giugno","Luglio","Agosto","Settembre","Ottobre","Novembre","Dicembre"];
const GG=["dom","lun","mar","mer","gio","ven","sab"];
const GGI=["domenica","lunedì","martedì","mercoledì","giovedì","venerdì","sabato"];
const FORMS={fd:"Full drive",contanti:"Contanti",altro:"Altro"};
const FONTI=["Salone","Internet","Telefono","Passaparola","Cliente già mio","Altro"];
const MOTIVI=["Prezzo","Rata","Valutazione permuta","Tempi di consegna","Comprato altrove","Non risponde più","Ci ripensa","Altro"];
const DEF={settimana:[1,2,3,4,5,6],marche:["Citroën","Peugeot","Opel","Fiat","Jeep","DS"]};
const DEF_PIANO={fisso:1100,contanti:230,perc:6,fin:130,domenica:75,premio:150,tasse:30};
const CST={da_saldare:{l:"Da saldare",c:"r"},saldato:{l:"Saldato, da consegnare",c:"y"},consegnata:{l:"Consegnata",c:"g"}};
const FST={attesa:{l:"In attesa",long:"Finanziamento in attesa",c:"acc"},approvato:{l:"Approvato",long:"Finanziamento approvato",c:"good"},rifiutato:{l:"Rifiutato",long:"Finanziamento rifiutato",c:"bad"}};

const S={
  tr:leggiCollezione(path.join(dirVendite,"trattative")),
  days:leggiCollezione(path.join(dirVendite,"giorni")),
  mesi:leggiCollezione(path.join(dirVendite,"mesi")),
  app:leggiCollezione(path.join(dirVendite,"appuntamenti")),
  settings:{...DEF,...leggiDoc(path.join(dirVendite,"config","impostazioni.json"))}
};

const piano=()=>({...DEF_PIANO,...(S.settings.piano||{})});
const pays=t=>Array.isArray(t.pagamenti)?t.pagamenti:[];
const paid=t=>pays(t).reduce((a,p)=>a+(+p.importo||0),0);
const prezzoV=t=>+(t.prezzoVendita||t.prezzo||0);
const residuo=t=>Math.max(0,prezzoV(t)-paid(t));
const T=()=>Object.entries(S.tr).map(([id,v])=>({id,...v}));
const A=()=>Object.entries(S.app).map(([id,v])=>({id,...v}));
function agendaItems(from,to){
  const it=[];A().forEach(a=>{if(a.data&&a.data>=from&&a.data<=to)it.push({k:"a",id:a.id,data:a.data,ora:a.ora||"",tit:(a.tipo||"Appuntamento")+(a.con?" · "+a.con:""),sub:[a.auto,a.note].filter(Boolean).join(" · "),fatto:!!a.fatto});});
  T().forEach(t=>{if(t.tdData&&t.tdData>=from&&t.tdData<=to)it.push({k:"t",id:t.id,data:t.tdData,ora:t.tdOra||"",tit:"Test drive · "+(t.nome||"Cliente"),sub:[t.marca,t.modello].filter(Boolean).join(" "),fatto:false});});
  return it.sort((a,b)=>(a.data+(a.ora||"99"))<(b.data+(b.ora||"99"))?-1:1);
}
const cstOf=t=>CST[t.statoCliente]?t.statoCliente:"da_saldare";
const finOf=t=>t.formula==="contanti"?null:(FST[t.statoFin]?t.statoFin:"attesa");
const earn=(x,P)=>x.formula==="contanti"?P.contanti:(+x.margine||0)*P.perc/100+P.fin;

const nf=(n,d=0)=>Number(n||0).toLocaleString("it-IT",{minimumFractionDigits:d,maximumFractionDigits:d});
const nf1=n=>Number(n).toLocaleString("it-IT",{maximumFractionDigits:1});
const eur=n=>"€ "+nf(Math.round(n||0));
const pctF=n=>nf(n*100,1)+"%";
const pad=n=>String(n).padStart(2,"0");
const keyOf=d=>d.getFullYear()+"-"+pad(d.getMonth()+1)+"-"+pad(d.getDate());
const dOf=k=>new Date(k+"T12:00:00");
const today=()=>keyOf(new Date());
const addDays=(k,n)=>{const d=dOf(k);d.setDate(d.getDate()+n);return keyOf(d);};
const diffDays=(a,b)=>Math.round((dOf(b)-dOf(a))/864e5);
const ymOf=k=>(k||"").slice(0,7);
const dayLabel=k=>{const d=dOf(k);return GG[d.getDay()]+" "+d.getDate()+" "+MESI[d.getMonth()].slice(0,3).toLowerCase();};
const itDate=k=>{const d=dOf(k);return GGI[d.getDay()]+" "+d.getDate()+"/"+(d.getMonth()+1)+"/"+d.getFullYear();};

const brandList=()=>{const b=(S.settings.marche&&S.settings.marche.length)?S.settings.marche:DEF.marche;return b.slice();};
function legacyPrev(v){ if(!v) return {}; if(v.prev&&typeof v.prev==="object") return v.prev; const n=+v.preventivi||0; return n?{"Senza marca":n}:{}; }
const sumMap=m=>Object.values(m).reduce((a,b)=>a+(+b||0),0);
const contattiOf=t=>Array.isArray(t.contatti)?t.contatti:[];
function lastContact(t){const c=contattiOf(t);return c.length?c[c.length-1].data:t.data;}

function dayStats(k){
  const all=T();
  const prev=all.filter(t=>t.data===k);
  const sold=all.filter(t=>t.stato==="venduto"&&t.dataVendita===k);
  let calls=0; all.forEach(t=>contattiOf(t).forEach(c=>{if(c.data===k)calls++;}));
  const g=S.days[k]; const leg=sumMap(legacyPrev(g));
  const riposo=!!(g&&g.lavorato===false);
  const st={prev:prev.length+leg,leg,prevList:prev,sold,calls,n:sold.length,fd:sold.filter(t=>t.formula==="fd").length,marg:sold.reduce((a,t)=>a+(+t.margine||0),0),riposo};
  st.worked=!riposo&&(st.prev>0||st.n>0||calls>0||!!(g&&g.lavorato===true));
  return st;
}

function calc(ym){
  const [y,m]=ym.split("-").map(Number), nDays=new Date(y,m,0).getDate(), week=S.settings.settimana||DEF.settimana;
  const keys=[],sched=[];
  for(let d=1;d<=nDays;d++){const dt=new Date(y,m-1,d),k=keyOf(dt);keys.push(k);if(week.includes(dt.getDay()))sched.push(k);}
  const tk=today(), all=T();
  const t={prev:0,lav:0,off:0,fd:0,cont:0,altro:0,marg:0,mFd:0,mCont:0,mAltro:0};
  const stats={}; keys.forEach(k=>{const s=dayStats(k);stats[k]=s;t.prev+=s.prev;if(s.worked)t.lav++;if(s.riposo)t.off++;});
  const sales=all.filter(x=>x.stato==="venduto"&&ymOf(x.dataVendita)===ym).sort((a,b)=>a.dataVendita<b.dataVendita?1:-1);
  sales.forEach(x=>{const mg=+x.margine||0;t.marg+=mg;if(x.formula==="fd"){t.fd++;t.mFd+=mg;}else if(x.formula==="contanti"){t.cont++;t.mCont+=mg;}else{t.altro++;t.mAltro+=mg;}});
  t.tot=t.fd+t.cont+t.altro;
  const mese=S.mesi[ym]||{}, ov=+mese.giorniLavorativi||0, thisYm=tk.slice(0,7);
  let rim=0;
  if(ym>thisYm) rim=ov||sched.length;
  else if(ym===thisYm){ rim=sched.filter(k=>k>tk&&!stats[k].riposo).length+((sched.includes(tk)||stats[tk].worked)&&!stats[tk].worked&&!stats[tk].riposo?1:0);
    if(ov) rim=Math.max(0,ov-t.lav-t.off); }
  const cohort=all.filter(x=>ymOf(x.data)===ym);
  const obj=+mese.obiettivo||0, P=piano();
  t.nCont=0;t.nFin=0;t.eCont=0;t.ePerc=0;t.eFin=0;
  sales.forEach(x=>{if(x.formula==="contanti"){t.nCont++;t.eCont+=P.contanti;}else{t.nFin++;t.ePerc+=(+x.margine||0)*P.perc/100;t.eFin+=P.fin;}});
  t.eSales=t.eCont+t.ePerc+t.eFin;
  const isSun=k=>dOf(k).getDay()===0;
  t.dom=keys.filter(k=>isSun(k)&&stats[k].worked).length; t.eDom=t.dom*P.domenica;
  t.premio=obj&&t.tot>=obj?P.premio:0;
  t.fisso=+P.fisso||0;
  t.fatt=t.fisso+t.eSales+t.eDom+t.premio;
  let domRim=0;
  if(ym>thisYm) domRim=sched.filter(isSun).length;
  else if(ym===thisYm) domRim=sched.filter(k=>isSun(k)&&!stats[k].riposo&&(k>tk||(k===tk&&!stats[k].worked))).length;
  const f=t.lav?rim/t.lav:null;
  let proj=null;
  if(f!==null){const totP=t.tot*(1+f);proj={tot:totP,sales:t.eSales*(1+f),dom:(t.dom+domRim)*P.domenica,premio:obj&&totP>=obj?P.premio:0};proj.fatt=t.fisso+proj.sales+proj.dom+proj.premio;}
  return {y,m,keys,stats,sales,t,rim,previsti:ov||sched.length,schedN:sched.length,obj,objM:+mese.obiettivoMargine||0,cohort,P,domRim,proj};
}

function prevYm(ym,n){const [y,m]=ym.split("-").map(Number);const d=new Date(y,m-1+n,1);return d.getFullYear()+"-"+pad(d.getMonth()+1);}
const ymLabel=ym=>{const [y,m]=ym.split("-").map(Number);return MESI[m-1]+" "+y;};

function ritmoInfo(c){const t=c.t,att=t.lav?t.prev/t.lav:0,chi=t.prev?t.tot/t.prev:0;let nec=null;
  if(c.obj&&t.tot<c.obj&&c.rim&&chi){nec=((c.obj-t.tot)/chi)/c.rim;}return{att,chi,nec};}
function monthLine(c){const t=c.t,r=ritmoInfo(c);
  return "preventivi "+t.prev+", vendite "+t.tot+" (full drive "+t.fd+", contanti "+t.cont+", altro "+t.altro+"), conversione full drive "+(t.prev?pctF(t.fd/t.prev):"—")+", chiusura totale "+(t.prev?pctF(r.chi):"—")+
   ", margine "+eur(t.marg)+", fatturato ad oggi "+eur(t.fatt)+" (fisso "+eur(t.fisso)+", provvigioni vendite "+eur(t.eSales)+", domeniche "+t.dom+" = "+eur(t.eDom)+", premio "+eur(t.premio)+")"+
   ", giorni lavorati "+t.lav+", giorni lavorativi rimasti "+c.rim+", obiettivo vendite "+(c.obj||"non impostato")+(c.obj?" (mancano "+Math.max(0,c.obj-t.tot)+")":"")+
   (c.proj&&c.rim?", proiezione fine mese: ~"+nf1(c.proj.tot)+" vendite e "+eur(c.proj.fatt)+" di fatturato":"")+
   ", ritmo attuale "+nf1(r.att)+" preventivi al giorno"+(r.nec?", ritmo necessario "+nf(r.nec,1)+" preventivi al giorno":"");}
function aiSnapshot(){
  const tk=today(),cur=today().slice(0,7),c=calc(cur),p=calc(prevYm(cur,-1)),P=piano(),all=T();
  const L=[];
  L.push("OGGI: "+itDate(tk)+" ("+tk+"). Prossimi giorni: "+[1,2,3,4,5,6,7].map(i=>{const k=addDays(tk,i);return GGI[dOf(k).getDay()]+" = "+k;}).join(", ")+".");
  L.push("MESE CORRENTE ("+ymLabel(cur)+"): "+monthLine(c)+".");
  L.push("MESE PRECEDENTE ("+ymLabel(p.y+"-"+pad(p.m))+"): "+monthLine(p)+".");
  L.push("PIANO PROVVIGIONALE: fisso "+eur(P.fisso)+"/mese; vendita in contanti "+eur(P.contanti)+"; vendita finanziata (full drive o altro) "+nf1(P.perc)+"% del margine + "+eur(P.fin)+"; domenica lavorata "+eur(P.domenica)+"; premio obiettivo vendite "+eur(P.premio)+".");
  L.push("MARCHE DISPONIBILI: "+brandList().join(", ")+". FONTI: "+FONTI.join(", ")+". MOTIVI PERSO: "+MOTIVI.join(", ")+".");
  const open=all.filter(t=>t.stato==="aperto").sort((a,b)=>(a.richiamo||"9")<(b.richiamo||"9")?-1:1).slice(0,80);
  L.push("\nPREVENTIVI APERTI ("+all.filter(t=>t.stato==="aperto").length+") — id | nome | auto | data preventivo | richiamo | prezzo | chiamate | test drive | permuta | note:");
  open.forEach(t=>{const cc=contattiOf(t);L.push([t.id,t.nome,[t.marca,t.modello].filter(Boolean).join(" "),t.data,t.richiamo?(t.richiamo<tk?t.richiamo+" (IN RITARDO)":t.richiamo):"nessun richiamo",t.prezzo?eur(t.prezzo):"-",cc.length+(cc.length?" (ultima "+cc[cc.length-1].data+": "+(cc[cc.length-1].nota||"")+")":""),t.testDrive?"sì":(t.tdData?"prenotato "+t.tdData+(t.tdOra?" "+t.tdOra:""):"no"),t.permuta?"sì":"no",(t.note||"").slice(0,140)].join(" | "));});
  const ag=A().filter(a=>a.data&&a.data>=addDays(tk,-14)&&!(a.fatto&&a.data<tk)).sort((a,b)=>(a.data+(a.ora||""))<(b.data+(b.ora||""))?-1:1).slice(0,60);
  L.push("\nAGENDA APPUNTAMENTI — id | data | ora | tipo | con | auto | note | stato:");ag.forEach(a=>L.push([a.id,a.data,a.ora||"-",a.tipo||"Appuntamento",a.con||"-",a.auto||"-",(a.note||"").slice(0,100),a.fatto?"fatto":(a.data<tk?"passato, non segnato":"in programma")].join(" | ")));if(!ag.length)L.push("nessuno");
  const tdUp=all.filter(t=>t.tdData&&t.tdData>=tk).sort((a,b)=>(a.tdData+(a.tdOra||""))<(b.tdData+(b.tdOra||""))?-1:1);
  L.push("\nTEST DRIVE PRENOTATI: "+(tdUp.length?tdUp.map(t=>t.nome+" ("+[t.marca,t.modello].filter(Boolean).join(" ")+") "+t.tdData+(t.tdOra?" "+t.tdOra:"")+" [id "+t.id+"]").join("; "):"nessuno")+".");
  const sold=all.filter(t=>t.stato==="venduto").sort((a,b)=>(b.dataVendita||"")>(a.dataVendita||"")?1:-1).slice(0,80);
  L.push("\nCLIENTI (VENDUTI) — id | nome | auto | data vendita | formula | margine | ti frutta | prezzo vendita | pagato | da saldare | stato cliente | avvisato saldo | finanziamento:");
  sold.forEach(t=>L.push([t.id,t.nome,[t.marca,t.modello].filter(Boolean).join(" "),t.dataVendita,FORMS[t.formula]||"",eur(t.margine),eur(earn(t,P)),prezzoV(t)?eur(prezzoV(t)):"non indicato",eur(paid(t)),prezzoV(t)?eur(residuo(t)):"-",CST[cstOf(t)].l,t.avvisatoSaldo?"sì":"no",finOf(t)?FST[finOf(t)].l:"contanti"].join(" | ")));
  const lost=all.filter(t=>t.stato==="perso"&&(t.dataPerso||"")>=addDays(tk,-60));const lm={};lost.forEach(t=>{lm[t.motivo||"non indicato"]=(lm[t.motivo||"non indicato"]||0)+1;});
  L.push("\nPERSI ULTIMI 60 GIORNI: "+lost.length+(lost.length?" — "+Object.entries(lm).map(([k,v])=>k+" "+v).join(", "):"")+".");
  const bm={};c.cohort.forEach(t=>{const k=t.marca||"?";const o=bm[k]||(bm[k]={n:0,v:0});o.n++;if(t.stato==="venduto")o.v++;});
  L.push("PREVENTIVI DEL MESE PER MARCA: "+(Object.entries(bm).map(([k,o])=>k+" "+o.n+" (venduti "+o.v+")").join(", ")||"nessuno")+".");
  const allP=all.filter(t=>t.data);const grp=(fn)=>{const g={};allP.forEach(t=>{const k=fn(t);const o=g[k]||(g[k]={n:0,v:0});o.n++;if(t.stato==="venduto")o.v++;});return Object.entries(g).map(([k,o])=>k+" "+o.v+"/"+o.n).join(", ");};
  L.push("ANALISI DA SEMPRE (venduti/preventivi): per marca: "+grp(t=>t.marca||"?")+". Per provenienza: "+grp(t=>t.fonte||"non indicata")+". Test drive: "+grp(t=>t.testDrive?"con test drive":"senza test drive")+". Permuta: "+grp(t=>t.permuta?"con permuta":"senza permuta")+".");
  const sv=all.filter(t=>t.stato==="venduto"&&t.data&&t.dataVendita);if(sv.length)L.push("Giorni medi dal preventivo alla vendita: "+nf1(sv.reduce((x,t)=>x+Math.max(0,diffDays(t.data,t.dataVendita)),0)/sv.length)+".");
  const lmA={};all.filter(t=>t.stato==="perso").forEach(t=>{lmA[t.motivo||"non indicato"]=(lmA[t.motivo||"non indicato"]||0)+1;});L.push("Motivi di perdita da sempre: "+(Object.entries(lmA).map(([k,v])=>k+" "+v).join(", ")||"nessuno")+".");
  const stale=all.filter(t=>t.stato==="aperto"&&diffDays(lastContact(t),tk)>=7).length;L.push("Preventivi aperti fermi da 7+ giorni senza contatti: "+stale+". Senza data di richiamo: "+all.filter(t=>t.stato==="aperto"&&!t.richiamo).length+".");
  L.push("CONTI: fatturato del mese ad oggi "+eur(c.t.fatt)+"; da mettere da parte per tasse ("+nf1(P.tasse)+"%): "+eur(c.t.fatt*P.tasse/100)+"; netto stimato "+eur(c.t.fatt*(1-P.tasse/100))+". Regime forfettario. Proiezione fatturato fine mese: "+(c.proj?eur(c.proj.fatt):"n.d.")+".");
  return L.join("\n");
}

/* ---------- Riepilogo per Agente 1 ---------- */

const ora = new Date();
const tk = today();
const c = calc(tk.slice(0, 7));
const tutte = T();
const aperti = tutte.filter((t) => t.stato === 'aperto');
const inRitardo = aperti.filter((t) => t.richiamo && t.richiamo < tk);
const richiamiOggi = aperti.filter((t) => t.richiamo === tk);
const daSaldare = tutte.filter((t) => t.stato === 'venduto' && cstOf(t) === 'da_saldare' && prezzoV(t) && residuo(t) > 0);
const auto = (t) => [t.marca, t.modello].filter(Boolean).join(' ');

// Agenda dei prossimi 7 giorni: appuntamenti e test drive della app, più i richiami dei preventivi aperti.
const agenda = agendaItems(tk, addDays(tk, 7)).map((x) => ({ data: x.data, ora: x.ora, titolo: x.tit, dettagli: x.sub, fatto: x.fatto }));
for (const t of aperti) {
  if (t.richiamo && t.richiamo <= addDays(tk, 7)) {
    agenda.push({ data: t.richiamo < tk ? tk : t.richiamo, ora: '', titolo: 'Richiamare · ' + (t.nome || 'Cliente'), dettagli: auto(t) + (t.richiamo < tk ? ' · in ritardo dal ' + dayLabel(t.richiamo) : ''), fatto: false });
  }
}
agenda.sort((a, b) => (a.data + (a.ora || '99')) < (b.data + (b.ora || '99')) ? -1 : 1);
const agendaOggi = agenda.filter((x) => x.data === tk && !x.fatto);

const polso = {
  mese: ymLabel(tk.slice(0, 7)),
  vendite: c.t.tot,
  obiettivo: c.obj || null,
  fatturato: Math.round(c.t.fatt),
  proiezione: c.proj ? Math.round(c.proj.fatt) : null,
  margine: Math.round(c.t.marg),
  preventivi: c.t.prev,
  aperti: aperti.length,
  richiamiInRitardo: inRitardo.length,
  richiamiOggi: richiamiOggi.length,
  agendaOggi: agendaOggi.length
};

// Avvisi con id stabili: se esistono già tra le notifiche di Agente 1 non vengono ripetuti.
const giaInviate = new Set(Object.keys(leggiCollezione(path.join(dirAgente, 'notifiche'))));
const avvisi = [];
const aggiungi = (id, titolo, testo) => { if (!giaInviate.has(id)) avvisi.push({ id, titolo, testo }); };

if (inRitardo.length || richiamiOggi.length) {
  const righe = [];
  if (inRitardo.length) righe.push('In ritardo: ' + inRitardo.map((t) => `${t.nome} (${auto(t)}, dal ${dayLabel(t.richiamo)})`).join('; ') + '.');
  if (richiamiOggi.length) righe.push('Oggi: ' + richiamiOggi.map((t) => `${t.nome} (${auto(t)})`).join('; ') + '.');
  aggiungi(`richiami-${tk}`, 'Clienti da richiamare', righe.join(' '));
}

const inAgendaOggi = agendaOggi.filter((x) => !x.titolo.startsWith('Richiamare'));
if (inAgendaOggi.length) {
  aggiungi(`agenda-${tk}`, 'Oggi in agenda', inAgendaOggi.map((x) => (x.ora ? x.ora + ' ' : '') + x.titolo).join('; ') + '.');
}

// Impegni che iniziano entro 90 minuti: il battito orario li intercetta almeno una volta.
const minutiDa = (oraStr) => { const [h, m] = oraStr.split(':').map(Number); return h * 60 + m - (ora.getHours() * 60 + ora.getMinutes()); };
for (const x of agendaItems(tk, tk)) {
  if (x.fatto || !x.ora) continue;
  const mancano = minutiDa(x.ora);
  if (mancano >= 0 && mancano <= 90) aggiungi(`presto-${x.k}-${x.id}-${tk}`, `Alle ${x.ora}: ${x.tit}`, x.sub || x.tit);
}

// Saldi da incassare: una volta a settimana (id legato al lunedì della settimana).
const lunedi = addDays(tk, -((dOf(tk).getDay() + 6) % 7));
if (daSaldare.length) {
  const pagamento = (t) => finOf(t) ? `${FORMS[t.formula] || 'finanziato'}, finanziamento ${FST[finOf(t)].l.toLowerCase()}` : 'contanti';
  aggiungi(`saldi-${lunedi}`, 'Saldi da incassare', daSaldare.map((t) => `${t.nome} (${auto(t)}, ${pagamento(t)}): mancano ${eur(residuo(t))}`).join('; ') + '.');
}

scrivi(path.join(dirUscita, 'sync', 'vendite.json'), {
  aggiornato: ora.toISOString(),
  fonte: 'Andamento vendite',
  polso,
  agenda: agenda.slice(0, 40),
  testo: aiSnapshot()
});
for (const a of avvisi) {
  scrivi(path.join(dirUscita, 'notifiche', a.id + '.json'), { titolo: a.titolo, testo: a.testo, ora: ora.toISOString(), fonte: 'Vendite', letta: false });
}

console.log(JSON.stringify({ polso, nuoveNotifiche: avvisi }, null, 2));
