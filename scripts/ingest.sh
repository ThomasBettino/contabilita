#!/data/data/com.termux/files/usr/bin/sh
# Lanciato in automatico da termux-job-scheduler: legge le notifiche Revolut.
# Il database sta nella home, fuori dal repo, così git non lo tocca mai.
cd "$HOME/contabilita" || exit 1
echo "--- $(date '+%Y-%m-%d %H:%M:%S')" >> "$HOME/ingest.log"
python -m src.revolut.ingest --db "$HOME/movimenti.db" >> "$HOME/ingest.log" 2>&1
