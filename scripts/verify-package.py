#!/usr/bin/env python3
"""Verify the exact exported metadata payload against this source checkout."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

root=Path(__file__).resolve().parents[1]
image=sys.argv[1]
inspect=json.loads(subprocess.check_output(['podman','image','inspect',image]))[0]
labels=inspect['Labels']
assert labels['org.nethserver.rootfull']=='1'
assert labels['org.nethserver.max-per-node']=='1'
assert labels['org.nethserver.images']==''
assert labels['org.opencontainers.image.version']==(root/'VERSION').read_text().strip()
assert labels['org.opencontainers.image.revision']==subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
cid=subprocess.check_output(['podman','create',image],text=True).strip()
try:
    with tempfile.TemporaryDirectory() as directory:
        export=Path(directory)/'payload.tar'
        subprocess.run(['podman','export','-o',str(export),cid],check=True)
        with tarfile.open(export) as tar:
            members=[m for m in tar.getmembers() if m.isfile() and m.name.startswith(('imageroot/','ui/'))]
            actual={m.name:hashlib.sha256(tar.extractfile(m).read()).hexdigest() for m in members}
            expected={str(f.relative_to(root)):hashlib.sha256(f.read_bytes()).hexdigest() for base in ['imageroot','ui'] for f in (root/base).rglob('*') if f.is_file() and '__pycache__' not in f.parts and f.suffix!='.pyc'}
            assert actual==expected, 'export does not match source or includes unexpected files'
            for member in members:
                if member.name.endswith('/50execute') or '/update-module.d/' in member.name:
                    assert member.mode & 0o111, 'non-executable native hook'
        print(f'Package verified: {len(actual)} source-exact files; labels, native hook modes, no bytecode/test payload')
finally:
    subprocess.run(['podman','rm',cid],check=True,stdout=subprocess.DEVNULL)
