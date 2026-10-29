#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""Compile actual GENI UART functions with fault-injected DMA/PM APIs."""
from pathlib import Path
import os,re,subprocess,tempfile
root=Path(__file__).resolve().parents[1]
source=Path(os.environ.get('GENI_TEST_SOURCE',root/'kernel/drivers/tty/serial/msm_geni_serial.c')).read_text()
def function(name):
    m=re.search(r'^static (?:int|void) '+name+r'\([^;{}]*\)\n\{',source,re.M)
    if not m:raise RuntimeError(name)
    end=source.index('{',m.start())+1;depth=1
    while depth:
        depth+=(source[end]=='{')-(source[end]=='}');end+=1
    return source[m.start():end]
prefix=r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
static void test_log(void *context,const char *format,...) {(void)context;(void)format;}
#define IPC_LOG_MSG(...) test_log(__VA_ARGS__)
#define WARN_ON_ONCE(x) ((void)(x))
#define atomic_read(x) (*(x))
#define GET_DEV_PORT(u) ((u)->driver)
#define UART_XMIT_SIZE 4096
#define FIFO_MODE 0
#define SE_DMA 1
#define M_GENI_CMD_ACTIVE 1
#define M_TX_FIFO_WATERMARK_EN 2
#define M_CMD_DONE_EN 4
#define SE_GENI_STATUS 1
#define SE_GENI_IOS 2
#define SE_GENI_M_IRQ_EN 3
#define SE_GENI_TX_WATERMARK_REG 4
#define mb() ((void)0)
typedef uintptr_t dma_addr_t;
struct mutex { int held; };
struct tty_port { struct mutex mutex; };
struct circ_buf { unsigned int head,tail; };
struct uart_state { struct tty_port port; struct circ_buf xmit; };
struct device { struct {int usage_count;} power; int disable_depth; bool active; };
struct msm_geni_serial_port;
struct uart_port {
    struct device *dev; struct uart_state *state;
    struct msm_geni_serial_port *driver;
    bool console,suspended; void *membase;
    struct {unsigned int tx;} icount;
};
struct msm_geni_serial_port {
    int is_clock_off,xfer_mode,tx_wm;
    dma_addr_t tx_dma; unsigned int xmit_size;
    void *wrapper_dev,*ipc_log_pwr,*ipc_log_misc,*ipc_log_tx,*console_log;
};
static int sync_result,manual_result,prep_result;
static int wakeups,unmaps,off_calls,prep_calls,reg_accesses;
static unsigned int status_reg;
static struct uart_port port;
static bool uart_console(struct uart_port *u) {return u->console;}
static int mutex_trylock(struct mutex *m) {if(m->held)return 0; m->held=1;return 1;}
static void mutex_unlock(struct mutex *m) {assert(m->held);m->held=0;}
static bool pm_runtime_enabled(struct device *d) {return !d->disable_depth;}
static bool pm_runtime_status_suspended(struct device *d) {return !d->active;}
static bool pm_runtime_active(struct device *d) {return d->active;}
static void pm_runtime_disable(struct device *d) {d->disable_depth++;}
static void pm_runtime_enable(struct device *d) {assert(d->disable_depth);d->disable_depth--;}
static int msm_geni_serial_runtime_resume(struct device *d) {(void)d;return manual_result;}
static void pm_runtime_get_noresume(struct device *d) {d->power.usage_count++;}
static void pm_runtime_set_active(struct device *d) {d->active=true;}
static void pm_runtime_set_suspended(struct device *d) {d->active=false;}
static int pm_runtime_get_sync(struct device *d) {d->power.usage_count++;if(sync_result>=0)d->active=true;return sync_result;}
static void pm_runtime_put_noidle(struct device *d) {assert(d->power.usage_count>0);d->power.usage_count--;}
static int pm_runtime_get(struct device *d) {d->power.usage_count++;return d->active?1:0;}
static void pm_runtime_mark_last_busy(struct device *d) {(void)d;}
static void pm_runtime_put_autosuspend(struct device *d) {off_calls++;assert(d->power.usage_count>0);d->power.usage_count--;}
static unsigned int geni_read_reg_nolog(void *base,int offset) {(void)base;reg_accesses++;return offset==SE_GENI_STATUS?status_reg:0;}
static void geni_write_reg_nolog(unsigned int value,void *base,int offset) {(void)value;(void)base;(void)offset;reg_accesses++;}
static bool uart_circ_empty(struct circ_buf *c) {return c->head==c->tail;}
static void uart_write_wakeup(struct uart_port *u) {(void)u;wakeups++;}
static unsigned int msm_geni_serial_tx_empty(struct uart_port *u) {(void)u;return 1;}
static int msm_geni_serial_prep_dma_tx(struct uart_port *u) {
    prep_calls++;
    if(!prep_result) {
        u->driver->tx_dma=0x1234;
        u->driver->xmit_size=(u->state->xmit.head-u->state->xmit.tail)&(UART_XMIT_SIZE-1);
    }
    return prep_result;
}
static void geni_se_tx_dma_unprep(void *dev,dma_addr_t address,unsigned int size) {
    (void)dev;assert(address && size==16);unmaps++;
}
'''
main=r'''
static struct device dev;
static struct uart_state state;
static struct msm_geni_serial_port driver;
static void reset(void) {
    dev=(struct device){.active=true};state=(struct uart_state){0};
    driver=(struct msm_geni_serial_port){.xfer_mode=SE_DMA};
    port=(struct uart_port){.dev=&dev,.state=&state,.driver=&driver};
    sync_result=manual_result=prep_result=0;
    wakeups=unmaps=off_calls=prep_calls=reg_accesses=0;status_reg=0;
}
static void power_test(void) {
    for(int locked=0;locked<2;locked++) {
        reset();dev.disable_depth=1;dev.active=false;manual_result=-EIO;state.port.mutex.held=locked;
        assert(msm_geni_serial_power_on(&port)==-EIO);
        assert(!dev.active && !dev.power.usage_count && dev.disable_depth==1 && state.port.mutex.held==locked);
    }
    reset();dev.disable_depth=1;dev.active=false;
    assert(!msm_geni_serial_power_on(&port));
    assert(dev.active && dev.power.usage_count==1 && dev.disable_depth==1 && !state.port.mutex.held);
    for(int result=0;result<=1;result++) {
        reset();sync_result=result;
        assert(!msm_geni_serial_power_on(&port));assert(dev.power.usage_count==1);
    }
    reset();sync_result=-EIO;
    assert(msm_geni_serial_power_on(&port)==-EIO);assert(!dev.power.usage_count);
    reset();dev.disable_depth=1;
    assert(!msm_geni_serial_power_on(&port));assert(!dev.power.usage_count);
}
static void start_test(void) {
    int errors[]={-ENOMEM,-EIO,-EPERM};
    for(unsigned int e=0;e<sizeof(errors)/sizeof(*errors);e++) for(int other=0;other<3;other++) {
        reset();dev.power.usage_count=other;state.xmit.head=100;prep_result=errors[e];
        msm_geni_serial_start_tx(&port);
        assert(dev.power.usage_count==other && off_calls==1 && prep_calls==1);
        assert(!driver.tx_dma && state.xmit.head==100 && state.xmit.tail==0);
    }
    reset();dev.disable_depth=1;dev.power.usage_count=2;state.xmit.head=100;prep_result=-ENOMEM;
    msm_geni_serial_start_tx(&port);assert(dev.power.usage_count==2 && !off_calls);
    reset();state.xmit.head=100;msm_geni_serial_start_tx(&port);
    assert(dev.power.usage_count==1 && driver.tx_dma && prep_calls==1 && !off_calls);
    reset();dev.power.usage_count=2;driver.tx_dma=0x55;
    msm_geni_serial_start_tx(&port);
    assert(dev.power.usage_count==2 && driver.tx_dma==0x55 && !prep_calls && off_calls==1);
    reset();dev.active=false;msm_geni_serial_start_tx(&port);
    assert(!dev.power.usage_count && !prep_calls && !reg_accesses);
    reset();port.console=true;driver.is_clock_off=1;msm_geni_serial_start_tx(&port);
    assert(!dev.power.usage_count && !prep_calls && !reg_accesses);
    reset();driver.xfer_mode=FIFO_MODE;msm_geni_serial_start_tx(&port);
    assert(dev.power.usage_count==1 && !prep_calls && !off_calls && reg_accesses);
}
static void completion_test(void) {
    int errors[]={-ENOMEM,-EIO,-EPERM};
    for(unsigned int e=0;e<sizeof(errors)/sizeof(*errors);e++) for(int other=0;other<3;other++) {
        reset();dev.power.usage_count=other+1;state.xmit.tail=4088;state.xmit.head=64;
        driver.tx_dma=0x55;driver.xmit_size=16;prep_result=errors[e];
        assert(!msm_geni_serial_handle_dma_tx(&port));
        assert(dev.power.usage_count==other && off_calls==1);
        assert(state.xmit.tail==8 && state.xmit.head==64 && port.icount.tx==16);
        assert(unmaps==1 && !driver.tx_dma && wakeups);
    }
    reset();dev.power.usage_count=1;state.xmit.head=64;driver.tx_dma=0x55;driver.xmit_size=16;
    assert(!msm_geni_serial_handle_dma_tx(&port));
    assert(state.xmit.tail==16 && dev.power.usage_count==1 && !off_calls && driver.tx_dma);
    reset();dev.power.usage_count=1;state.xmit.head=16;driver.tx_dma=0x55;driver.xmit_size=16;
    assert(!msm_geni_serial_handle_dma_tx(&port));
    assert(state.xmit.tail==16 && !dev.power.usage_count && off_calls==1 && !prep_calls && wakeups==1);
}
int main(void) {
    const char *which=getenv("GENI_TEST_CASE");
    if(!which || !strcmp(which,"power"))power_test();
    if(!which || !strcmp(which,"start"))start_test();
    if(!which || !strcmp(which,"completion"))completion_test();
    puts("PASS: GENI manual resume errors, DMA failure PM balance, pending data and normal/console/FIFO paths");
}
'''
with tempfile.TemporaryDirectory(prefix='geni-pm-test-') as work:
    cfile,binary=Path(work)/'test.c',Path(work)/'test'
    funcs='\n'.join(function(name) for name in ['msm_geni_serial_power_on','msm_geni_serial_power_off','msm_geni_serial_start_tx','msm_geni_serial_handle_dma_tx'])
    cfile.write_text(prefix+funcs+main)
    subprocess.run(['cc','-std=gnu11','-O1','-g','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',str(cfile),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True)
