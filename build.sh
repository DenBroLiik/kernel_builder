#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-or-later
# Original build script: Copyright (C) 2025 Julival Bittencourt.
# Русское меню сборки. Ничего не скачивает и не прошивает.
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
compiler=${COMPILER_PATH:-"$root/validation/clang-r563880c/bin"}
if [[ ! -x "$compiler/clang" && -x "$HOME/clang-r563880c/bin/clang" ]]; then
    compiler="$HOME/clang-r563880c/bin"
fi
usage() {
    echo 'Сборка Eclipse Daily для POCO X5 5G (семейство stone)'
    echo 'bash build.sh                 — интерактивное меню в терминале'
    echo 'bash build.sh --menu          — меню, в том числе с перенаправленным вводом'
    echo 'bash build.sh --build [путь]  — сборка и ZIP без вопросов'
    echo 'bash build.sh --config [путь] — только подготовка и проверка конфигурации'
    echo 'bash build.sh --package путь  — упаковка успешной сборки'
    echo 'bash build.sh --backup SERIAL — резервное копирование POCO через ADB'
    echo 'COMPILER_PATH — каталог LLVM; KSU_MODE=keep|y|n; JOBS — число потоков'
    echo 'Это экспериментальная сборка. Скрипт не прошивает телефон.'
}
details() {
    echo 'Повседневная конфигурация с возвращёнными функциями NEW function: внешние адаптеры, USB, сетевые диски и namespaces.'
    echo 'Сохранены штатные драйверы телефона, KernelSU, термозащиты, schedutil и zram.'
    echo 'Частоты, напряжения и зарядные токи не повышаются.'
    echo 'Загрузка, автономность и быстродействие требуют проверки на телефоне.'
}
action=build
out="$root/validation/stone-daily"
menu=0
case ${1:-} in
    --help|-h) usage; exit 0;;
    --menu) menu=1;;
    --build) out=${2:-$out};;
    --config) action=config; out=${2:-"$root/validation/stone-daily-config"};;
    --package) bash "$root/tools/package-stone.sh" "${2:?Укажите каталог сборки}"; exit $?;;
    --backup) bash "$root/tools/backup-stone.sh" "${2:?Укажите ADB serial POCO}"; exit $?;;
    '') [[ ! -t 0 ]] || menu=1;;
    --*) usage; exit 2;;
    *) out=$1;;
esac
if [[ "$menu" == 1 ]]; then
    while true; do
        echo
        echo '╔══ Eclipse Daily • POCO X5 5G ══╗'
        echo '  1. Настроить и собрать ядро + ZIP'
        echo '  2. Настроить и проверить конфигурацию без сборки'
        echo '  3. Упаковать уже готовую сборку'
        echo '  4. Сохранить резервную копию разделов POCO'
        echo '  5. Возможности и ограничения'
        echo '  0. Выход'
        read -r -p 'Выберите пункт [1]: ' choice || exit 0
        case "$choice" in
            1|'') action=build; break;;
            2) action=config; out="$root/validation/stone-daily-config"; break;;
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
if [[ "$action" == config ]]; then export CONFIG_ONLY=1; fi
bash "$root/tools/build-stone.sh" "$compiler" "$out"
[[ "$action" != config ]] || exit 0
bash "$root/tools/package-stone.sh" "$out"
