#!/usr/bin/env python3
"""Build the Smart Swap KernelSU ZIP. No installation or device access."""
from pathlib import Path
import hashlib,subprocess,zipfile
root=Path(__file__).resolve().parents[1]
source=root/'modules/auto_swap_smart'
names=['module.prop','config.conf','service.sh','action.sh','uninstall.sh','customize.sh','skip_mount','README.md','README_RU.md']
for name in names:
    if name.endswith('.sh'):subprocess.run(['bash','-n',str(source/name)],check=True)
props=(source/'module.prop').read_text()
assert 'id=auto_swap_4gb\n' in props and 'version=2.1.0\n' in props
out=root/'artifacts/Auto_Swap_2GiB_Smart_KernelSU_v2.1.zip'
out.parent.mkdir(exist_ok=True)
with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
    for name in names:
        info=zipfile.ZipInfo(name,(2026,10,29,0,0,0));info.create_system=3
        info.external_attr=(0o100755 if name.endswith('.sh') else 0o100644)<<16
        z.writestr(info,(source/name).read_bytes(),compress_type=zipfile.ZIP_DEFLATED)
with zipfile.ZipFile(out) as z:assert z.testzip() is None
sha=hashlib.sha256(out.read_bytes()).hexdigest()
out.with_suffix('.zip.sha256').write_text(sha+'  '+out.name+'\n')
print(out);print(sha)
