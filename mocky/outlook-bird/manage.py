#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, you can obtain one at https://mozilla.org/MPL/2.0/.

"""Install or restore Outlook Bird's local appearance. Close Thunderbird first."""
import argparse
import configparser
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parent
STATE = Path.home() / '.local/state/outlook-bird'
ADDON_ID = 'outlook-bird@mocky.local'
BEGIN, END = '// BEGIN OUTLOOK BIRD', '// END OUTLOOK BIRD'
PREFS = {
    'toolkit.legacyUserProfileCustomizations.stylesheets': True,
    'mail.pane_config.dynamic': 2,
    'mail.thread.conversation.enabled': False,
    'extensions.activeThemeID': 'thunderbird-compact-light@mozilla.org',
    'ui.systemUsesDarkTheme': 0,
    'mail.inappnotifications.enabled': False,
    'mailnews.start_page.enabled': False,
    'mailnews.attachments.display.start_expanded': True,
    'mailnews.message_display.disable_remote_image': False,
}

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
    with zipfile.ZipFile(ROOT/'outlook-bird.xpi', 'w', zipfile.ZIP_DEFLATED) as archive:
        for source in sorted((ROOT/'addon').rglob('*')):
            if source.is_file():
                relative = source.relative_to(ROOT/'addon')
                if relative.as_posix() == 'experiment/api.js':
                    text = source.read_text()
                    for token, name in [
                        ('__OUTLOOK_BIRD_CONVERSATION_CSS__', 'conversation.css'),
                        ('__OUTLOOK_BIRD_MESSAGE_BODY_CSS__', 'message-body.css'),
                    ]:
                        marker = json.dumps(token)
                        if marker not in text:
                            raise ValueError('Missing stylesheet build token: ' + token)
                        text = text.replace(marker, json.dumps((source.parent/name).read_text()))
                    archive.writestr(relative.as_posix(), text)
                else:
                    archive.write(source, relative)

def capture(profile, source=None):
    source = source or profile
    destination = STATE/'backups'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    destination.mkdir(parents=True, mode=0o700)
    STATE.chmod(0o700)
    text = (source/'prefs.js').read_text()
    originals = {}
    for key in PREFS:
        match = pref_pattern(key).search(text)
        originals[key] = json.loads(match[1]) if match else None
    for name in ['user.js', 'xulstore.json']:
        if (source/name).exists():
            shutil.copy2(source/name, destination/name)
    if (source/'chrome').exists():
        shutil.copytree(source/'chrome', destination/'chrome')
    (destination/'state.json').write_text(json.dumps({'profile':str(profile), 'prefs':originals}, indent=2))
    (STATE/'last-backup').write_text(str(destination))
    return destination

def install(profile):
    backup = capture(profile)
    build()
    shutil.copytree(ROOT/'chrome', profile/'chrome', dirs_exist_ok=True)
    user = profile/'user.js'
    text = user.read_text() if user.exists() else ''
    text = re.sub(re.escape(BEGIN) + r'.*?' + re.escape(END) + r'\n?', '', text, flags=re.DOTALL)
    block = '\n'.join('user_pref(' + json.dumps(k) + ', ' + json.dumps(v) + ');' for k,v in PREFS.items())
    user.write_text(text.rstrip()+'\n\n'+BEGIN+'\n'+block+'\n'+END+'\n')
    print('Appearance installed. Backup:', backup)
    print('Open Thunderbird, then Add-ons and Themes > gear > Install Add-on From File:')
    print(ROOT/'outlook-bird.xpi')

def restore(profile):
    marker = STATE/'last-backup'
    if not marker.exists():
        raise SystemExit('No saved backup found.')
    backup = Path(marker.read_text().strip())
    state = json.loads((backup/'state.json').read_text())
    if state['profile'] != str(profile):
        raise SystemExit('Backup belongs to a different profile. Nothing changed.')
    user = profile/'user.js'
    if user.exists():
        text = re.sub(re.escape(BEGIN) + r'.*?' + re.escape(END) + r'\n?', '', user.read_text(), flags=re.DOTALL)
        if text.strip() or (backup/'user.js').exists():
            user.write_text(text)
        else:
            user.unlink()
    elif (backup/'user.js').exists():
        shutil.copy2(backup/'user.js', user)
    if (backup/'xulstore.json').exists():
        shutil.copy2(backup/'xulstore.json', profile/'xulstore.json')
    for name in ['userChrome.css', 'reading-pane.css', 'alpine-lake.png']:
        target = profile/'chrome'/name
        original = backup/'chrome'/name
        if original.exists():
            shutil.copy2(original, target)
        else:
            target.unlink(missing_ok=True)
    prefs = profile/'prefs.js'
    text = prefs.read_text()
    for key, value in state['prefs'].items():
        text = pref_pattern(key).sub('', text)
        if value is not None:
            text += '\nuser_pref('+json.dumps(key)+', '+json.dumps(value)+');\n'
    prefs.write_text(text)
    (profile/'extensions'/f'{ADDON_ID}.xpi').unlink(missing_ok=True)
    print('Original appearance restored. Mail files were not changed.')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['build', 'install', 'restore'])
    parser.add_argument('--profile', type=Path)
    args = parser.parse_args()
    if args.action == 'build':
        build()
    else:
        if subprocess.run(['pgrep', '-x', 'thunderbird-bin'], capture_output=True).returncode == 0:
            raise SystemExit('Close Thunderbird before changing its profile files.')
        profile = (args.profile or find_profile()).resolve()
        if not (profile/'prefs.js').is_file():
            raise SystemExit('The selected folder is not an initialized Thunderbird profile.')
        {'install':install, 'restore':restore}[args.action](profile)
