#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, you can obtain one at https://mozilla.org/MPL/2.0/.
"""Build, install, update or restore the local Thunderbird layout."""
import argparse
import configparser
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parent
STATE = Path.home() / '.local/state/outlook-bird'
ADDON_ID = 'outlook-bird@mocky.local'
BEGIN, END = '// BEGIN OUTLOOK BIRD', '// END OUTLOOK BIRD'
BLOCK = re.compile(re.escape(BEGIN) + r'.*?' + re.escape(END) + r'\n?', re.DOTALL)
PREFS = {
    'toolkit.legacyUserProfileCustomizations.stylesheets': True,
    'mail.pane_config.dynamic': 2,
    'mail.thread.conversation.enabled': False,
    'extensions.activeThemeID': 'thunderbird-compact-light@mozilla.org',
    'ui.systemUsesDarkTheme': 0,
    'mail.inappnotifications.enabled': False,
    'mailnews.start_page.enabled': False,
    'mailnews.attachments.display.start_expanded': True,
}
OWNED = ['chrome/'+name for name in [
    'userChrome.css', 'reading-pane.css', 'compose.css', 'accessibility.css',
    'alpine-lake.png',
]] + ['extensions/'+ADDON_ID+'.xpi']


def atomic_write(path, data):
    """Replace one file without exposing a partially written package or setting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as output:
        temporary = Path(output.name)
        output.write(data if isinstance(data, bytes) else data.encode())
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def find_profile():
    for base in [Path.home()/'.config/thunderbird', Path.home()/'.thunderbird']:
        ini = base/'profiles.ini'
        if not ini.exists():
            continue
        config = configparser.ConfigParser()
        config.read(ini)
        for section in config.sections():
            if section.startswith('Install') and config.has_option(section, 'Default'):
                return (base/config[section]['Default']).resolve()
        for section in config.sections():
            if section.startswith('Profile') and config[section].get('Default') == '1':
                path = Path(config[section]['Path'])
                return (base/path if config[section].get('IsRelative') == '1' else path).resolve()
    raise SystemExit('No default profile found; pass --profile /absolute/profile/path.')


def pref_pattern(key):
    return re.compile(r'^user_pref\(' + re.escape(json.dumps(key)) + r',\s*(.*?)\);\s*$', re.MULTILINE)


def build():
    """Build a deterministic XPI, embedding the renderer and its stylesheets."""
    with tempfile.TemporaryDirectory() as temporary:
        package = Path(temporary)/'package.xpi'
        with zipfile.ZipFile(package, 'w', zipfile.ZIP_DEFLATED) as archive:
            for source in sorted((ROOT/'addon').rglob('*')):
                if not source.is_file() or source.suffix not in {'.js', '.json', '.css'}:
                    continue
                relative = source.relative_to(ROOT/'addon').as_posix()
                data = source.read_bytes()
                if relative == 'experiment/api.js':
                    text = data.decode()
                    marker = '/* __OUTLOOK_BIRD_MESSAGE_LAYOUT__ */'
                    if text.count(marker) != 1:
                        raise ValueError('Missing or duplicate message-renderer build marker')
                    text = text.replace(marker, (source.parent/'message-layout.js').read_text())
                    for token, name in [
                        ('__OUTLOOK_BIRD_CONVERSATION_CSS__', 'conversation.css'),
                        ('__OUTLOOK_BIRD_MESSAGE_BODY_CSS__', 'message-body.css'),
                    ]:
                        marker = json.dumps(token)
                        if text.count(marker) != 1:
                            raise ValueError('Missing or duplicate stylesheet build marker: ' + token)
                        text = text.replace(marker, json.dumps((source.parent/name).read_text()))
                    if '__OUTLOOK_BIRD_' in text:
                        raise ValueError('An unexpanded build marker remains')
                    data = text.encode()
                info = zipfile.ZipInfo(relative, date_time=(2026, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                archive.writestr(info, data)
        atomic_write(ROOT/'outlook-bird.xpi', package.read_bytes())


def profile_state(profile):
    key = hashlib.sha256(str(profile.resolve()).encode()).hexdigest()[:20]
    directory = STATE/'profiles'/key
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    STATE.chmod(0o700)
    return directory


def capture(profile):
    directory = profile_state(profile)
    destination = directory/'backups'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    destination.mkdir(parents=True, mode=0o700)
    text = (profile/'prefs.js').read_text()
    keys = set(PREFS) | {'mailnews.message_display.disable_remote_image'}
    originals = {}
    for key in keys:
        match = pref_pattern(key).search(text)
        originals[key] = json.loads(match[1]) if match else None
    for name in OWNED+['user.js']:
        if (profile/name).exists():
            target = destination/name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(profile/name, target)
    atomic_write(destination/'state.json', json.dumps({'profile':str(profile), 'prefs':originals}, indent=2))
    return destination


def replace_block(profile, block):
    user = profile/'user.js'
    text = BLOCK.sub('', user.read_text() if user.exists() else '').rstrip()
    atomic_write(user, text + ('\n\n' if text and block else '') + block + '\n')


def install(profile, allow_remote_images=False):
    build()  # Fail before changing the profile if the source package is broken.
    directory = profile_state(profile)
    backup = capture(profile)
    baseline = directory/'baseline'
    if not baseline.exists():
        # Preserve a compatible baseline made by the previous installer.
        legacy = STATE/'last-backup'
        previous = Path(legacy.read_text().strip()) if legacy.exists() else None
        if previous and (previous/'state.json').is_file() and json.loads((previous/'state.json').read_text()).get('profile') == str(profile):
            atomic_write(baseline, str(previous))
        else:
            atomic_write(baseline, str(backup))
    atomic_write(directory/'rollback', str(backup))
    try:
        for source in (ROOT/'chrome').iterdir():
            if 'chrome/'+source.name in OWNED:
                atomic_write(profile/'chrome'/source.name, source.read_bytes())
        # Direct file installation is detected at Thunderbird's next startup.
        atomic_write(profile/'extensions'/f'{ADDON_ID}.xpi', (ROOT/'outlook-bird.xpi').read_bytes())
        prefs = dict(PREFS)
        old = BLOCK.search((profile/'user.js').read_text()) if (profile/'user.js').exists() else None
        remote = 'mailnews.message_display.disable_remote_image'
        if allow_remote_images:
            prefs[remote] = False
        elif old and pref_pattern(remote).search(old[0]):
            prefs[remote] = json.loads(pref_pattern(remote).search(old[0])[1])
        block = BEGIN+'\n'+'\n'.join('user_pref('+json.dumps(k)+', '+json.dumps(v)+');' for k,v in prefs.items())+'\n'+END
        replace_block(profile, block)
    except Exception:
        restore_snapshot(profile, backup)
        raise
    print('Installed. Restart Thunderbird. Backup:', backup)


def restore_snapshot(profile, backup):
    state = json.loads((backup/'state.json').read_text())
    if state['profile'] != str(profile):
        raise SystemExit('Backup belongs to a different profile. Nothing changed.')
    saved_user = (backup/'user.js').read_text() if (backup/'user.js').exists() else ''
    block = BLOCK.search(saved_user)
    replace_block(profile, block[0] if block else '')
    for name in OWNED:
        target, original = profile/name, backup/name
        if original.is_file():
            atomic_write(target, original.read_bytes())
        else:
            target.unlink(missing_ok=True)
    prefs = profile/'prefs.js'
    text = prefs.read_text()
    for key, value in state['prefs'].items():
        text = pref_pattern(key).sub('', text)
        if value is not None:
            text += '\nuser_pref('+json.dumps(key)+', '+json.dumps(value)+');\n'
    atomic_write(prefs, text)


def restore(profile, rollback=False):
    directory = profile_state(profile)
    marker = directory/('rollback' if rollback else 'baseline')
    if not marker.exists():
        raise SystemExit('No saved backup found for this profile.')
    restore_snapshot(profile, Path(marker.read_text().strip()))
    print('Previous version restored.' if rollback else 'Original appearance restored. Mail files were not changed.')


def release():
    """Package a self-contained installer and checksum list without profile data."""
    build()
    version = json.loads((ROOT/'addon/manifest.json').read_text())['version']
    destination = ROOT/'dist'/f'outlook-bird-{version}.zip'
    destination.parent.mkdir(exist_ok=True)
    sources = [ROOT/name for name in ['manage.py', 'README.md', 'LICENSE', 'outlook-bird.xpi', 'CHANGELOG.md', 'VERIFICATION.md', 'ASSET-NOTES.txt', 'preview.png']]
    for directory in ['addon', 'chrome', 'tests']:
        sources.extend(p for p in (ROOT/directory).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    checksums = []
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as archive:
        for source in sorted(sources):
            name = source.relative_to(ROOT).as_posix()
            data = source.read_bytes()
            checksums.append(hashlib.sha256(data).hexdigest()+'  '+name)
            archive.writestr(name, data)
        archive.writestr('SHA256SUMS', '\n'.join(checksums)+'\n')
    atomic_write(destination.with_suffix('.zip.sha256'), hashlib.sha256(destination.read_bytes()).hexdigest()+'  '+destination.name+'\n')
    print(destination)


def require_supported(executable):
    result = subprocess.run([executable, '--version'], capture_output=True, text=True, check=True)
    if not re.search(r'\b159\.', result.stdout):
        raise SystemExit('This layout is validated for Thunderbird 159.x. Use restore before upgrading to an untested major version.')


def require_closed():
    if shutil.which('pgrep'):
        for name in ['thunderbird', 'thunderbird-bin']:
            if subprocess.run(['pgrep', '-x', name], capture_output=True).returncode == 0:
                raise SystemExit('Close Thunderbird before changing its profile files.')
    else:
        raise SystemExit('Process detection is unavailable. This installer currently supports Linux with pgrep.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['build', 'release', 'install', 'update', 'restore', 'rollback'])
    parser.add_argument('--profile', type=Path)
    parser.add_argument('--thunderbird', default='thunderbird')
    parser.add_argument('--allow-remote-images', action='store_true', help='Allow all remote images, including open-tracking pixels; otherwise keep the existing policy.')
    args = parser.parse_args()
    if args.action in {'build', 'release'}:
        {'build':build, 'release':release}[args.action]()
    else:
        require_closed()
        profile = (args.profile or find_profile()).resolve()
        if not (profile/'prefs.js').is_file():
            raise SystemExit('The selected folder is not an initialized Thunderbird profile.')
        if args.action in {'install', 'update'}:
            require_supported(args.thunderbird)
            install(profile, args.allow_remote_images)
        else:
            restore(profile, rollback=args.action == 'rollback')
