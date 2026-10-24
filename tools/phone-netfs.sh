#!/system/bin/sh
set -eu
fail() { echo "ERROR: $*" >&2; exit 1; }
usage() { echo "Usage: sh phone-netfs.sh smb //host/share name /absolute/credentials | nfs host:/export name | unmount name"; }
case ${1:-} in --help|help|-h|'') usage; exit 0;; esac
[ "$(id -u)" = 0 ] || fail "Root is required; run in the Android host mount namespace."
command -v getprop >/dev/null 2>&1 || fail "Run on the phone."
case $(getprop ro.product.device) in stone|moonstone|sunstone) ;; *) fail "Wrong device family.";; esac
if [ "$1" = unmount ]; then name=${2:-}; else name=${3:-}; fi
case "$name" in ''|.|..|*[!a-zA-Z0-9_-]*) fail "Mount name must contain only letters, numbers, _ or -.";; esac
dest=/mnt/stone-shares/$name
if [ "$1" = unmount ]; then umount "$dest"; rmdir "$dest"; exit 0; fi
source=${2:-}
case "$source" in *[!a-zA-Z0-9._:/-]*|'') fail "Use an ASCII host/share path without mount option characters.";; esac
case "$1" in
    smb)
        case "$source" in //?*/?*) ;; *) fail "Expected //host/share.";; esac
        command -v mount.cifs >/dev/null 2>&1 || fail "Install cifs-utils (mount.cifs) in the rooted environment first."
        creds=${4:-}
        case "$creds" in /*) ;; *) fail "Use an absolute credentials-file path.";; esac
        case "$creds" in *[!a-zA-Z0-9_./-]*) fail "Unsupported credentials path characters.";; esac
        [ -f "$creds" ] && [ ! -L "$creds" ] || fail "Credentials must be a regular non-symlink file."
        [ "$(stat -c %u "$creds")" = 0 ] || fail "Credentials must be owned by root."
        case $(stat -c %a "$creds") in 400|600) ;; *) fail "Credentials permissions must be 400 or 600.";; esac;;
    nfs)
        case "$source" in ?*:/?*) ;; *) fail "Expected host:/export.";; esac
        command -v mount.nfs >/dev/null 2>&1 || fail "Install nfs-utils (mount.nfs) in the rooted environment first.";;
    *) usage; exit 2;;
esac
# mkdir must fail on a pre-existing path, including an existing mount/symlink.
mkdir -p /mnt/stone-shares
mkdir "$dest" || fail "Destination already exists."
if [ "$1" = smb ]; then
    mount.cifs "$source" "$dest" -o "credentials=$creds,vers=3.0,seal,ro,nosuid,nodev,noexec" || { rmdir "$dest"; exit 1; }
else
    mount.nfs "$source" "$dest" -o ro,nosuid,nodev,noexec,vers=4 || { rmdir "$dest"; exit 1; }
fi
echo "Read-only share mounted at $dest. Access from apps depends on SELinux and mount namespace."
