#!/bin/bash

#
# Copyright (C) 2025 Julival Bittencourt
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation;
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, see <http://www.gnu.org/licenses/>.

# Clone Kernel
if [ ! -d "kernel/.git" ]; then
    git clone \
        https://github.com/bittencourtjulival/eclipse_kernel_xiaomi_stone_rebase \
        -b seventeen \
        kernel \
        --depth=1
fi
#git clone https://github.com/bittencourtjulival/eclipse_kernel_xiaomi_stone -b 17 kernel --depth=1

# Copy AnyKernel to kernel dir.
cp -r AnyKernel3 kernel/AnyKernel3

# Move to Kernel Path
cd kernel

echo "Do you want to include KernelSU? (y / n)"
read KernelSU

if [ "$KernelSU" = "y" ]; then
    echo "Build KernelSU Selected"

    # Clone KernelSU next branch
    if [ ! -d "$PWD/KernelSU" ]; then
        echo "Setting up KernelSU..."
        if ! curl -LSs "https://raw.githubusercontent.com/bittencourtjulival/KernelSU/master/kernel/setup.sh" | bash -s; then
            echo "❌ Failed to setup KernelSU!"
            exit 1
        fi
        echo "✅ KernelSU setup completed!"
    fi
else
    echo "Build Non KernelSU Selected"
fi

# Set Kernel Build Variables
DEVICE_CODENAME="stone"  # Device codename (e.g., veux, garnet, etc.)
DEVICE_NAME="POCO X5 5G/Redmi Note 12 5G/Note 12R Pro"          # Device Market name
KERNEL_NAME="Eclipse"    # Kernel name
KERNEL_DEFCONFIG="${DEVICE_CODENAME}_defconfig"
ANYKERNEL3_DIR=$PWD/AnyKernel3/
if [ "$KernelSU" = "y" ]; then
        FINAL_KERNEL_ZIP="${KERNEL_NAME}-Kernel-KSU-${DEVICE_CODENAME}-$(date '+%Y%m%d_%H%M').zip"
else
    FINAL_KERNEL_ZIP="${KERNEL_NAME}-Kernel-${DEVICE_CODENAME}-$(date '+%Y%m%d_%H_%M').zip"
fi

# Set Build Status (Change to "STABLE/TESTING" if needed)
BUILD_STATUS="STABLE"

# Get Hostname
BUILD_HOSTNAME=$(hostname)

# Set Compiler Path (Change if needed)
COMPILER_PATH="$HOME/clang-r563880c/bin"

# Dynamically detect compiler name & version
if [ -d "$COMPILER_PATH" ]; then
    export PATH="$COMPILER_PATH:$PATH"
    COMPILER_NAME="$($COMPILER_PATH/clang --version | head -n 1 | sed -E 's/\(.*\)//' | awk '{$1=$1;print}')"
else
    COMPILER_NAME="Unknown Compiler"
fi

export ARCH=arm64
export KBUILD_BUILD_HOST=$BUILD_HOSTNAME
export KBUILD_BUILD_USER="Julival"
export KBUILD_COMPILER_STRING="$COMPILER_NAME"

# Clone Clang if not found
if ! [ -d "$HOME/clang-r563880c" ]; then
    echo "⚙️ Clang not found! Cloning..."
    if ! git clone -q https://gitlab.com/crdroidandroid/android_prebuilts_clang_host_linux-x86_Clang_r563880c.git -b 15.0 --depth=1 --single-branch ~/clang-r563880c; then
        echo "❌ Cloning failed! Aborting..."
        exit 1
    fi
fi

# Start Build Process
BUILD_START=$(date +"%s")

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🔥 ${KERNEL_NAME} Kernel Build Started!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📱 Device: ${DEVICE_NAME} (${DEVICE_CODENAME})"
echo "🖥️ Building on: $(hostname)"
echo "⚙️ Compiler: ${COMPILER_NAME}"
echo "📰 Build Status: ${BUILD_STATUS}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Clean previous builds
echo "🧹 Cleaning previous builds..."
make O=out clean

# Set Defconfig
echo "⚙️ Setting up defconfig..."
make $KERNEL_DEFCONFIG O=out

# INJEÇÃO AUTOMÁTICA DO KERNELSU (Agora no lugar certo!)
if [ "$KernelSU" = "y" ]; then
    echo "Adicionando configurações do KernelSU ao .config da build..."

    cat << EOF >> out/.config
CONFIG_KSU=y
CONFIG_OVERLAY_FS=y
CONFIG_KSU_HACK_ARM64_BRANCH_LINK=y
# CONFIG_KSU_TAMPER_SYSCALL_TABLE is not set
CONFIG_KSU_LSM_SECURITY_HOOKS=y
# CONFIG_KSU_FEATURE_SULOG is not set
# CONFIG_KSU_FEATURE_ADBROOT is not set
CONFIG_KSU_HOSTSREDIRECT=y
# CONFIG_KSU_ENABLE_FULL_UID_CHECKS is not set
CONFIG_KSU_THRONE_TRACKER_ALWAYS_THREADED=y
# CONFIG_KSU_NOPRINTK is not set
# CONFIG_KSU_SHELL_HAS_SU_ALWAYS is not set
# CONFIG_KSU_DEBUG is not set
CONFIG_KSU_HEURISTIC_IN_TREE_BUILD=y

# nfqttl kernel backend
CONFIG_NETFILTER_ADVANCED=y
CONFIG_NETFILTER_XT_TARGET_HL=y
EOF

    echo "🔄 Aplicando e validando dependências com olddefconfig..."
    make O=out ARCH=arm64 olddefconfig
else
    echo "Nada a fazer ..."
fi



# Compile Kernel
echo ""
echo "🔨 Starting kernel compilation..."
echo ""

make -j$(nproc) O=out \
                ARCH=arm64 \
                CC=clang \
                CLANG_TRIPLE=aarch64-linux-gnu- \
                CROSS_COMPILE=aarch64-linux-gnu- \
                CROSS_COMPILE_ARM32=arm-linux-gnueabi- \
                LD=ld.lld \
                LLVM=1 \
                LLVM_IAS=1 \
                2> error.log

# Check for compiled files
if [ ! -f "$PWD/out/arch/arm64/boot/Image" ]; then
    echo ""
    echo "❌ Build failed! Image not found."
    exit 1
fi

echo ""
echo "✅ ${KERNEL_NAME} Kernel built successfully! Zipping files..."

# Move files to AnyKernel3
rm -rf $ANYKERNEL3_DIR/Image $ANYKERNEL3_DIR/dtbo.img $ANYKERNEL3_DIR/dtb
cp $PWD/out/arch/arm64/boot/Image $ANYKERNEL3_DIR/
cp $PWD/out/arch/arm64/boot/dtbo.img $ANYKERNEL3_DIR/
cp $PWD/out/arch/arm64/boot/dtb.img $ANYKERNEL3_DIR/dtb

# Zip Kernel
cd $ANYKERNEL3_DIR/
zip -r9 "../$FINAL_KERNEL_ZIP" * -x README $FINAL_KERNEL_ZIP

BUILD_END=$(date +"%s")
BUILD_TIME=$((BUILD_END - BUILD_START))

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Build Completed Successfully!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📦 Kernel ZIP: $FINAL_KERNEL_ZIP"
echo "⏱️ Build time: $(($BUILD_TIME / 60)) min $(($BUILD_TIME % 60)) sec"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Clean up
echo "🧹 Cleaning up..."
rm -rf out/
rm -rf $ANYKERNEL3_DIR/Image $ANYKERNEL3_DIR/dtbo.img $ANYKERNEL3_DIR/dtb

echo "✅ All done!"
exit 0
