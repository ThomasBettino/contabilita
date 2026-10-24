#!/data/data/com.termux/files/usr/bin/sh
# Riavvia Ada e dice subito se è partita; se no, mostra l'errore (stesso file di log: ~/ada.log).
cd "$(dirname "$0")/.." || exit 1
[ -f "$HOME/.ada.env" ] && . "$HOME/.ada.env"
PORTA="${ADA_PORT:-8765}"

# ferma la copia in corso: prima dal numero salvato da ada.sh (solo se è davvero Ada), poi per nome
if [ -f "$HOME/ada.pid" ]; then
  pid=$(cat "$HOME/ada.pid")
  if [ -r "/proc/$pid/cmdline" ] && tr '\0' ' ' < "/proc/$pid/cmdline" | grep -q "src.ada.server"; then kill "$pid" 2>/dev/null; fi
fi
command -v pkill > /dev/null 2>&1 && pkill -f "src.ada.server" 2>/dev/null
sleep 2

nohup sh scripts/ada.sh > "$HOME/ada.log" 2>&1 &
i=0
while [ "$i" -lt 15 ]; do
  sleep 1
  i=$((i + 1))
  # vale solo se il programma è vivo E la porta risponde (un'altra app sulla porta non basta)
  if kill -0 "$(cat "$HOME/ada.pid" 2> /dev/null)" 2> /dev/null \
     && python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:$PORTA/', timeout=2)" 2> /dev/null; then
    echo "Ada è partita. Apri http://localhost:$PORTA"
    exit 0
  fi
done
echo "Ada NON è partita. Ultime righe del log:"
tail -n 20 "$HOME/ada.log"
exit 1
