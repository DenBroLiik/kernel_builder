#!/usr/bin/env bash
set -euo pipefail
config=${1:?Укажите путь к итоговой конфигурации ядра}
required=(
    USB_OTG USB_DWC3 USB_DWC3_MSM TCPC_CLASS TCPC_RT1711H
    CFG80211 QCA_CLD_WLAN MSM_BT_POWER USB_CONFIGFS
    USB_STORAGE USB_UAS SND_USB_AUDIO USB_VIDEO_CLASS
    VETH BRIDGE
    NET_SCH_FQ NET_SCH_DEFAULT DEFAULT_FQ TCP_CONG_BBR DEFAULT_BBR
    CPU_FREQ_GOV_SCHEDUTIL CPU_IDLE CC_OPTIMIZE_FOR_PERFORMANCE
    WIREGUARD TUN ZRAM ZRAM_WRITEBACK ZSMALLOC CRYPTO_ZSTD ZSTD_COMPRESS ZSTD_DECOMPRESS
    PSTORE PSTORE_RAM PSTORE_CONSOLE
    THERMAL THERMAL_TSENS QTI_BCL_PMIC5 QTI_BCL_SOC_DRIVER
    SECURITY_SELINUX SECCOMP SECCOMP_FILTER DM_VERITY FS_VERITY
    UNMAP_KERNEL_AT_EL0 HARDEN_BRANCH_PREDICTOR MITIGATE_SPECTRE_BRANCH_HISTORY
    ARM64_SSBD HARDEN_EL2_VECTORS LTO_CLANG THINLTO
    MAC80211 RTL8821CU ATH9K_HTC MT7601U MT76x0U MT76x2U RT2800USB
    BT_HCIBTUSB BT_ATH3K BT_RFCOMM BT_BNEP BT_HIDP
    CIFS NFS_FS SQUASHFS PID_NS IPC_NS CGROUP_PIDS CGROUP_DEVICE
    USB_SERIAL USB_ACM USB_PRINTER USB_NET_QMI_WWAN
    USB_CONFIGFS_F_HID USB_CONFIGFS_F_MIDI USB_CONFIGFS_MASS_STORAGE
)
disabled=(
    USB_EHSET_TEST_FIXTURE USB_LINK_LAYER_TEST USB_DUMMY_HCD THERMAL_EMULATION
    CIFS_ALLOW_INSECURE_LEGACY CIFS_WEAK_PW_HASH NFS_V2
    USER_NS MEMCG MEMCG_SWAP ANDROID_SIMPLE_LMK
    ZRAM_MEMORY_TRACKING
)
failed=0
if grep -qx 'CONFIG_KSU=y' "$config"; then
    if ! grep -qE '^CONFIG_KSU_(HACK_ARM64_BRANCH_LINK|TAMPER_SYSCALL_TABLE|KPROBES_KSUD)=y$' "$config"; then
        echo 'KernelSU включён без механизма хуков. В этом дереве ручные хуки не подключены; такая сборка не даст root.' >&2
        failed=1
    fi
    if ! grep -qx 'CONFIG_KSU_LSM_SECURITY_HOOKS=y' "$config"; then
        echo 'Для текущей интеграции KernelSU необходим CONFIG_KSU_LSM_SECURITY_HOOKS=y.' >&2
        failed=1
    fi
fi
for symbol in "${required[@]}"; do
    if ! grep -qx "CONFIG_$symbol=y" "$config"; then
        echo "Не включён обязательный параметр CONFIG_$symbol=y" >&2
        failed=1
    fi
done
for symbol in "${disabled[@]}"; do
    if grep -qE "^CONFIG_$symbol=[ym]$" "$config"; then
        echo "Небезопасный или неподдерживаемый параметр CONFIG_$symbol включён" >&2
        failed=1
    fi
done
for setting in 'CONFIG_DEFAULT_NET_SCH="fq"' 'CONFIG_DEFAULT_TCP_CONG="bbr"'; do
    if ! grep -qx "$setting" "$config"; then
        echo "Не соответствует сетевой профиль: $setting" >&2
        failed=1
    fi
done
(( failed == 0 )) || exit 1
echo "Проверки повседневной конфигурации и защит пройдены. Контроллер памяти MEMCG остаётся отключённым из-за неполной реализации в этом дереве."
