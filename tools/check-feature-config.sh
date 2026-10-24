#!/usr/bin/env bash
set -euo pipefail
config=${1:?Укажите путь к итоговой конфигурации ядра}
source "$(dirname -- "${BASH_SOURCE[0]}")/features.sh"
if [[ -n ${2:-} ]]; then feature_load "$2"; fi
required=(
    USB_OTG USB_DWC3 USB_DWC3_MSM TCPC_CLASS TCPC_RT1711H
    CFG80211 QCA_CLD_WLAN MSM_BT_POWER USB_CONFIGFS
    USB_STORAGE USB_UAS SND_USB_AUDIO USB_VIDEO_CLASS
    VETH BRIDGE
    WIREGUARD TUN ZRAM PSTORE PSTORE_RAM PSTORE_CONSOLE
    THERMAL THERMAL_TSENS QTI_BCL_PMIC5 QTI_BCL_SOC_DRIVER
    SECURITY_SELINUX SECCOMP SECCOMP_FILTER DM_VERITY FS_VERITY
    UNMAP_KERNEL_AT_EL0 HARDEN_BRANCH_PREDICTOR MITIGATE_SPECTRE_BRANCH_HISTORY
    ARM64_SSBD HARDEN_EL2_VECTORS LTO_CLANG THINLTO
)
disabled=(
    USB_EHSET_TEST_FIXTURE USB_LINK_LAYER_TEST USB_DUMMY_HCD THERMAL_EMULATION
    CIFS_ALLOW_INSECURE_LEGACY CIFS_WEAK_PW_HASH NFS_V2
    USER_NS MEMCG MEMCG_SWAP ANDROID_SIMPLE_LMK
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
for name in "${feature_names[@]}"; do
    key=FEATURE_$name
    for symbol in $(feature_symbols "$name"); do
        if [[ ${!key} == 1 ]]; then
            if ! grep -qx "CONFIG_$symbol=y" "$config"; then
                echo "Выбрана возможность $name, но CONFIG_$symbol не включён." >&2
                failed=1
            fi
        elif grep -qE "^CONFIG_$symbol=[ym]$" "$config"; then
            echo "Возможность $name отключена, но CONFIG_$symbol остался включён." >&2
            failed=1
        fi
    done
done
(( failed == 0 )) || exit 1
echo "Проверки возможностей и защит пройдены. Контроллер памяти MEMCG остаётся отключённым из-за неполной реализации в этом дереве."
