# POCO X5 5G: состояние перехода на Linux 6.x

Текущий результат — очистка Linux 5.4.304. Порт 6.x не выполнен.

## Проверенная кандидатная база

Официальная ветка Xiaomi `spring-v-oss`:
https://github.com/MiCode/Xiaomi_Kernel_OpenSource/tree/spring-v-oss

Проверенное дерево API: `e29c0fd34c6e8f91d30046a85d1afac3fe032a7e`.
Makefile содержит VERSION=6, PATCHLEVEL=1, SUBLEVEL=93.
Фрагмент spring_GKI.config включает ARCH_BLAIR и ARCH_HOLI; основные аппаратные
драйверы собираются модулями. Это база для другого устройства, а не готовый порт X5.

`build.config.msm.spring` требует boot header v4, init_boot,
BUILD_VENDOR_DLKM=1 и PREPARE_SYSTEM_DLKM=1. Наш текущий AnyKernel устанавливает
ядро/DTB/DTBO в существующую схему, имеет do.modules=0, а конфигурация 5.4
использует встроенные драйверы. Простая подмена Image оставит новую базу без
необходимого набора драйверов и не согласует интерфейсы с установленной ROM.

Device tree Xiaomi:
https://github.com/MiCode/kernel_devicetree/tree/spring-v-oss

SHA `7736353f52d97fdd7f169b27af0d30aa79cd3d37`. Полный список дерева получен без
усечения: есть spring-sm6375-overlay.dts, spring-sm6375.dtsi и
longcheer-sm6375-common.dtsi; файлов moonstone/sunstone нет.
Рекурсивный ответ API самого ядра усечён, поэтому отсутствие moonstone во всём
репозитории ядра по этому ответу не утверждается.

Исходные ответы API и проверенные файлы сохранены в validation/spring-*-tree.json
и validation/port-6.1-audit/ как локальные материалы исследования.

## Что требуется для настоящего порта

1. Получить ROM device/vendor trees и данные реального X5: boot layout, dtb/dtbo,
   загружаемые модули, firmware, VINTF и журналы исходной рабочей системы.
2. Подготовить отдельное дерево 6.1 и полный Qualcomm/Xiaomi workspace с модулями;
   перенести плату moonstone, дисплей/тач, камеру, звук, GPU, модем, Wi-Fi/BT,
   питание/зарядку/термодатчики и suspend/resume.
3. Согласовать vendor-интерфейсы, firmware, упаковку/загрузку модулей и ROM.
   Встроить совместимую версию KernelSU после первого рабочего запуска.
4. Проверять загрузку с путём восстановления и сравнивать основные функции,
   сон/пробуждение, нагрев и автономность с исходной системой.

Рабочий телефон через ADB во время проверки не обнаружен. Каталог Android_RisingOS
пуст: device/vendor sources установленной ROM здесь нет. До получения этих
данных нельзя подтвердить аппаратную совместимость или выпускать этот кандидат
как готовое ядро для установки.

Стабильность KMI ограничена одной LTS-семьёй:
https://source.android.com/docs/core/architecture/kernel/android-common

Найденное объявление SingkoKernel 6.1.167 от 1 апреля ссылается на Telegram,
не предоставляет проверенного исходного дерева и не используется как
подтверждение работоспособности порта:
https://t.me/s/PocoX5IDUpdates/726
