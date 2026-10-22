// Per le prove: con ORARIO_FINTO (ISO) gli script credono che sia quell'ora.
const Vero = Date;
const finto = process.env.ORARIO_FINTO;
if (finto) {
  global.Date = class extends Vero {
    constructor(...a) { super(...(a.length ? a : [finto])); }
    static now() { return new Vero(finto).getTime(); }
  };
}
