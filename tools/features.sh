#!/usr/bin/env bash
# Shared feature selection. All values are validated; no profile is evaluated.
feature_names=(USB_WIFI USB_BLUETOOTH NETFS CONTAINERS USB_GADGET)
feature_init() {
    local name key value
    for name in "${feature_names[@]}"; do
        key=FEATURE_$name
        value=${!key:-1}
        case "$value" in 0|1) ;; *) echo "Некорректное значение $key: требуется 0 или 1." >&2; return 1;; esac
        export "$key=$value"
    done
}
feature_symbols() {
    case "$1" in
        USB_WIFI) echo 'ATH9K_HTC CARL9170 AR5523 MT7601U MT76x0U MT76x2U RT2500USB RT73USB RT2800USB RTL8187 RTL8XXXU RTL8821CU';;
        USB_BLUETOOTH) echo 'BT_HCIBTUSB BT_ATH3K BT_RFCOMM BT_BNEP BT_HIDP';;
        NETFS) echo 'CIFS NFS_FS NFS_V3 NFS_V4 NFS_V4_1 NFS_V4_2 SQUASHFS SQUASHFS_LZ4 SQUASHFS_XZ SQUASHFS_ZSTD';;
        CONTAINERS) echo 'SYSVIPC POSIX_MQUEUE IPC_NS PID_NS CGROUP_PIDS CGROUP_DEVICE FHANDLE';;
        USB_GADGET) echo 'USB_CONFIGFS_F_HID USB_CONFIGFS_F_MIDI USB_CONFIGFS_MASS_STORAGE';;
        *) return 1;;
    esac
}
feature_label() {
    case "$1" in
        USB_WIFI) echo 'Внешние USB Wi-Fi, включая RTL8811CU AC600';;
        USB_BLUETOOTH) echo 'USB Bluetooth и дополнительные Bluetooth-протоколы';;
        NETFS) echo 'SMB3/NFS и сжатые образы SquashFS';;
        CONTAINERS) echo 'Пространства имён и cgroups для root-контейнеров';;
        USB_GADGET) echo 'Телефон как USB HID, MIDI и ISO-накопитель';;
    esac
}
feature_save() {
    local name key
    : > "$1"
    for name in "${feature_names[@]}"; do
        key=FEATURE_$name
        printf '%s=%s\n' "$key" "${!key}" >> "$1"
    done
}
feature_load() {
    local key value
    [[ -f "$1" ]] || return 0
    while IFS='=' read -r key value; do
        [[ -n "$key" ]] || continue
        case "$key" in FEATURE_USB_WIFI|FEATURE_USB_BLUETOOTH|FEATURE_NETFS|FEATURE_CONTAINERS|FEATURE_USB_GADGET) ;; *) echo 'Неизвестная настройка в профиле возможностей.' >&2; return 1;; esac
        case "$value" in 0|1) ;; *) echo 'Некорректное значение в профиле возможностей.' >&2; return 1;; esac
        export "$key=$value"
    done < "$1"
}
feature_apply() {
    local config=$1 editor=$2 name key action symbol
    for name in "${feature_names[@]}"; do
        key=FEATURE_$name
        action=--disable
        [[ ${!key} == 0 ]] || action=--enable
        for symbol in $(feature_symbols "$name"); do
            "$editor" --file "$config" --keep-case "$action" "$symbol"
        done
    done
}
feature_init
