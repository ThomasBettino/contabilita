#!/data/data/com.termux/files/usr/bin/sh
# Parte da solo all'accensione del telefono (serve l'app Termux:Boot).
# Si copia in ~/.termux/boot/ con: sh scripts/installa-boot.sh
termux-wake-lock
cd "$HOME/contabilita" || exit 1
nohup sh scripts/ada.sh > "$HOME/ada.log" 2>&1 &
