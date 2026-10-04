"""Install a verified portable Windows FFmpeg build beside this skill. Explicit setup only."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import urllib.request
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', type=Path,
                        default=Path(__file__).resolve().parents[1] / 'runtime' / 'ffmpeg')
    args = parser.parse_args()
    if os.name != 'nt':
        parser.error('Install ffmpeg and ffprobe with your OS package manager instead.')
    destination = args.destination.resolve()
    if (destination / 'bin' / 'ffmpeg.exe').exists():
        print(f'Already installed: {destination}')
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    url = 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip'
    with tempfile.TemporaryDirectory(prefix='ffmpeg-setup-', dir=destination.parent) as tmp:
        archive = Path(tmp) / 'ffmpeg.zip'
        with urllib.request.urlopen(url + '.sha256', timeout=60) as response:
            match = re.search(r'\b[0-9a-fA-F]{64}\b', response.read().decode())
        if not match:
            raise RuntimeError('Publisher checksum not found; installation stopped.')
        expected = match.group().lower()
        print('Downloading portable FFmpeg from the Windows provider linked by ffmpeg.org...', flush=True)
        digest = hashlib.sha256()
        with urllib.request.urlopen(url, timeout=60) as response, archive.open('wb') as out:
            while chunk := response.read(1024 * 1024):
                digest.update(chunk)
                out.write(chunk)
        if digest.hexdigest() != expected:
            raise RuntimeError('Download checksum mismatch; installation stopped.')
        staging = Path(tmp) / 'verified'
        with zipfile.ZipFile(archive) as zipped:
            for name in zipped.namelist():
                # Extract only the two executables and upstream license/documentation.
                parts = Path(name).parts
                if len(parts) < 2 or name.endswith('/'):
                    continue
                relative = Path(*parts[1:])
                if relative.as_posix() not in ('bin/ffmpeg.exe', 'bin/ffprobe.exe', 'LICENSE', 'README.txt'):
                    continue
                target = staging / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                with zipped.open(name) as source, target.open('wb') as out:
                    shutil.copyfileobj(source, out)
        for executable in ('ffmpeg.exe', 'ffprobe.exe'):
            if not (staging / 'bin' / executable).is_file():
                raise RuntimeError(f'Missing {executable} in verified download.')
        (staging / 'provenance.json').write_text(json.dumps({
            'url': url, 'sha256': expected,
            'providerListing': 'https://ffmpeg.org/download.html',
            'sourceAndLicensing': 'https://www.gyan.dev/ffmpeg/builds/'
        }, indent=2), encoding='utf-8')
        # Never replace an existing runtime.
        if destination.exists():
            raise RuntimeError(f'Destination already exists: {destination}')
        # Do not move a private TemporaryDirectory into the installation: on
        # Windows its inherited ACL can hide the runtime from the desktop user.
        destination.mkdir()
        for source in staging.rglob("*"):
            if source.is_file():
                target = destination / source.relative_to(staging)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
        print(f'Installed and checksum-verified: {destination}')


if __name__ == '__main__':
    main()
