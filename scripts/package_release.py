#!/usr/bin/env python3
"""Build only the reviewed public files; never walk private state or Git history."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FILES = [
    '.env.example', '.gitignore', 'LICENSE', 'README.md', 'RELEASE_NOTES.md',
    'THIRD_PARTY_NOTICES.md', 'requirements.txt',
    'Launch dork.command', 'Setup dork.command',
    'app/dashboard.py', 'app/templates/index.html',
    'app/static/js/app.js', 'app/static/js/sketch.js', 'app/static/js/media-upgrade.js',
    'app/static/css/styles.css', 'app/static/css/sketch.css',
    'tests/test_local_boundary.py', 'tests/test_media.py', 'tests/test_sketch.cjs', 'tests/test_media_bridge.cjs',
    'scripts/package_release.py',
    'assets/dork-draw.jpg', 'assets/dork-video.jpg', 'assets/dork-director.jpg',
    *[f'LICENSES/{name}.txt' for name in ['Flask','Werkzeug','Jinja2','MarkupSafe','itsdangerous','click','blinker','python-dotenv','Pillow']],
]
CHECKS = {
    'private-key': re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    'provider-token': re.compile(r'\b(?:xai-[A-Za-z0-9_-]{20,}|sk-(?:proj-)?[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})'),
    'aws-key': re.compile(r'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b'),
    'private-host-path': re.compile(r'/' + r'Users/[^\s\'"<>]+' + r'|\.' + 'codex/' + r'|\.' + 'ssh/' + r'|\.' + 'aws/'),
}

def reviewed_files():
    manifest = []
    for relative in FILES:
        source = ROOT / relative
        if not source.is_file() or source.is_symlink():
            raise SystemExit(f'Refusing missing or symlinked release file: {relative}')
        data = source.read_bytes()
        if source.suffix != '.jpg':
            text = data.decode('utf-8')
            for label, pattern in CHECKS.items():
                if pattern.search(text):
                    raise SystemExit(f'Release scan failed: {label} in {relative}; no value printed')
        manifest.append({'path': relative, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
    return manifest

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT.parent / 'outputs')
    args = parser.parse_args()
    manifest = reviewed_files()
    args.output.mkdir(parents=True, exist_ok=True)
    bundle = args.output / 'dork-0.1.0-source.zip'
    manifest_bytes = (json.dumps({'product': 'dork', 'version': '0.1.0', 'scope': 'audited source and desktop launchers', 'files': manifest}, indent=2) + '\n').encode()
    with zipfile.ZipFile(bundle, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for row in manifest:
            info = zipfile.ZipInfo('dork/' + row['path'], date_time=(2026,10,2,0,0,0))
            info.create_system = 3
            info.external_attr = (0o100755 if row['path'].endswith('.command') else 0o100644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, (ROOT / row['path']).read_bytes())
        info = zipfile.ZipInfo('dork/release-manifest.json', date_time=(2026,10,2,0,0,0))
        info.external_attr = 0o100644 << 16
        info.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(info, manifest_bytes)
    digest = hashlib.sha256(bundle.read_bytes()).hexdigest()
    (args.output / 'release-manifest.json').write_bytes(manifest_bytes)
    (args.output / 'dork-0.1.0-source.zip.sha256').write_text(f'{digest}  {bundle.name}\n')
    print(f'Audited {len(manifest)} public files; no detected tokens, private keys, or private host paths.')
    print(f'{bundle.name}: {bundle.stat().st_size} bytes; SHA-256 {digest}')

if __name__ == '__main__':
    main()
