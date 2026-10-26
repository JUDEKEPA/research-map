#!/usr/bin/env python3
"""Create an audited, reproducible source ZIP without local build/runtime state."""
from pathlib import Path
import zipfile
from audit_public import ROOT, audit, source_files

if __name__ == '__main__':
    issues = audit()
    if issues: raise SystemExit('\n'.join(issues))
    output = ROOT.parent / 'research-map-open-source.zip'
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for path in source_files():
            info = zipfile.ZipInfo('research-map/'+path.relative_to(ROOT).as_posix(), date_time=(2026,1,1,0,0,0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())
    print(output.name+' created')
