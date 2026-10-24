#!/data/data/com.termux/files/usr/bin/sh
# Ricollega ADB al telefono. Uso: sh scripts/telefono.sh PORTA
# PORTA = quella in Impostazioni > Opzioni sviluppatore > Debug wireless (Indirizzo IP e porta).
# Serve ogni volta che il wifi si spegne e si riaccende: la porta cambia.
[ -z "$1" ] && { echo "Uso: sh scripts/telefono.sh PORTA   (la porta dalla schermata Debug wireless)"; exit 1; }
adb connect "localhost:$1" || exit 1
adb tcpip 5555
sleep 3
adb connect localhost:5555
adb devices
