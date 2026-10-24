#!/data/data/com.termux/files/usr/bin/sh
# Installa l'avvio automatico di Ada dopo un riavvio del telefono.
mkdir -p "$HOME/.termux/boot"
cp "$(dirname "$0")/boot-ada.sh" "$HOME/.termux/boot/start-ada"
chmod +x "$HOME/.termux/boot/start-ada"
echo "Fatto: $HOME/.termux/boot/start-ada"
echo "Ora apri una volta l'app Termux:Boot (da F-Droid) e togli le restrizioni di batteria a Termux e Termux:Boot."
