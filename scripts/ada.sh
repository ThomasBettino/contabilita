#!/data/data/com.termux/files/usr/bin/sh
# Avvia l'hub di Ada. La chiave API sta fuori dal repo, in ~/.ada.env
cd "$(dirname "$0")/.." || exit 1
[ -f "$HOME/.ada.env" ] && . "$HOME/.ada.env"
echo $$ > "$HOME/ada.pid"  # exec tiene lo stesso numero: serve a riavvia.sh
exec python -u -m src.ada.server
