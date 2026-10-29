#!/usr/bin/env python3
"""Run the actual module script with fake Android tools/sysfs, never host swap."""
from pathlib import Path
import os,re,subprocess,tempfile

root=Path(__file__).resolve().parents[1]
FAKE=r'''#!/usr/bin/env python3
from pathlib import Path
import os,sys
base=Path(os.environ['SMART_SWAP_TEST_ROOT'])
mode=Path(sys.argv[0]).name;args=sys.argv[1:]
if mode=='busybox': mode,args=args[0],args[1:]
if mode in ['fallocate','dd','mkswap','swapon','swapoff']:
 with (base/'commands').open('a') as f:f.write(mode+' '+repr(args)+'\n')
if mode=='swapoff':raise RuntimeError('Forbidden swapoff call')
if mode=='id':print(0);sys.exit()
if mode=='stat' and args[:2]==['-c','%u']:print(0);sys.exit()
if mode=='getprop':print('0' if os.getenv('TEST_BOOT_FAIL') else '1');sys.exit()
if mode=='sleep':sys.exit()
if mode=='df':
 print('Filesystem 1K-blocks Used Available Use% Mounted on')
 print('/dev/fake 10000000 0 '+('64' if os.getenv('TEST_LOW') else '9000000')+' 0% /data');sys.exit()
if mode=='nice':os.execvp(args[2],args[2:])
if mode=='cat' and args and args[0].endswith('/zram-control/hot_add'):
 if os.getenv('TEST_HOT_FAIL'):sys.exit(1)
 dev=base/'dev/block/zram3';dev.parent.mkdir(parents=True,exist_ok=True);dev.touch()
 sysdev=base/'sys/block/zram3';sysdev.mkdir(parents=True,exist_ok=True)
 for name,data in [('disksize','0'),('reset','0'),('comp_algorithm','[lzo] lz4 zstd')]: (sysdev/name).write_text(data)
 print(3);sys.exit()
if mode=='fallocate':
 if os.getenv('TEST_ALLOC_FAIL'):sys.exit(1)
 with open(args[-1],'wb') as f:f.truncate(int(args[-2]))
 (base/'alloc-kind').write_text('fallocate');sys.exit()
if mode=='dd' and any(x.startswith('of=') for x in args):
 if os.getenv('TEST_ALLOC_FAIL'):sys.exit(1)
 out=next(x[3:] for x in args if x.startswith('of='))
 with open(out,'wb') as f:f.truncate(2147483648)
 (base/'alloc-kind').write_text('dd');sys.exit()
if mode=='mkswap':
 if os.getenv('TEST_FORMAT_FAIL'):sys.exit(1)
 with open(args[-1],'r+b') as f:f.seek(4086);f.write(b'SWAPSPACE2')
 sys.exit()
if mode=='swapon':
 if os.getenv('TEST_ON_FAIL'):sys.exit(1)
 target=args[-1]
 if target.endswith('/swapfile') and os.getenv('TEST_FALLOC_REJECT') and (base/'alloc-kind').read_text()=='fallocate':sys.exit(1)
 if '-p' in args:
  priority=int(args[args.index('-p')+1]);assert 0<=priority<=32767
 else:
  priorities=[int(l.split()[4]) for l in (base/'proc/swaps').read_text().splitlines()[1:]]
  priority=min([-1]+priorities)-1
 with (base/'proc/swaps').open('a') as f:f.write(target+' partition 2097148 0 '+str(priority)+'\n')
 sys.exit()
os.execv('/usr/bin/'+mode,[mode]+args)
'''

def scenario(name, *, mode='auto',zram_priority=32758,legacy=False,active=False,ok=True,**env):
 with tempfile.TemporaryDirectory(prefix='smart-swap-'+name+'-') as work:
  p=Path(work);bin=p/'bin';bin.mkdir();mod=p/'module';mod.mkdir()
  for cmd in ['busybox','getprop','cat','stat','df','sleep','nice','fallocate','dd','mkswap','swapon','swapoff']:
   f=bin/cmd;f.write_text(FAKE);f.chmod(0o755)
  for d in ['proc/sys/kernel/random','sys/block/zram0','data/local/tmp','sys/class/zram-control','dev/block']: (p/d).mkdir(parents=True,exist_ok=True)
  (p/'proc/sys/kernel/random/boot_id').write_text('test-boot')
  (p/'sys/block/zram0/reset').write_text('0')
  (p/'sys/class/zram-control/hot_add').write_text('3')
  (p/'sys/class/zram-control/hot_remove').write_text('')
  header='Filename Type Size Used Priority\n';lines=header
  if zram_priority is not None:lines+=str(p/'dev/block/zram0')+' partition 3145724 123 '+str(zram_priority)+'\n'
  swap=p/'data/local/tmp/swapfile'
  if legacy:
   with swap.open('wb') as f:f.truncate(4294967296);f.seek(4086);f.write(b'SWAPSPACE2')
  old_inode=swap.stat().st_ino if legacy else None
  if active:lines+=str(swap)+' file 4194300 123 -2\n'
  (p/'proc/swaps').write_text(lines)
  (mod/'config.conf').write_text('MODE='+mode+'\n')
  source=(root/'modules/auto_swap_smart/service.sh').read_text()
  source=source.replace('/data/adb/ksu/bin/busybox',str(bin/'busybox')).replace('/system/bin/swapon',str(bin/'swapon'))
  source=re.sub(r'/(proc|sys|data|dev)/',lambda m:str(p)+m[0],source)
  source=source.replace('df -k /data ', 'df -k '+str(p/'data')+' ')
  # Fake sysfs device nodes are regular files; only this OS predicate is mocked.
  source=source.replace('[ -b ', '[ -f ')
  script=mod/'service.sh';script.write_text(source)
  held_lock=None
  if env.pop('hold_lock',False):
   import fcntl
   held_lock=open(mod/'.run.lock','w');fcntl.flock(held_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  if env.pop('unknown_stage',False):
   d=p/'data/local/tmp/.auto_swap_smart';d.mkdir();(d/'new.swap').write_text('keep-me')
  if env.pop('unknown_file',False):swap.write_text('user-data')
  runenv={**os.environ,'PATH':str(bin)+':'+os.environ['PATH'],'SMART_SWAP_TEST_ROOT':str(p),**env}
  r=subprocess.run(['sh',str(script)],capture_output=True,text=True,env=runenv,timeout=12)
  log=(mod/'swap.log').read_text() if (mod/'swap.log').exists() else ''
  assert (r.returncode==0)==ok,(name,r.returncode,r.stderr,log)
  after=(p/'proc/swaps').read_text()
  assert (p/'sys/block/zram0/reset').read_text()=='0',name
  if held_lock:
   assert after==lines and not (p/'commands').exists()
   held_lock.close();print('PASS:',name);return
  if name=='failed-new-zram':assert (p/'sys/class/zram-control/hot_remove').read_text().strip()=='3'
  if active:
   assert after==lines and swap.stat().st_ino==old_inode
  elif ok and mode!='zram' and zram_priority is not None:
   assert swap.stat().st_size==2147483648 and str(swap) in after
   file_priority=int(next(l for l in after.splitlines() if l.startswith(str(swap)+' ')).split()[4])
   assert file_priority<zram_priority
   before_commands=(p/'commands').read_text();r2=subprocess.run(['sh',str(script)],env=runenv,capture_output=True,timeout=12)
   assert r2.returncode==0 and (p/'commands').read_text()==before_commands
  elif ok and zram_priority is None:
   assert str(p/'dev/block/zram3') in after and not swap.exists()
   commands=(p/'commands').read_text();subprocess.run(['sh',str(script)],env=runenv,capture_output=True,check=True,timeout=12)
   assert (p/'commands').read_text()==commands,(name,commands,(p/'commands').read_text(),(mod/'zram.state').read_text() if (mod/'zram.state').exists() else 'no state',(mod/'swap.log').read_text())
  if not ok and legacy:
   assert swap.exists() and swap.stat().st_ino==old_inode and swap.stat().st_size==4294967296,(name,log)
   assert after==lines
  if name=='unknown-file':assert swap.read_text()=='user-data'
  if name=='unknown-stage':assert (p/'data/local/tmp/.auto_swap_smart/new.swap').read_text()=='keep-me'
  print('PASS:',name)

scenario('locked-second-instance',hold_lock=True)
scenario('existing-system-zram')
scenario('zram-zero-priority',zram_priority=0)
scenario('zram-negative-priority',zram_priority=-2)
scenario('active-legacy',legacy=True,active=True)
scenario('legacy-migration',legacy=True)
scenario('fallocate-rejected-dd-retry',legacy=True,TEST_FALLOC_REJECT='1')
scenario('migration-failed-restores-original',legacy=True,TEST_ON_FAIL='1',ok=False)
scenario('allocation-failed-preserves-legacy',legacy=True,TEST_ALLOC_FAIL='1',ok=False)
scenario('format-failed-preserves-legacy',legacy=True,TEST_FORMAT_FAIL='1',ok=False)
scenario('low-space-preserves-legacy',legacy=True,TEST_LOW='1',ok=False)
scenario('unknown-file',unknown_file=True,ok=False)
scenario('unknown-stage',unknown_stage=True,ok=False)
scenario('new-managed-zram',zram_priority=None)
scenario('failed-new-zram',mode='zram',zram_priority=None,TEST_FORMAT_FAIL='1',ok=False)
scenario('boot-incomplete',legacy=True,TEST_BOOT_FAIL='1',ok=False)
print('All Smart Swap sandbox tests passed; no real swap or sysfs device was modified.')
