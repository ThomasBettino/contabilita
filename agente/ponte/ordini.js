#!/usr/bin/env node
// Esecutore degli ordini di Agente 1 per l'app "Andamento vendite".
// Gli ordini nascono nell'app Agente 1 (collezione ordini) e li esegue il battito.
// Le operazioni e le loro regole sono copiate dal Coach della app vendite (aiTools, v21):
// stesse validazioni, stessi campi, stesso risultato di una modifica fatta dalla app.
//
// Uso: node ordini.js <export-ordini> <export-vendite> <uscita>
//   <export-ordini>   cartella con ordini/<id>.json: gli ordini presi in carico in questo giro
//   <export-vendite>  export di Andamento vendite (trattative/, appuntamenti/, config/impostazioni.json);
//                     le copie vengono aggiornate, così il riepilogo vendite di questo giro vede le modifiche
//   <uscita>          scrive ordini-piano.json, scritture/<collezione>/<id>.json e ordini/<id>.json
process.env.TZ = 'Europe/Rome';

const fs = require('node:fs');
const path = require('node:path');

const [dirOrdini, dirVendite, dirUscita] = process.argv.slice(2);
if (!dirOrdini || !dirVendite || !dirUscita) {
  console.error('Uso: node ordini.js <export-ordini> <export-vendite> <uscita>');
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
function scrivi(file, dati) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify(dati, null, 2) + '\n');
}
const clona = (x) => JSON.parse(JSON.stringify(x));

/* ---------- Costanti e aiuti copiati da Andamento vendite (v21) ---------- */

const MESI=["Gennaio","Febbraio","Marzo","Aprile","Maggio","Giugno","Luglio","Agosto","Settembre","Ottobre","Novembre","Dicembre"];
const GG=["dom","lun","mar","mer","gio","ven","sab"];
const FORMS={fd:"Full drive",contanti:"Contanti",altro:"Altro"};
const FONTI=["Salone","Internet","Telefono","Passaparola","Cliente già mio","Altro"];
const MOTIVI=["Prezzo","Rata","Valutazione permuta","Tempi di consegna","Comprato altrove","Non risponde più","Ci ripensa","Altro"];
const DEF={settimana:[1,2,3,4,5,6],marche:["Citroën","Peugeot","Opel","Fiat","Jeep","DS"]};
const DEF_PIANO={fisso:1100,contanti:230,perc:6,fin:130,domenica:75,premio:150,tasse:30};
const PAYT=["Acconto","Caparra","Saldo","Finanziamento","Permuta","Altro"];
const APPT=["Appuntamento","Consegna","Firma contratto","Telefonata","Perizia permuta","Altro"];
const CST={da_saldare:{l:"Da saldare",c:"r"},saldato:{l:"Saldato, da consegnare",c:"y"},consegnata:{l:"Consegnata",c:"g"}};
const FST={attesa:{l:"In attesa",long:"Finanziamento in attesa",c:"acc"},approvato:{l:"Approvato",long:"Finanziamento approvato",c:"good"},rifiutato:{l:"Rifiutato",long:"Finanziamento rifiutato",c:"bad"}};

const S={
  tr:leggiCollezione(path.join(dirVendite,"trattative")),
  app:leggiCollezione(path.join(dirVendite,"appuntamenti")),
  settings:{...DEF,...(fs.existsSync(path.join(dirVendite,"config","impostazioni.json"))?JSON.parse(fs.readFileSync(path.join(dirVendite,"config","impostazioni.json"),"utf8")):{})}
};
const MAPS={trattative:"tr",appuntamenti:"app"};

const piano=()=>({...DEF_PIANO,...(S.settings.piano||{})});
const pays=t=>Array.isArray(t.pagamenti)?t.pagamenti:[];
const T=()=>Object.entries(S.tr).map(([id,v])=>({id,...v}));
const finOf=t=>t.formula==="contanti"?null:(FST[t.statoFin]?t.statoFin:"attesa");
const earn=(x,P)=>x.formula==="contanti"?P.contanti:(+x.margine||0)*P.perc/100+P.fin;
const nf=(n,d=0)=>Number(n||0).toLocaleString("it-IT",{minimumFractionDigits:d,maximumFractionDigits:d});
const eur=n=>"€ "+nf(Math.round(n||0));
const pad=n=>String(n).padStart(2,"0");
const keyOf=d=>d.getFullYear()+"-"+pad(d.getMonth()+1)+"-"+pad(d.getDate());
const dOf=k=>new Date(k+"T12:00:00");
const today=()=>keyOf(new Date());
const addDays=(k,n)=>{const d=dOf(k);d.setDate(d.getDate()+n);return keyOf(d);};
const dayLabel=k=>{const d=dOf(k);return GG[d.getDay()]+" "+d.getDate()+" "+MESI[d.getMonth()].slice(0,3).toLowerCase();};
const brandList=()=>{const b=(S.settings.marche&&S.settings.marche.length)?S.settings.marche:DEF.marche;return b.slice();};
const contattiOf=t=>Array.isArray(t.contatti)?t.contatti:[];

/* ---------- Le operazioni, come aiTools della app ---------- */
// Ognuna restituisce {titolo, righe, id, col, build}: build(attuale) dà il documento nuovo.

function operazioni(nuovoId) {
  const str=v=>v==null?"":String(v).trim();const num=v=>{if(v==null||v==="")return null;if(typeof v==="number")return v;const n=parseFloat(String(v).replace(/\./g,"").replace(",","."));return isNaN(n)?null:n;};
  const okDate=v=>/^\d{4}-\d{2}-\d{2}$/.test(str(v))?str(v):null;
  const find=id=>{const k=str(id),t=S.tr[k];if(!t)throw new Error("Nessuna scheda con id "+id);return {...t,id:k};};
  const W=(titolo,righe,id,build,col)=>({titolo,righe:righe.filter(Boolean),id,build,col:col||"trattative"});
  return {
    crea_preventivo(i){const nome=str(i.nome);if(!nome)throw new Error("Manca il nome");const marca=brandList().find(b=>b.toLowerCase()===str(i.marca).toLowerCase())||str(i.marca)||brandList()[0];
      const v={stato:"aperto",contatti:[],creato:Date.now(),nome,telefono:str(i.telefono),marca,modello:str(i.modello),prezzo:num(i.prezzo)||0,fonte:FONTI.includes(i.fonte)?i.fonte:"Salone",testDrive:!!i.testDrive,permuta:!!i.permuta,data:today(),note:str(i.note),richiamo:okDate(i.richiamo)||addDays(today(),2)};
      if(S.tr[nuovoId])throw new Error("Preventivo già creato");
      return W("Nuovo preventivo: "+nome,[[marca,v.modello].filter(Boolean).join(" ")+(v.prezzo?" · "+eur(v.prezzo):""),"Richiamo: "+dayLabel(v.richiamo),v.telefono?"Tel. "+v.telefono:"",v.note],nuovoId,()=>v);},
    modifica_scheda(i){const t=find(i.id);const ch={},L=[];
      if(str(i.aggiungi_nota)){L.push("Nota: "+str(i.aggiungi_nota));}
      if(str(i.telefono)){ch.telefono=str(i.telefono);L.push("Telefono: "+ch.telefono);}
      if(str(i.marca)){ch.marca=brandList().find(b=>b.toLowerCase()===str(i.marca).toLowerCase())||str(i.marca);L.push("Marca: "+ch.marca);}
      if(str(i.modello)){ch.modello=str(i.modello);L.push("Modello: "+ch.modello);}
      if(num(i.prezzo)!=null){ch.prezzo=num(i.prezzo);L.push("Prezzo proposto: "+eur(ch.prezzo));}
      if(num(i.prezzoVendita)!=null){ch.prezzoVendita=num(i.prezzoVendita);L.push("Prezzo di vendita: "+eur(ch.prezzoVendita));}
      if(num(i.margine)!=null){ch.margine=Math.max(0,num(i.margine));L.push("Margine: "+eur(ch.margine));}
      if(["fd","contanti","altro"].includes(i.formula)){ch.formula=i.formula;L.push("Formula: "+FORMS[i.formula]);}
      if(str(i.richiamo)){if(/nessun/i.test(i.richiamo)){ch.richiamo=null;L.push("Richiamo tolto");}else if(okDate(i.richiamo)){ch.richiamo=okDate(i.richiamo);L.push("Richiamo: "+dayLabel(ch.richiamo));}}
      if(typeof i.testDrive==="boolean"){ch.testDrive=i.testDrive;L.push(i.testDrive?"Test drive fatto":"Test drive: no");}
      if(typeof i.permuta==="boolean"){ch.permuta=i.permuta;L.push(i.permuta?"Con permuta":"Senza permuta");}
      if(FONTI.includes(i.fonte)){ch.fonte=i.fonte;L.push("Provenienza: "+i.fonte);}
      if(!L.length)throw new Error("Nessuna modifica indicata");
      const nota=str(i.aggiungi_nota);
      return W("Scheda di "+t.nome,L,t.id,cur=>({...cur,...ch,...(nota?{note:[cur.note,dayLabel(today())+": "+nota].filter(Boolean).join("\n")}:{})}));},
    appuntamento(i){const az=["crea","sposta","fatto","cancella"].includes(i.azione)?i.azione:"crea";const o=/^\d{1,2}:\d{2}$/.test(str(i.ora))?str(i.ora).padStart(5,"0"):"";const d=okDate(i.data);
      if(az==="crea"){if(!d)throw new Error("Serve la data AAAA-MM-GG");const con=str(i.con),cl=T().find(x=>(x.nome||"").toLowerCase()===con.toLowerCase());
        if(S.app[nuovoId])throw new Error("Appuntamento già creato");
        const v={tipo:APPT.includes(i.tipo)?i.tipo:"Appuntamento",con:cl?cl.nome:con,clienteId:cl?cl.id:null,telefono:str(i.telefono)||(cl&&cl.telefono)||"",data:d,ora:o,auto:str(i.auto)||(cl?[cl.marca,cl.modello].filter(Boolean).join(" "):""),note:str(i.note),fatto:false,creato:Date.now()};
        return W("In agenda: "+v.tipo+(v.con?" con "+v.con:""),[dayLabel(d)+(o?" ore "+o:""),v.auto,v.note],nuovoId,()=>v,"appuntamenti");}
      const k=str(i.id),a=S.app[k];if(!a)throw new Error("Nessun appuntamento con id "+i.id);
      if(az==="fatto")return W("Fatto: "+(a.tipo||"Appuntamento")+(a.con?" con "+a.con:""),[dayLabel(a.data)],k,cur=>({...cur,fatto:true}),"appuntamenti");
      if(az==="cancella")return W("Cancello: "+(a.tipo||"Appuntamento")+(a.con?" con "+a.con:""),[a.data?dayLabel(a.data)+(a.ora?" ore "+a.ora:""):""],k,cur=>({...cur,data:null,cancellato:true}),"appuntamenti");
      if(!d&&!o)throw new Error("Per spostare serve la nuova data o ora");
      return W("Sposto: "+(a.tipo||"Appuntamento")+(a.con?" con "+a.con:""),[(d?dayLabel(d):dayLabel(a.data))+(o?" ore "+o:a.ora?" ore "+a.ora:"")],k,cur=>({...cur,...(d?{data:d}:{}),...(o?{ora:o}:{})}),"appuntamenti");},
    prenota_test_drive(i){const t=find(i.id);const az=["fatto","cancella"].includes(i.azione)?i.azione:"prenota";
      if(az==="fatto")return W("Test drive fatto: "+t.nome,["Segnato come fatto"],t.id,cur=>({...cur,testDrive:true,tdData:null,tdOra:""}));
      if(az==="cancella")return W("Test drive cancellato: "+t.nome,["Prenotazione tolta"],t.id,cur=>({...cur,tdData:null,tdOra:""}));
      const d=okDate(i.data);if(!d)throw new Error("Serve la data in formato AAAA-MM-GG");const o=/^\d{1,2}:\d{2}$/.test(str(i.ora))?str(i.ora).padStart(5,"0"):"";
      return W("Test drive prenotato: "+t.nome,[dayLabel(d)+(o?" ore "+o:""),[t.marca,t.modello].filter(Boolean).join(" ")],t.id,cur=>({...cur,tdData:d,tdOra:o}));},
    registra_chiamata(i){const t=find(i.id);const r=okDate(i.prossimo_richiamo);
      return W("Chiamata a "+t.nome,["Esito: "+(str(i.esito)||"chiamato"),r?"Prossimo richiamo: "+dayLabel(r):"Nessun nuovo richiamo"],t.id,cur=>({...cur,contatti:[...contattiOf(cur),{data:today(),nota:str(i.esito)}],richiamo:r}));},
    segna_venduto(i){const t=find(i.id);const f=["fd","contanti","altro"].includes(i.formula)?i.formula:"fd";const mg=num(i.margine);if(mg==null)throw new Error("Serve il margine");
      const pz=num(i.prezzoVendita),ac=num(i.acconto);
      const prev={...t,formula:f,margine:Math.max(0,mg)};
      return W("Venduto a "+t.nome,[FORMS[f]+" · margine "+eur(mg)+" · ti frutta "+eur(earn(prev,piano())),pz!=null?"Prezzo "+eur(pz):"",ac>0?"Acconto "+eur(ac):""],t.id,
        cur=>({...cur,stato:"venduto",formula:f,margine:Math.max(0,mg),dataVendita:today(),richiamo:null,prezzoVendita:pz!=null?pz:(cur.prezzo||0),statoCliente:"da_saldare",pagamenti:ac>0?[...pays(cur),{tipo:"Acconto",importo:ac,data:today(),nota:""}]:pays(cur)}));},
    segna_perso(i){const t=find(i.id);const m=MOTIVI.includes(i.motivo)?i.motivo:"Altro";
      return W("Perso: "+t.nome,["Motivo: "+m,str(i.nota)],t.id,cur=>({...cur,stato:"perso",motivo:m,notaPerso:str(i.nota),dataPerso:today(),richiamo:null}));},
    riapri(i){const t=find(i.id);return W("Riapro "+t.nome,["Torna tra i preventivi aperti, richiamo domani"],t.id,cur=>{const v={...cur,stato:"aperto",richiamo:addDays(today(),1)};["dataVendita","formula","margine","dataPerso","motivo","notaPerso","statoCliente"].forEach(k=>delete v[k]);return v;});},
    aggiorna_cliente(i){const t=find(i.id);if(t.stato!=="venduto")throw new Error(t.nome+" non risulta venduto: prima va segnato come venduto");
      const ch={},L=[];
      if(CST[i.statoCliente]){ch.statoCliente=i.statoCliente;L.push("Stato: "+CST[i.statoCliente].l);}
      if(typeof i.avvisatoSaldo==="boolean"){ch.avvisatoSaldo=i.avvisatoSaldo;L.push(i.avvisatoSaldo?"Avvisato del saldo ✓":"Non avvisato del saldo");if(i.avvisatoSaldo&&finOf(t)&&finOf(t)!=="approvato"&&!i.statoFin){ch.statoFin="approvato";L.push("Finanziamento: Approvato");}}
      if(FST[i.statoFin]){if(!finOf(t))throw new Error("Vendita in contanti: niente finanziamento");ch.statoFin=i.statoFin;L.push("Finanziamento: "+FST[i.statoFin].l);}
      const imp=num(i.pagamento_importo);let pay=null;if(imp>0){pay={tipo:PAYT.includes(i.pagamento_tipo)?i.pagamento_tipo:"Altro",importo:imp,data:today(),nota:""};L.push(pay.tipo+" di "+eur(imp));}
      if(!L.length)throw new Error("Nessuna modifica indicata");
      return W("Cliente "+t.nome,L,t.id,cur=>({...cur,...ch,...(pay?{pagamenti:[...pays(cur),pay]}:{})}));}
  };
}

/* ---------- Esecuzione ---------- */

const ora = new Date().toISOString();
const ordini = Object.entries(leggiCollezione(path.join(dirOrdini, 'ordini')))
  .map(([id, o]) => ({ id, ...o }))
  .sort((a, b) => String(a.creato).localeCompare(String(b.creato)));

const scritture = {};
const esiti = [];
for (const o of ordini) {
  let esito;
  try {
    if (o.agente !== 'vendite') throw new Error('Agente non gestito: ' + o.agente);
    const ops = operazioni(String(o.nuovoId || ('p' + o.id)).replace(/[^A-Za-z0-9_-]/g, ''));
    const op = Object.prototype.hasOwnProperty.call(ops, o.operazione) ? ops[o.operazione] : null;
    if (!op) throw new Error('Operazione non permessa: ' + o.operazione);
    const r = op(o.argomenti || {});
    const mappa = S[MAPS[r.col]];
    const prima = mappa[r.id];
    const dopo = r.build(prima ? clona(prima) : {});
    delete dopo.id;
    mappa[r.id] = dopo;
    scritture[r.col + '/' + r.id] = { collezione: r.col, doc: r.id, esisteva: scritture[r.col + '/' + r.id] ? scritture[r.col + '/' + r.id].esisteva : !!prima };
    esito = { id: o.id, stato: 'eseguito', esito: r.titolo + (r.righe.length ? ' · ' + r.righe.join(' · ') : ''), collezione: r.col, doc: r.id };
  } catch (e) {
    esito = { id: o.id, stato: 'errore', esito: e.message };
  }
  esiti.push(esito);
}

// Documenti da scrivere in Andamento vendite e copie aggiornate dell'export, per il riepilogo di questo giro.
const risultato = { scritture: [], ordini: [] };
for (const w of Object.values(scritture)) {
  const doc = S[MAPS[w.collezione]][w.doc];
  const file = path.join(dirUscita, 'scritture', w.collezione, w.doc + '.json');
  scrivi(file, doc);
  scrivi(path.join(dirVendite, w.collezione, w.doc + '.json'), doc);
  risultato.scritture.push({ collezione: w.collezione, doc: w.doc, file, esisteva: w.esisteva });
}
for (const e of esiti) {
  const file = path.join(dirUscita, 'ordini', e.id + '.json');
  scrivi(file, { stato: e.stato, esito: e.esito, eseguito: ora });
  risultato.ordini.push({ id: e.id, stato: e.stato, esito: e.esito, file, scrittura: e.collezione ? e.collezione + '/' + e.doc : null });
}
scrivi(path.join(dirUscita, 'ordini-piano.json'), risultato);
console.log(JSON.stringify(risultato, null, 2));
