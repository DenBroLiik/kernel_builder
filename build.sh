#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-or-later
# Original build script: Copyright (C) 2025 Julival Bittencourt.
# Русское меню сборки. Ничего не скачивает и не прошивает.
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source "$root/tools/features.sh"
compiler=${COMPILER_PATH:-"$root/validation/clang-r563880c/bin"}
if [[ ! -x "$compiler/clang" && -x "$HOME/clang-r563880c/bin/clang" ]]; then
    compiler="$HOME/clang-r563880c/bin"
fi
usage() {
    echo 'Сборка Eclipse Multifunction для POCO X5 5G (семейство stone)'
    echo 'bash build.sh                 — интерактивное меню в терминале'
    echo 'bash build.sh --menu          — меню, в том числе с перенаправленным вводом'
    echo 'bash build.sh --build [путь]  — сборка и ZIP без вопросов'
    echo 'bash build.sh --config [путь] — только подготовка и проверка конфигурации'
    echo 'bash build.sh --package путь  — упаковка успешной сборки'
    echo 'bash build.sh --backup SERIAL — резервное копирование POCO через ADB'
    echo 'COMPILER_PATH — каталог LLVM; KSU_MODE=keep|y|n; JOBS — число потоков'
    echo 'FEATURE_USB_WIFI, FEATURE_USB_BLUETOOTH, FEATURE_NETFS,'
    echo 'FEATURE_CONTAINERS, FEATURE_USB_GADGET: 1 — включить, 0 — отключить.'
    echo 'Это экспериментальная сборка. Скрипт не прошивает телефон.'
}
details() {
    echo
    echo 'Дополнительные возможности:'
    for feature in "${feature_names[@]}"; do echo "  • $(feature_label "$feature")"; done
    echo 'Также: USB Ethernet/модемы/UART, аудио, камеры, накопители и геймпады.'
    echo 'Для HID/MIDI/ISO, сетевых дисков и профилей питания есть tools/phone-*.sh.'
    echo 'MEMCG и непривилегированные user namespaces остаются выключенными.'
    echo 'Частоты, напряжения, термолимиты и размер zram автоматически не меняются.'
    echo 'Драйверы не гарантируют поддержку внешнего Wi-Fi/Bluetooth штатными HAL Android.'
    echo
}
ask_toggle() {
    local name=$1 key=FEATURE_$1 answer hint
    hint=д/Н
    [[ ${!key} == 0 ]] || hint=Д/н
    while true; do
        read -r -p "$(feature_label "$name") [$hint]: " answer || exit 0
        case "$answer" in
            '') return 0;;
            д|Д|y|Y|1) export "$key=1"; return 0;;
            н|Н|n|N|0) export "$key=0"; return 0;;
            *) echo 'Введите д или н.';;
        esac
    done
}
action=build
out="$root/validation/stone-release"
menu=0
case ${1:-} in
    --help|-h) usage; exit 0;;
    --menu) menu=1;;
    --build) out=${2:-$out};;
    --config) action=config; out=${2:-"$root/validation/stone-config"};;
    --package) bash "$root/tools/package-stone.sh" "${2:?Укажите каталог сборки}"; exit $?;;
    --backup) bash "$root/tools/backup-stone.sh" "${2:?Укажите ADB serial POCO}"; exit $?;;
    '') [[ ! -t 0 ]] || menu=1;;
    --*) usage; exit 2;;
    *) out=$1;;
esac
if [[ "$menu" == 1 ]]; then
    while true; do
        echo
        echo '╔══ Eclipse Multifunction • POCO X5 5G ══╗'
        echo '  1. Настроить и собрать ядро + ZIP'
        echo '  2. Настроить и проверить конфигурацию без сборки'
        echo '  3. Упаковать уже готовую сборку'
        echo '  4. Сохранить резервную копию разделов POCO'
        echo '  5. Возможности и ограничения'
        echo '  0. Выход'
        read -r -p 'Выберите пункт [1]: ' choice || exit 0
        case "$choice" in
            1|'') action=build; break;;
            2) action=config; out="$root/validation/stone-config"; break;;
            3)
                read -r -p "Каталог готовой сборки [$out]: " answer || exit 0
                bash "$root/tools/package-stone.sh" "${answer:-$out}"
                exit $?;;
            4)
                echo 'Сначала найдите serial именно POCO командой adb devices -l.'
                read -r -p 'ADB serial POCO: ' answer || exit 0
                [[ -n "$answer" ]] || { echo 'Serial обязателен.'; continue; }
                bash "$root/tools/backup-stone.sh" "$answer"
                exit $?;;
            5) details;;
            0) exit 0;;
            *) echo 'Нет такого пункта.';;
        esac
    done
    echo
    read -r -p "Каталог LLVM-компилятора [$compiler]: " answer || exit 0
    compiler=${answer:-$compiler}
    echo 'KernelSU: 1 — настройки дерева; 2 — включить; 3 — отключить.'
    while true; do
        read -r -p 'Выберите KernelSU [1]: ' answer || exit 0
        case "$answer" in
            ''|1) export KSU_MODE=keep; break;;
            2) export KSU_MODE=y; break;;
            3) export KSU_MODE=n; break;;
            *) echo 'Введите 1, 2 или 3.';;
        esac
    done
    echo 'Дополнительные возможности (Enter сохраняет текущее значение):'
    for feature in "${feature_names[@]}"; do ask_toggle "$feature"; done
    read -r -p "Каталог результата [$out]: " answer || exit 0
    out=${answer:-$out}
    if [[ "$action" == build ]]; then
        max_jobs=$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 4)
        default_jobs=${JOBS:-8}
        [[ "$default_jobs" =~ ^[1-9][0-9]{0,2}$ ]] || default_jobs=8
        (( default_jobs <= max_jobs )) || default_jobs=$max_jobs
        while true; do
            read -r -p "Потоки сборки, от 1 до $max_jobs [$default_jobs]: " answer || exit 0
            answer=${answer:-$default_jobs}
            if [[ "$answer" =~ ^[1-9][0-9]*$ ]] && (( answer <= max_jobs )); then export JOBS=$answer; break; fi
            echo 'Укажите допустимое число потоков.'
        done
    fi
fi
[[ -x "$compiler/clang" ]] || { echo 'Компилятор не найден. Задайте COMPILER_PATH; подробности в README.md.' >&2; exit 1; }
echo
echo 'Выбранные возможности:'
for feature in "${feature_names[@]}"; do
    key=FEATURE_$feature
    state=выключено
    [[ ${!key} == 0 ]] || state=включено
    echo "  $(feature_label "$feature"): $state"
done
if [[ "$action" == config ]]; then export CONFIG_ONLY=1; fi
bash "$root/tools/build-stone.sh" "$compiler" "$out"
[[ "$action" != config ]] || exit 0
bash "$root/tools/package-stone.sh" "$out"
