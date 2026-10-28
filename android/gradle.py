#!/usr/bin/env python3
"""Text-only Gradle bootstrap: fixed official distribution and SHA256, no credentials."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

VERSION='8.13'
SHA256='20f1b1176237254a6fc204d8434196fa11a4cfb387567519c61556e8710aed78'
ROOT=Path(__file__).resolve().parent
cache=Path(os.environ.get('KINDER_BUILD_CACHE',Path.home()/'.cache/kinder-build'))
cache.mkdir(parents=True,exist_ok=True)
archive=cache/('gradle-'+VERSION+'-bin.zip')
if not archive.exists() or hashlib.sha256(archive.read_bytes()).hexdigest()!=SHA256:
    with urllib.request.urlopen('https://downloads.gradle.org/distributions/gradle-'+VERSION+'-bin.zip',timeout=60) as source:
        with tempfile.NamedTemporaryFile(dir=cache,delete=False) as target:
            name=Path(target.name);size=0
            while chunk:=source.read(1024*1024):
                size+=len(chunk)
                if size>200*1024*1024:raise RuntimeError('Gradle archive exceeds limit')
                target.write(chunk)
    if hashlib.sha256(name.read_bytes()).hexdigest()!=SHA256:
        name.unlink();raise RuntimeError('Gradle distribution hash mismatch')
    name.replace(archive)
folder=cache/('gradle-'+VERSION)
if not folder.exists():
    with zipfile.ZipFile(archive) as zipped:
        for entry in zipped.infolist():
            if not (cache/entry.filename).resolve().is_relative_to(cache.resolve()):raise RuntimeError('invalid archive path')
        zipped.extractall(cache)
    (folder/'bin/gradle').chmod(0o755)
raise SystemExit(subprocess.call([str(folder/'bin/gradle'),'-p',str(ROOT),'--no-daemon',*sys.argv[1:]]))
