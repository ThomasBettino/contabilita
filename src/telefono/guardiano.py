"""Filtro di sicurezza sulle azioni di Ada sullo schermo. Sta nel codice: nessun prompt lo cambia.

- Il tasto finale di acquisto/pagamento non lo preme mai Ada: lo preme l'utente.
- Carrello e cassa si toccano solo con l'autorizzazione dell'utente (tasto nell'app).
- App finanziarie, di autenticazione e password: Ada non le legge e non le tocca.
- Mai password né numeri di carta/IBAN digitati.
"""
import re

I = re.IGNORECASE

# Mai toccare: tasti che concludono un acquisto o un pagamento.
VIETATI = re.compile(
    r"\bacquista ora\b|\bcompra ora\b|\bacquista con 1-?click\b|\bordina con 1-?click\b|\b1-?click\b"
    r"|\beffettua l.ordine\b|\bconferma (l.)?ordine\b|\bconferma e paga\b|\bordina (ora|adesso)\b"
    r"|\bplace your order\b|\bbuy now\b|\bpaga( ora| adesso)?\b|\bpay( now)?\b|\binvia denaro\b"
    r"|\bsend money\b|\btrasferisci\b|\bconferma (il )?pagamento\b|\bbonifico\b"
    r"|buy-?now|one-?click|place-?order|submit\.buy|pyo-button|confirm-?order|pay-?now", I)

# Se compaiono sulla schermata, siamo alla fine dell'ordine: Ada non tocca più niente.
FINALI = re.compile(
    r"\beffettua l.ordine\b|\bplace your order\b|\bconferma (l.)?ordine\b|\bconferma e paga\b"
    r"|\bordina (ora|adesso)\b|\bpaga( ora| adesso)?\b|\bpay now\b|\bconferma (il )?pagamento\b"
    r"|\binvia denaro\b|\bsend money\b|place-?order|submit\.buy|pyo-button|confirm-?order", I)

# Si toccano solo dopo l'ok dell'utente.
PRIMA_DELL_OK = re.compile(
    r"\baggiungi al carrello\b|\badd to cart\b|\bprocedi all.ordine\b|\bvai alla cassa\b"
    r"|\bproceed to checkout\b|\bprocedi al checkout\b|\bimposta ordine\b|add-?to-?cart|proceed-?to-?retail", I)

PROTETTE = re.compile(
    r"revolut|paypal|bank|banc|intesa|unicredit|\bbnl\b|poste|authenticator|bitwarden|1password|lastpass"
    r"|keepass|samsungpass|wallet|satispay|nexi|\bn26\b|hype|fineco|mediolanum|widiba|isybank|googlepay", I)

CARTA_O_IBAN = re.compile(r"[\d\s-]{13,23}|[A-Za-z]{2}\d{2}[A-Za-z0-9]{11,30}")


def app_protetta(pacchetto: str) -> bool:
    return bool(PROTETTE.search(pacchetto or ""))


def _campi(e):
    return f"{e.testo} {e.desc} {e.rid}"


def schermata_finale(elementi) -> bool:
    return any(FINALI.search(_campi(e)) for e in elementi)


def valuta_tocco(e, elementi, autorizzato: bool):
    """Restituisce il motivo del rifiuto, oppure None se il tocco è consentito."""
    if schermata_finale(elementi):
        return ("Questa è la schermata finale dell'ordine o del pagamento: fermati. "
                "Il tasto finale lo preme l'utente, tu non tocchi più nulla qui.")
    if VIETATI.search(_campi(e)):
        return "Questo tasto conclude un acquisto o un pagamento: lo preme l'utente, non tu."
    if PRIMA_DELL_OK.search(_campi(e)) and not autorizzato:
        return ("Carrello e cassa si toccano solo dopo l'autorizzazione dell'utente "
                "(tasto 'Autorizza' nell'app). Proponi prima le opzioni con proponi_acquisto.")
    return None


def valuta_digitazione(e, testo: str):
    if e.password:
        return "Non scrivo nei campi password."
    if CARTA_O_IBAN.fullmatch(testo.strip()):
        return "Non digito numeri di carta, IBAN o codici di pagamento."
    return None
