#!/bin/sh
set -eu

password="$(cat /keys/password)"
printf 'password:%s\nkey:%s\nagent:%s\n' "$password" "$password" "$password" | chpasswd
for user in key agent; do
    install -d -m 700 -o "$user" -g "$user" "/home/$user/.ssh"
    install -m 600 -o "$user" -g "$user" "/keys/$user.pub" "/home/$user/.ssh/authorized_keys"
done
exec /usr/sbin/sshd -D -e
