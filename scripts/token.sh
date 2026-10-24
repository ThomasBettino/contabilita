#!/data/data/com.termux/files/usr/bin/sh
# Crea il token di accesso di Ada (una volta sola), lo copia negli appunti senza mostrarlo e riavvia Ada.
# Il token sta in ~/.ada.env, fuori dal repo: non va condiviso con nessuno.
cd "$(dirname "$0")/.." || exit 1
[ -f "$HOME/.ada.env" ] && . "$HOME/.ada.env"
if [ -z "$ADA_TOKEN" ]; then
  ADA_TOKEN=$(head -c 18 /dev/urandom | base64 | tr -d '/+=')
  echo "export ADA_TOKEN=$ADA_TOKEN" >> "$HOME/.ada.env"
  chmod 600 "$HOME/.ada.env"
  echo "Token creato. Riavvio Ada..."
  sh scripts/riavvia.sh || exit 1
else
  echo "Il token c'era già: lo copio e basta."
fi
if printf %s "$ADA_TOKEN" | termux-clipboard-set 2> /dev/null; then
  echo "Token copiato negli appunti: incollalo quando Ada lo chiede (una volta sola)."
else
  echo "Non riesco a copiarlo negli appunti. Per vederlo: grep ADA_TOKEN ~/.ada.env"
fi
