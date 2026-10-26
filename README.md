# Eclipse Daily для POCO X5 5G

Ядро Linux 5.4.304 для семейства stone/moonstone/sunstone и совместимых AOSP ROM.
Новая конфигурация ещё не проверена на телефоне. Установщик сохраняет ограничения
на устройство и версии Android; сборщик ничего не прошивает.

Удалены дополнения из коммита `132e475606fb` отдельного репозитория `kernel`:
внешние Wi-Fi/Bluetooth, дополнительные USB-модемы/UART/принтеры, SMB/NFS/SquashFS
и контейнерные функции. Также отключены HID/MIDI/ISO gadget-функции и удалены
скрипты их настройки. Штатные ADB/MTP и драйверы телефона сохраняются.

Сохранены KernelSU с исправлением хуков, ARM64 mitigations, термозащиты,
SELinux, schedutil, idle, ThinLTO, zram/writeback, WireGuard и штатные частоты.
Тестовые USB-контроллеры, thermal emulation и Simple LMK отключены.
Отладочный ZRAM_MEMORY_TRACKING отключён: на ARM64 убирается 8-байтная временная
метка для каждой логической страницы zram и её обновление при обращении.
При страницах 4 KiB это около 2 MiB таблицы на 1 GiB логического размера zram.
Idle marking и writeback имеют реализацию без tracking и сохраняются.
Изменение автономности/скорости на устройстве не измерялось.

## Сборка

Нужны Linux x86_64, Android Clang r563880c, gcc, make, flex, bison,
OpenSSL development headers, bc, dtc, zip/unzip.

```sh
bash build.sh                          # русское меню
bash build.sh --config                 # итоговая конфигурация и проверки
JOBS=4 bash build.sh --build            # ядро и ZIP
KSU_MODE=n JOBS=4 bash build.sh --build # явно без KernelSU
bash tests/test-tools.sh validation/stone-daily/.config
```

Компилятор: `validation/clang-r563880c/bin` или `COMPILER_PATH`.
KernelSU: `KSU_MODE=keep|y|n`; по умолчанию настройки дерева.
Результаты: `validation/stone-daily`, ZIP и SHA256: `artifacts/`.
Старые сборки сохраняются. Упаковка проверяет итоговую конфигурацию, контрольные
суммы и соответствие исходникам. ZIP помечен EXPERIMENTAL до проверки загрузки.

## Проверка на телефоне

До установки сохранить подходящие прошивке boot/DTBO и проверить доступ в recovery.
`bash tools/backup-stone.sh SERIAL` читает резервные копии через ADB при наличии root.
После установки проверить загрузку, root, связь/Wi-Fi/Bluetooth, камеру, звук,
зарядку, сон/пробуждение, затем сравнить нагрев и расход батареи в одинаковых условиях.
`tools/phone-report.sh` собирает диагностический отчёт без настройки частот.

## Переход на 6.x

См. `kernel/Documentation/stone-daily.md`. Это отдельный перенос аппаратной
поддержки и согласование с ROM, а не смена номера версии или установка GKI ZIP.
