# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, you can obtain one at https://mozilla.org/MPL/2.0/.
"""Profile lifecycle tests; never read or change the user's real profile."""
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import zipfile

SOURCE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('manage', SOURCE/'manage.py')
manage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manage)


class ProfileLifecycle(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.root = self.directory/'source'
        shutil.copytree(SOURCE, self.root, ignore=shutil.ignore_patterns('work', 'dist', '__pycache__', '*.xpi'))
        self.profile = self.make_profile('one')
        self.patcher = patch.multiple(manage, ROOT=self.root, STATE=self.directory/'state')
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.output = contextlib.redirect_stdout(io.StringIO())
        self.output.__enter__()
        self.addCleanup(self.output.__exit__, None, None, None)

    def make_profile(self, name):
        profile = self.directory/name
        (profile/'chrome').mkdir(parents=True)
        (profile/'prefs.js').write_text('user_pref("ui.systemUsesDarkTheme", 1);\nuser_pref("unrelated", 7);\n')
        (profile/'user.js').write_text('user_pref("unrelated", 7);\n')
        (profile/'chrome/userChrome.css').write_text('/* original theme */')
        (profile/'chrome/avatars.json').write_text('{"private": "keep"}')
        (profile/'xulstore.json').write_text('{"window": "keep"}')
        return profile

    def test_build_is_reproducible_and_embeds_renderer(self):
        manage.build()
        first = (self.root/'outlook-bird.xpi').read_bytes()
        manage.build()
        self.assertEqual(first, (self.root/'outlook-bird.xpi').read_bytes())
        with zipfile.ZipFile(self.root/'outlook-bird.xpi') as package:
            self.assertIsNone(package.testzip())
            api = package.read('experiment/api.js').decode()
            self.assertNotIn('__OUTLOOK_BIRD_', api)
            self.assertIn('class MessageLayout', api)

    def test_localized_background_labels_match_schema(self):
        labels = json.loads((self.root/'addon/_locales/en/messages.json').read_text())
        schema = json.loads((self.root/'addon/experiment/schema.json').read_text())
        required = schema[0]['functions'][0]['parameters'][0]['properties']
        for key in required:
            self.assertIn(key, labels)
            self.assertIn('"'+key+'"', (self.root/'addon/background.js').read_text())

    def test_install_keeps_remote_image_policy_by_default(self):
        manage.install(self.profile)
        user = (self.profile/'user.js').read_text()
        self.assertNotIn('disable_remote_image', user)
        self.assertTrue((self.profile/'extensions'/f'{manage.ADDON_ID}.xpi').exists())

    def test_update_preserves_explicit_remote_image_choice(self):
        manage.install(self.profile, allow_remote_images=True)
        manage.install(self.profile)
        text = (self.profile/'user.js').read_text()
        self.assertEqual(text.count(manage.BEGIN), 1)
        self.assertIn('"mailnews.message_display.disable_remote_image", false', text)

    def test_restore_keeps_later_preferences_photos_and_window_state(self):
        manage.install(self.profile)
        with (self.profile/'user.js').open('a') as stream:
            stream.write('user_pref("added.later", true);\n')
        (self.profile/'xulstore.json').write_text('{"window":"changed later"}')
        manage.restore(self.profile)
        self.assertIn('added.later', (self.profile/'user.js').read_text())
        self.assertEqual((self.profile/'chrome/userChrome.css').read_text(), '/* original theme */')
        self.assertEqual((self.profile/'chrome/avatars.json').read_text(), '{"private": "keep"}')
        self.assertIn('changed later', (self.profile/'xulstore.json').read_text())
        self.assertIn('"ui.systemUsesDarkTheme", 1', (self.profile/'prefs.js').read_text())
        self.assertNotIn(manage.BEGIN, (self.profile/'user.js').read_text())

    def test_repeated_updates_keep_original_baseline(self):
        manage.install(self.profile)
        manage.install(self.profile)
        manage.restore(self.profile)
        self.assertEqual((self.profile/'chrome/userChrome.css').read_text(), '/* original theme */')

    def test_rollback_restores_previous_styles_and_xpi(self):
        manage.install(self.profile)
        before = (self.profile/'extensions'/f'{manage.ADDON_ID}.xpi').read_bytes()
        (self.root/'chrome/userChrome.css').write_text('/* new theme */')
        (self.root/'addon/background.js').write_text('// changed build\n')
        manage.install(self.profile)
        manage.restore(self.profile, rollback=True)
        self.assertEqual((self.profile/'extensions'/f'{manage.ADDON_ID}.xpi').read_bytes(), before)
        self.assertNotEqual((self.profile/'chrome/userChrome.css').read_text(), '/* new theme */')

    def test_backups_are_independent_for_each_profile(self):
        other = self.make_profile('two')
        manage.install(self.profile)
        manage.install(other)
        manage.restore(self.profile)
        self.assertEqual((self.profile/'chrome/userChrome.css').read_text(), '/* original theme */')
        self.assertNotEqual((other/'chrome/userChrome.css').read_text(), '/* original theme */')

    def test_broken_build_does_not_change_installed_files(self):
        manage.install(self.profile)
        before = (self.profile/'chrome/userChrome.css').read_bytes()
        (self.root/'addon/experiment/api.js').write_text('// broken source')
        with self.assertRaises(ValueError):
            manage.install(self.profile)
        self.assertEqual((self.profile/'chrome/userChrome.css').read_bytes(), before)

    def test_failed_copy_restores_previous_installation(self):
        original = manage.atomic_write
        failed = False
        def fail_once(path, data):
            nonlocal failed
            if path == self.profile/'chrome/compose.css' and not failed:
                failed = True
                raise OSError('Simulated write failure')
            return original(path, data)
        with patch.object(manage, 'atomic_write', side_effect=fail_once):
            with self.assertRaises(OSError):
                manage.install(self.profile)
        self.assertEqual((self.profile/'chrome/userChrome.css').read_text(), '/* original theme */')
        self.assertNotIn(manage.BEGIN, (self.profile/'user.js').read_text())

    def test_release_checksums_cover_every_file(self):
        manage.release()
        package = next((self.root/'dist').glob('*.zip'))
        with zipfile.ZipFile(package) as archive:
            self.assertIn('tests/smoke.py', archive.namelist())
            sums = archive.read('SHA256SUMS').decode().splitlines()
            self.assertEqual(len(sums), len(archive.namelist())-1)
            for entry in sums:
                expected, name = entry.split('  ', 1)
                self.assertEqual(hashlib.sha256(archive.read(name)).hexdigest(), expected)
            self.assertFalse(any('avatars.json' in name for name in archive.namelist()))

    def test_running_process_blocks_profile_writes(self):
        with patch.object(manage.shutil, 'which', return_value='/usr/bin/pgrep'), patch.object(manage.subprocess, 'run') as run:
            run.return_value.returncode = 0
            with self.assertRaises(SystemExit):
                manage.require_closed()

    def test_unsupported_thunderbird_is_rejected(self):
        with patch.object(manage.subprocess, 'run') as run:
            run.return_value.stdout = 'Mozilla Thunderbird 160.0'
            with self.assertRaises(SystemExit):
                manage.require_supported('thunderbird')
            run.return_value.stdout = 'Mozilla Thunderbird 159.0'
            manage.require_supported('thunderbird')
