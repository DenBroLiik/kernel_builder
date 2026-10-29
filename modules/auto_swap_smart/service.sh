#!/system/bin/sh
# Auto Swap Smart v2.1.0 — KernelSU late_start service.
# This module MUST NOT reset, swapoff, or reconfigure Android-managed zram.

MODDIR=${0%/*}
SWAPFILE=/data/local/tmp/swapfile
SIZE_MIB=2048
SIZE_BYTES=2147483648
OLD_SIZE_BYTES=4294967296
LOGFILE="$MODDIR/swap.log"
STATEFILE="$MODDIR/zram.state"
CONFIG="$MODDIR/config.conf"
TEMPFILE=
BACKUPFILE=
BACKUP_OWNED=0
NEW_ZRAM_ID=
MODE=auto
BB=/data/adb/ksu/bin/busybox
SWAPON=/system/bin/swapon
STAGEDIR=/data/local/tmp/.auto_swap_smart
umask 077

log() {
    [ -f "$LOGFILE" ] && [ "$(wc -c < "$LOGFILE" 2>/dev/null)" -gt 65536 ] 2>/dev/null && mv -f "$LOGFILE" "$LOGFILE.1"
    printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOGFILE"
}

# Parse configuration without sourcing it (no arbitrary shell execution).
if [ -f "$CONFIG" ]; then
    while IFS='=' read -r key value || [ -n "$key" ]; do
        case "$key" in
            MODE) case "$value" in auto|file|zram) MODE=$value ;; esac ;;
        esac
    done < "$CONFIG"
fi

# Kernel-owned file lock: no PID reuse, stale-boot cleanup, or mkdir race.
[ -x "$BB" ] && [ -x "$SWAPON" ] || { log 'ERROR: KernelSU BusyBox or Android swapon unavailable'; exit 1; }
[ "$("$BB" id -u)" = 0 ] || { log 'ERROR: root is required'; exit 1; }
[ ! -L "$MODDIR/.run.lock" ] || exit 1
exec 9>"$MODDIR/.run.lock"
"$BB" flock -n 9 || { log 'Another instance is running'; exit 0; }
BOOT_ID=$(cat /proc/sys/kernel/random/boot_id 2>/dev/null)
[ -n "$BOOT_ID" ] || { log 'ERROR: cannot establish boot identity'; exit 1; }

cleanup() {
    if [ -n "$TEMPFILE" ] && ! is_active "$TEMPFILE"; then rm -f "$TEMPFILE"; fi
    if [ "$BACKUP_OWNED" = 1 ] && [ -n "$BACKUPFILE" ] && [ -f "$BACKUPFILE" ] && \
       [ ! -e "$SWAPFILE" ] && ! is_active "$BACKUPFILE"; then
        mv "$BACKUPFILE" "$SWAPFILE" || log 'ERROR: failed to restore legacy swapfile'
    fi
    release_failed_zram
}
# Install traps only after cleanup helpers have been defined below.

# Ensure Android has mounted/decrypted /data before accessing persistent files.
i=0
while [ "$i" -lt 30 ]; do
    [ -d /data/local/tmp ] && [ -r /proc/swaps ] && \
        command -v mkswap >/dev/null 2>&1 && \
        command -v swapon >/dev/null 2>&1 && break
    sleep 2
    i=$((i + 1))
done
if [ "$i" -eq 30 ]; then
    log 'ERROR: /data or swap tools unavailable'
    exit 1
fi

# Let init finish Android's own zram setup before selecting a backend.
# This runs in a non-blocking KernelSU service, not a blocking boot hook.
if command -v getprop >/dev/null 2>&1; then
    i=0
    while [ "$i" -lt 45 ] && [ "$(getprop sys.boot_completed 2>/dev/null)" != 1 ]; do
        sleep 2
        i=$((i + 1))
    done
    if [ "$i" -ge 45 ]; then log 'ERROR: boot not complete; leaving Android swap setup alone'; exit 1; fi
fi

is_active() {
    # The path is literal and contains no spaces.
    awk -v target="$1" 'NR > 1 && $1 == target { found=1 } END { exit !found }' /proc/swaps
}

bytes_of() {
    stat -c %s "$1" 2>/dev/null
}

swap_signature() {
    # The SWAPSPACE2 header is stored at the end of the page (4K/16K/64K).
    path=$1
    for offset in 4086 16374 65526; do
        [ "$(dd if="$path" bs=1 skip="$offset" count=10 2>/dev/null)" = SWAPSPACE2 ] && return 0
    done
    return 1
}

available_kib() {
    df -k /data 2>/dev/null | awk 'END { if (NF >= 4) print $(NF-2); else print 0 }'
}

activate() {
    target=$1
    priority=$2
    if [ "$priority" = default ]; then
        "$SWAPON" "$target" >> "$LOGFILE" 2>&1 || return 1
    else
        "$SWAPON" -p "$priority" "$target" >> "$LOGFILE" 2>&1 || return 1
    fi
    if ! is_active "$target"; then log "ERROR: activation not visible for $target"; return 1; fi
    actual=$(awk -v target="$target" 'NR>1 && $1==target {print $5}' /proc/swaps)
    log "Verified active swap: $target, priority=$actual"
    return 0
}

file_priority() {
    # Linux accepts explicit nonnegative priorities. Never pass a negative
    # value to -p: it can be rejected or interpreted as a high unsigned value.
    lowest=$(awk 'NR>1 && $1 ~ /\/zram[0-9]+$/ {if (!found || $5<lowest) lowest=$5; found=1} END {if (found) print lowest; else print 1}' /proc/swaps)
    if [ "$lowest" -gt 0 ]; then echo 0; else echo default; fi
}

verify_file_priority() {
    awk -v target="$SWAPFILE" '
        NR>1 && $1==target {disk=$5; seen=1}
        NR>1 && $1 ~ /\/zram[0-9]+$/ {if (!ram || $5<lowest) lowest=$5; ram=1}
        END {exit !(seen && (!ram || disk<lowest))}' /proc/swaps
}

# Previously created by this module during the same boot.
if [ -f "$STATEFILE" ]; then
    IFS=' ' read -r SAVED_BOOT SAVED_DEV < "$STATEFILE"
    if [ -n "$BOOT_ID" ] && [ "$SAVED_BOOT" = "$BOOT_ID" ] && \
       [ -n "$SAVED_DEV" ] && is_active "$SAVED_DEV"; then
        log "Managed zram still active: $SAVED_DEV"
        exit 0
    fi
fi

# Never swapoff an active 4GiB legacy file. Doing so under load can OOM.
if is_active "$SWAPFILE"; then
    file_bytes=$(bytes_of "$SWAPFILE")
    if [ "$file_bytes" = "$SIZE_BYTES" ]; then
        log '2GiB swapfile already active; nothing to do'
        exit 0
    fi
    log "WARN: $SWAPFILE already active ($file_bytes bytes). Reboot to migrate safely."
    exit 0
fi

# Do not overwrite unknown or symlinked files at the legacy path.
if [ -L "$SWAPFILE" ]; then
    log "ERROR: unexpected symlink at $SWAPFILE; refusing to modify"
    exit 1
fi
if [ -f "$SWAPFILE" ]; then
    existing_size=$(bytes_of "$SWAPFILE")
    case "$existing_size" in
        "$SIZE_BYTES"|"$OLD_SIZE_BYTES")
            if ! swap_signature "$SWAPFILE"; then
                log 'ERROR: existing file has no valid swap header; refusing to overwrite'
                exit 1
            fi
            ;;
        *)
            log "ERROR: unexpected existing file size ($existing_size); refusing to overwrite"
            exit 1
            ;;
    esac
fi

# If Android already has zram, do not add another one by default.
existing_zram=$(awk 'NR > 1 && $1 ~ /\/zram[0-9]+$/ { print $1; exit }' /proc/swaps)

create_zram() {
    control=/sys/class/zram-control/hot_add
    [ -r "$control" ] || { log 'ZRAM dynamic creation is unavailable'; return 1; }

    id=$(cat "$control" 2>/dev/null) || return 1
    case "$id" in
        ''|*[!0-9]*) log "ERROR: invalid new zram id: $id"; return 1 ;;
    esac
    NEW_ZRAM_ID=$id
    sysdev="/sys/block/zram$id"
    node=
    k=0
    while [ "$k" -lt 10 ]; do
        if [ -b "/dev/block/zram$id" ]; then node="/dev/block/zram$id"; break; fi
        if [ -b "/dev/zram$id" ]; then node="/dev/zram$id"; break; fi
        sleep 1
        k=$((k + 1))
    done
    if [ -z "$node" ] || [ ! -w "$sysdev/disksize" ]; then
        log "ERROR: no usable node for zram$id"
        release_failed_zram
        return 1
    fi
    if [ -w "$sysdev/comp_algorithm" ]; then
        if grep -qw lz4 "$sysdev/comp_algorithm"; then
            if echo lz4 > "$sysdev/comp_algorithm" 2>/dev/null; then
                log 'Selected LZ4 compression for new zram'
            else
                log 'LZ4 selection rejected; using kernel default'
            fi
        else
            log 'LZ4 not supported; using kernel default compressor'
        fi
    fi
    if ! echo "$SIZE_BYTES" > "$sysdev/disksize" 2>/dev/null || \
       ! mkswap "$node" >> "$LOGFILE" 2>&1 || \
       ! activate "$node" 100; then
        log "ERROR: unable to initialize zram$id"
        release_failed_zram
        return 1
    fi
    printf '%s %s\n' "$BOOT_ID" "$node" > "$STATEFILE"
    NEW_ZRAM_ID=
    log "Enabled 2GiB compressed zram: $node"
    return 0
}

release_failed_zram() {
    [ -n "$NEW_ZRAM_ID" ] || return 0
    # Only the newly created, inactive device is eligible for removal.
    if ! is_active "/dev/zram$NEW_ZRAM_ID" && \
       ! is_active "/dev/block/zram$NEW_ZRAM_ID" && \
       [ -w /sys/class/zram-control/hot_remove ]; then
        [ -w "/sys/block/zram$NEW_ZRAM_ID/reset" ] && \
            echo 1 > "/sys/block/zram$NEW_ZRAM_ID/reset" 2>/dev/null
        echo "$NEW_ZRAM_ID" > /sys/class/zram-control/hot_remove 2>/dev/null
    fi
    NEW_ZRAM_ID=
}

trap cleanup EXIT
trap 'exit 1' HUP INT TERM

migrate_old_file() {
    [ -f "$SWAPFILE" ] || return 0
    [ "$(bytes_of "$SWAPFILE")" = "$OLD_SIZE_BYTES" ] || return 0
    # Validated above; never delete an active swap file.
    if is_active "$SWAPFILE"; then
        log 'ERROR: legacy file became active during migration'
        return 1
    fi
    if ! rm -f "$SWAPFILE"; then
        log 'ERROR: failed to remove inactive legacy 4GiB swapfile'
        return 1
    fi
    log 'Removed verified inactive 4GiB swapfile for 2GiB migration'
    return 0
}

if [ "$MODE" != file ] && { [ "$MODE" = zram ] || [ -z "$existing_zram" ]; }; then
    if create_zram; then
        migrate_old_file || log 'WARN: could not clean up old inactive swapfile'
        exit 0
    fi
    [ "$MODE" = zram ] && { log 'ERROR: ZRAM mode requested, no disk fallback'; exit 1; }
fi

# Legacy 4 GiB disk files remain intact until a replacement is ready.
# Recover a migration interrupted between the two renames.
if [ -L "$STAGEDIR" ]; then log 'ERROR: staging directory is a symlink'; exit 1; fi
if [ -d "$STAGEDIR" ] && [ "$(stat -c %u "$STAGEDIR")" != 0 ]; then
    log 'ERROR: staging directory is not root-owned'; exit 1
fi
mkdir -p "$STAGEDIR" || exit 1
chmod 700 "$STAGEDIR" || exit 1
BACKUPFILE="$STAGEDIR/previous.swap"
if [ -L "$BACKUPFILE" ]; then log 'ERROR: backup is a symlink'; exit 1; fi
if [ -e "$BACKUPFILE" ]; then
    if [ ! -e "$SWAPFILE" ] && ! is_active "$BACKUPFILE" && \
       [ "$(bytes_of "$BACKUPFILE")" = "$OLD_SIZE_BYTES" ] && swap_signature "$BACKUPFILE"; then
        mv "$BACKUPFILE" "$SWAPFILE" || exit 1
    else
        log 'ERROR: migration backup needs inspection; no file changed'; exit 1
    fi
fi

# Existing validated 2GiB swapfile: activate, never recreate.
if [ -f "$SWAPFILE" ] && [ "$(bytes_of "$SWAPFILE")" = "$SIZE_BYTES" ]; then
    chmod 600 "$SWAPFILE" 2>/dev/null
    if activate "$SWAPFILE" "$(file_priority)"; then
        verify_file_priority || { log 'ERROR: file priority is not below zram; active file retained'; exit 1; }
        log "Enabled existing 2GiB swapfile: $SWAPFILE"
        exit 0
    fi
    log 'ERROR: existing 2GiB swapfile rejected by kernel; no destructive retry'
    exit 1
fi

# Leave 256MiB spare. Disk files need real allocated blocks (no sparse files).
available=$(available_kib)
case "$available" in ''|*[!0-9]*) available=0 ;; esac
if [ "$available" -lt 2359296 ]; then
    log "ERROR: insufficient free /data space ($available KiB, need >=2359296 KiB)"
    exit 1
fi

mkdir -p /data/local/tmp || exit 1
TEMPFILE="$STAGEDIR/new.swap"
umask 077

create_and_activate_file() {
    method=$1
    # The staging directory is root-only; refuse interrupted/unknown files.
    [ ! -e "$TEMPFILE" ] && [ ! -L "$TEMPFILE" ] || { log 'ERROR: staging file exists'; TEMPFILE=; exit 1; }
    case "$method" in
        fallocate)
            command -v fallocate >/dev/null 2>&1 || return 1
            fallocate -l "$SIZE_BYTES" "$TEMPFILE" >> "$LOGFILE" 2>&1 || { rm -f "$TEMPFILE"; return 1; }
            ;;
        dd)
            # Lower CPU priority, allocate real blocks and flush before mkswap.
            nice -n 19 dd if=/dev/zero of="$TEMPFILE" bs=1048576 count="$SIZE_MIB" conv=fsync >> "$LOGFILE" 2>&1 || { rm -f "$TEMPFILE"; return 1; }
            ;;
    esac
    [ "$(bytes_of "$TEMPFILE")" = "$SIZE_BYTES" ] || { rm -f "$TEMPFILE"; return 1; }
    chmod 600 "$TEMPFILE" || return 1
    mkswap "$TEMPFILE" >> "$LOGFILE" 2>&1 || return 1
    swap_signature "$TEMPFILE" || return 1
    if [ -e "$SWAPFILE" ] || [ -L "$SWAPFILE" ]; then
        # Recheck immediately before replacement. Never replace live swap.
        if [ -L "$SWAPFILE" ] || is_active "$SWAPFILE" || \
           [ "$(bytes_of "$SWAPFILE")" != "$OLD_SIZE_BYTES" ] || ! swap_signature "$SWAPFILE"; then
            log 'ERROR: destination changed or became active'; return 1
        fi
        mv "$SWAPFILE" "$BACKUPFILE" || return 1
        BACKUP_OWNED=1
    fi
    mv "$TEMPFILE" "$SWAPFILE" || return 1
    TEMPFILE=
    if activate "$SWAPFILE" "$(file_priority)"; then
        verify_file_priority || { log 'ERROR: priority check failed; live swap/backup retained'; exit 1; }
        if [ -f "$BACKUPFILE" ] && ! is_active "$BACKUPFILE"; then rm -f "$BACKUPFILE"; fi
        BACKUPFILE=
        BACKUP_OWNED=0
        log "Enabled verified 2GiB disk swap ($method): $SWAPFILE"
        return 0
    fi
    log "WARN: kernel rejected $method swapfile"
    if is_active "$SWAPFILE"; then log 'ERROR: swap active despite tool failure; retaining files'; exit 1; fi
    rm -f "$SWAPFILE"
    if [ -f "$BACKUPFILE" ]; then mv "$BACKUPFILE" "$SWAPFILE" || exit 1; BACKUP_OWNED=0; fi
    TEMPFILE="$STAGEDIR/new.swap"
    return 1
}

if create_and_activate_file fallocate; then exit 0; fi
cleanup
TEMPFILE="$STAGEDIR/new.swap"
if create_and_activate_file dd; then exit 0; fi
log 'ERROR: both fallocate and dd swapfile attempts failed; check F2FS and kernel swap support'
exit 1
