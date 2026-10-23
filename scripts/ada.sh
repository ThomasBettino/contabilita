#!/data/data/com.termux/files/usr/bin/sh
# Avvia l'hub di Ada. La chiave API sta fuori dal repo, in ~/.ada.env
cd "$(dirname "$0")/.." || exit 1
[ -f "$HOME/.ada.env" ] && . "$HOME/.ada.env"
exec python -m src.ada.server
