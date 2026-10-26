#!/usr/bin/env python3
"""Build a local macOS app. Python 3 and Codex CLI remain explicit runtime dependencies."""
import json
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

code=Path(__file__).resolve().parent
bundle=code/'dist'/'Research Map Community.app';contents=bundle/'Contents';resources=contents/'Resources';runtime=resources/'app'
(contents/'MacOS').mkdir(parents=True,exist_ok=True);runtime.mkdir(parents=True,exist_ok=True)
for source in code.iterdir():
    if source.is_file() and (source.suffix in ('.py','.js','.css','.html') or source.name in ('RESEARCH_WORKFLOW.md','analysis-node.schema.json')) and not source.name.startswith('test_'):
        shutil.copy2(source,runtime/source.name)
for package in ('@xterm/xterm/lib','@xterm/xterm/css','@xterm/addon-fit/lib'):
    target=runtime/'node_modules'/package;target.mkdir(parents=True,exist_ok=True)
    for file in (code/'node_modules'/package).iterdir():
        if file.suffix in ('.js','.css'):shutil.copy2(file,target/file.name)
(resources/'python-path.txt').write_text(sys.executable+'\n')
shutil.copytree(code/'demo',runtime/'demo',dirs_exist_ok=True,ignore=shutil.ignore_patterns('.research-map','__pycache__','.DS_Store','._*'))
with (contents/'Info.plist').open('wb') as stream:plistlib.dump({'CFBundleExecutable':'ResearchMap','CFBundleIdentifier':'org.researchmap.community','CFBundleName':'Research Map','CFBundleDisplayName':'Research Map','CFBundlePackageType':'APPL','CFBundleShortVersionString':'0.2.0','NSHighResolutionCapable':True,'NSAppTransportSecurity':{'NSAllowsLocalNetworking':True},'LSMinimumSystemVersion':'12.0'},stream)
subprocess.run(['/usr/bin/swiftc',str(code/'desktop/ResearchMap.swift'),'-o',str(contents/'MacOS/ResearchMap'),'-framework','Cocoa','-framework','WebKit','-module-cache-path','/private/tmp/research-map-swift-cache'],check=True)
print(bundle)
