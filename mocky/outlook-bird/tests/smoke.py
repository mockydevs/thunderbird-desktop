#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, you can obtain one at https://mozilla.org/MPL/2.0/.
"""Exercise the add-on in a temporary local-only Thunderbird profile."""
import argparse
import base64
from email.message import EmailMessage
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mailbox
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import threading
import struct
import zlib
import time

from client import Marionette

ROOT = Path(__file__).resolve().parents[1]


def wait_for(check, timeout=30):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            last = check()
            if last:
                return last
        except (ConnectionError, OSError):
            pass
        time.sleep(0.05)
    raise AssertionError(f'Condition did not become true: {last!r}')


def check(value, message):
    if not value:
        raise AssertionError(message)
    print('PASS:', message, flush=True)


def avatar_fixture():
    """Return a small, recognisable PNG without external image dependencies."""
    def chunk(kind, data):
        return struct.pack('>I', len(data))+kind+data+struct.pack('>I', zlib.crc32(kind+data))
    rows = bytearray()
    for y in range(24):
        rows.append(0)
        for x in range(24):
            mark = (7 <= x <= 9 and 6 <= y <= 18) or (9 <= x <= 15 and (6 <= y <= 8 or 11 <= y <= 13)) or (13 <= x <= 15 and 8 <= y <= 11)
            rows.extend((255,255,255,255) if mark else (15,108,189,255))
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',24,24,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(rows))+chunk(b'IEND',b'')


def make_profile(profile, port):
    mail = profile/'Mail/Local Folders'
    mail.mkdir(parents=True)
    preferences = {
        'marionette.port': port,
        'mail.accountmanager.accounts': 'account1',
        'mail.accountmanager.defaultaccount': 'account1',
        'mail.accountmanager.localfoldersserver': 'server1',
        'mail.account.account1.server': 'server1',
        'mail.server.server1.type': 'none',
        'mail.server.server1.name': 'Preview mailbox',
        'mail.server.server1.hostname': 'Local Folders',
        'mail.server.server1.directory': str(mail),
        'mail.server.server1.userName': 'nobody',
        'app.use_without_mail_account': True,
        'toolkit.legacyUserProfileCustomizations.stylesheets': True,
        'mail.pane_config.dynamic': 2,
        'mailnews.start_page.enabled': False,
        'mailnews.attachments.display.start_expanded': True,
        'mail.inappnotifications.enabled': False,
        'mailnews.message_display.disable_remote_image': False,
        'mail.thread.conversation.enabled': False,
        'extensions.activeThemeID': 'thunderbird-compact-light@mozilla.org',
        'ui.systemUsesDarkTheme': 0,
        'mailnews.database.global.indexer.enabled': False,
        'mail.shell.checkDefaultClient': False,
        'mail.rights.override': True,
        'mailnews.default_view_flags': 1,
        'datareporting.healthreport.uploadEnabled': False,
        'datareporting.policy.dataSubmissionEnabled': False,
    }
    (profile/'user.js').write_text(''.join(
        f'user_pref({json.dumps(key)}, {json.dumps(value)});\n'
        for key, value in preferences.items()))
    shutil.copytree(ROOT/'chrome', profile/'chrome')
    pixel = 'data:image/png;base64,'+base64.b64encode(avatar_fixture()).decode()
    (profile/'chrome/avatars.json').write_text(json.dumps({f'preview{i}@example.test': pixel for i in range(4)}))
    box = mailbox.mbox(mail/'Inbox')
    bodies = [
        ('Emma Kamau', 'Hi, here is the updated proposal. Please review the typography and spacing.'),
        ('David Mwangi', 'The layout looks clean. Can we use blue accents for the primary actions?'),
        ('Emma Kamau', 'Yes, the blue accents and sender avatars are in the new design.'),
        ('David Mwangi', 'Thanks, this is ready for review. This preview contains only local sample messages.'),
    ]
    for index, (sender, body) in enumerate(bodies):
        message = EmailMessage()
        message['From'] = f'{sender} <preview{index}@example.test>'
        message['To'] = 'Design preview <preview@example.test>'
        message['Subject'] = ('Re: ' if index else '') + 'Website design review'
        message['Message-ID'] = f'<design-{index}@example.test>'
        message['Date'] = f'Thu, 29 Oct 2026 {9+index:02d}:00:00 +0300'
        message['X-Mozilla-Status'] = '0001'
        if index:
            message['In-Reply-To'] = f'<design-{index-1}@example.test>'
            message['References'] = ' '.join(f'<design-{i}@example.test>' for i in range(index))
        message.set_content(body)
        if index == 3:
            paragraphs = ''.join(f'<p>Review detail {number}: keep the reading area comfortable, with room for the text and attachments.</p>' for number in range(24))
            message.add_alternative('<html><body><p>'+body+'</p>'+paragraphs+'</body></html>', subtype='html')
            message.add_attachment(b'%PDF-1.4\n% Local fixture; not opened by this test.\n%%EOF', maintype='application', subtype='pdf', filename='design-notes.pdf')
            message.add_attachment(b'Local attachment fixture.', maintype='text', subtype='plain', filename='review-notes.txt')
        if index == 0:
            message.add_attachment(b'Local review notes.', maintype='text', subtype='plain', filename='first-notes.txt')
        box.add(message)
    box.flush()
    box.close()


def run(args):
    args.workdir.mkdir(parents=True, exist_ok=True)
    with socket.socket() as reserve:
        reserve.bind(('127.0.0.1', 0))
        port = reserve.getsockname()[1]
    os.environ['OB_PORT'] = str(port)
    with tempfile.TemporaryDirectory(prefix='outlook-bird-', dir=args.workdir) as temporary:
        profile = Path(temporary)/'profile'
        make_profile(profile, port)
        environment = os.environ.copy()
        environment['MOZ_REMOTE_ALLOW_SYSTEM_ACCESS'] = '1'
        with (Path(temporary)/'thunderbird.log').open('w') as log:
            process = subprocess.Popen([
                args.thunderbird, '--headless', '--new-instance', '--offline',
                '--profile', str(profile), '--marionette',
            ], env=environment, stdout=log, stderr=subprocess.STDOUT)
            client = None
            server = None
            try:
                client = wait_for(Marionette)
                def js(source):
                    return client.js(source)['value']
                js("""
const {MailServices}=ChromeUtils.importESModule('resource:///modules/MailServices.sys.mjs');
const folder=MailServices.accounts.localFoldersServer.rootFolder.getChildNamed('Inbox');
document.getElementById('tabmail').currentAbout3Pane.displayFolder(folder.URI);
window.resizeTo(1680,1000);
return true;
""")
                wait_for(lambda: js("return document.getElementById('tabmail').currentAbout3Pane.gDBView?.rowCount===1;"))
                installed = js("""return (async()=>{
const {AddonManager}=ChromeUtils.importESModule('resource://gre/modules/AddonManager.sys.mjs');
const file=Cc['@mozilla.org/file/local;1'].createInstance(Ci.nsIFile);
file.initWithPath(""" + json.dumps(str(ROOT/'outlook-bird.xpi')) + """);
const install=await AddonManager.getInstallForFile(file);
await install.install();return install.error===0;
})();""")
                check(installed, 'The add-on installs in a clean profile')
                wait_for(lambda: js("return !!document.getElementById('ob-ribbon')&&!!document.getElementById('tabmail').currentAbout3Pane.document.getElementById('ob-filter-tabs');"))
                check(js("return getComputedStyle(document.getElementById('ob-ribbon')).display==='flex';"), 'The toolbar starts with its horizontal styling')
                js("const w=document.getElementById('tabmail').currentAbout3Pane;w.paneLayout.folderPaneSplitter.width=292;w.paneLayout.messagePaneSplitter.width=Math.max(400,w.innerWidth-652);w.threadTree.selectedIndex=0;return true;")
                view = "document.getElementById('tabmail').currentAbout3Pane.document.querySelector('conversation-view')"
                wait_for(lambda: js(f"return {view}?.messages?.length===4;"))
                check(js(f"return {view}.shadowRoot.querySelectorAll('article').length===4;"), 'The thread shows all four conversation cards without a search index')
                wait_for(lambda: js(f"return {view}.shadowRoot.querySelector('browser')?.contentDocument?.querySelector('#messagepane')?.contentDocument?.body?.textContent?.includes('ready for review');"))
                check(True, 'The latest message body renders in its expanded card')
                wait_for(lambda: js(f"return {view}.shadowRoot.querySelector('article[aria-expanded=\"false\"]').hasAttribute('data-ob-photo');"))
                check(True, 'Configured sender photos decorate collapsed cards')
                wait_for(lambda: js(f"return {view}.shadowRoot.querySelector('browser').contentDocument.querySelector('.ob-account-photo')?.naturalWidth>0;"))
                check(True, 'Configured sender photos load in expanded message headers')
                wait_for(lambda: js(f"const b={view}.shadowRoot.querySelector('browser');const m=b.contentDocument.getElementById('messagepane');return m.clientHeight>=m.contentDocument.body.scrollHeight-2;"))
                check(True, 'The expanded message has no separate inner text scrollbar')
                wait_for(lambda: js(f"const a={view}.shadowRoot.querySelector('article[aria-expanded=\"true\"]');const b=a.querySelector('browser');return a.getBoundingClientRect().height-b.getBoundingClientRect().height<8;"))
                geometry = js(f"""const v={view};const a=v.shadowRoot.querySelector('article[aria-expanded="true"]');const b=a.querySelector('browser');const d=b.contentDocument;const m=d.getElementById('messagepane');const attachments=d.getElementById('attachmentView');return {{gap:a.getBoundingClientRect().height-b.getBoundingClientRect().height,readingHeight:m.getBoundingClientRect().height,inset:m.getBoundingClientRect().x,attachmentsTop:attachments.getBoundingClientRect().top,attachmentsBottom:attachments.getBoundingClientRect().bottom,bodyTop:m.getBoundingClientRect().top,headerBottom:d.getElementById('singleMessage').getBoundingClientRect().bottom,font:d.getElementById('messagepane').contentWindow.getComputedStyle(d.getElementById('messagepane').contentDocument.body).fontSize}};""")
                check(geometry['gap'] < 8, 'The expanded browser fills its card without an empty area below it')
                check(geometry['readingHeight'] > 600, 'The long message receives enough reading space above its attachments')
                check(geometry['inset'] >= 18, 'Message text is inset from the reading-card edge')
                check(geometry['attachmentsTop']>=geometry['headerBottom']-1 and geometry['attachmentsBottom']<=geometry['bodyTop'], 'Attachment cards appear between the sender details and message body')
                check(geometry['font']=='14px', 'The message body uses a balanced 14px reading size')
                spacing = js(f"const d={view}.shadowRoot.querySelector('browser').contentDocument;const item=d.querySelector('.attachmentItem').getBoundingClientRect();const name=d.querySelector('.attachmentcell-name').getBoundingClientRect();const menu=d.querySelector('.ob-attachment-menu').getBoundingClientRect();return {{edge:item.right-menu.right,gap:menu.left-name.right}};")
                check(spacing['edge']>=8 and spacing['gap']>=8, 'The attachment dropdown has space from the filename and card edge')
                js(f"const d={view}.shadowRoot.querySelector('browser').contentDocument;d.querySelector('.ob-attachment-menu').click();return true;")
                wait_for(lambda: js(f"return {view}.shadowRoot.querySelector('browser').contentDocument.getElementById('attachmentItemContext').state==='open';"))
                check(js(f"return {view}.shadowRoot.querySelector('browser').contentDocument.getElementById('attachmentItemContext').attachments.length===1;"), 'The attachment menu targets the selected file')
                js(f"{view}.shadowRoot.querySelector('browser').contentDocument.getElementById('attachmentItemContext').hidePopup();return true;")
                js(f"const v={view};const a=v.shadowRoot.querySelector('article[aria-expanded=\"false\"]');a.focus();a.dispatchEvent(new a.ownerDocument.defaultView.KeyboardEvent('keydown',{{key:'Enter',bubbles:true}}));return true;")
                wait_for(lambda: js(f"return {view}.shadowRoot.querySelector('browser')?.contentDocument?.querySelector('#messagepane')?.contentDocument?.body?.textContent?.includes('updated proposal');"))
                check(js(f"return {view}.shadowRoot.activeElement?.getAttribute('aria-expanded')==='true';"), 'Keyboard expansion opens the selected message and retains focus')
                check(js(f"return {view}.shadowRoot.querySelectorAll('article[aria-expanded=\"true\"]').length===2;"), 'Two messages remain expanded in the shared conversation scroll')
                check(js(f"const v={view};const header=v.shadowRoot.querySelector('header');return v.ownerDocument.defaultView.getComputedStyle(header).backgroundColor==='rgb(234, 243, 249)'&&v.ownerDocument.defaultView.getComputedStyle(v).scrollbarGutter==='stable';"), 'The title bar is opaque and the outer scrollbar has its own gutter')
                js("const w=document.getElementById('tabmail').currentAbout3Pane;w.document.querySelector('#ob-filter-tabs [data-ob-unread=\"true\"]').click();return true;")
                wait_for(lambda: js("return document.getElementById('tabmail').currentAbout3Pane.gDBView.rowCount===0;"))
                check(True, 'Unread filters out the read sample thread')
                js("const w=document.getElementById('tabmail').currentAbout3Pane;w.document.querySelector('#ob-filter-tabs [data-ob-unread=\"false\"]').click();return true;")
                wait_for(lambda: js("return document.getElementById('tabmail').currentAbout3Pane.gDBView.rowCount===1;"))
                check(True, 'All restores the sample thread')
                requested = threading.Event()
                class ImageHandler(BaseHTTPRequestHandler):
                    def do_GET(self):
                        requested.set()
                        png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jhfoAAAAASUVORK5CYII=')
                        self.send_response(200)
                        self.send_header('Content-Type', 'image/png')
                        self.end_headers()
                        self.wfile.write(png)
                    def log_message(self, *unused):
                        pass
                server = ThreadingHTTPServer(('127.0.0.1', 0), ImageHandler)
                threading.Thread(target=server.serve_forever, daemon=True).start()
                raw = 'From: Image fixture <image@example.test>\r\nTo: preview@example.test\r\nSubject: Local image check\r\nMessage-ID: <image@example.test>\r\nDate: Thu, 29 Oct 2026 15:00:00 +0300\r\nX-Mozilla-Status: 0001\r\nMIME-Version: 1.0\r\nContent-Type: text/html; charset=UTF-8\r\n\r\n<html><body><p>Local image fixture</p><img src="http://127.0.0.1:' + str(server.server_port) + '/fixture.png" alt="Local image"></body></html>\r\n'
                js("""
Services.io.manageOfflineStatus=false;Services.io.offline=false;
const {MailServices}=ChromeUtils.importESModule('resource:///modules/MailServices.sys.mjs');
const folder=MailServices.accounts.localFoldersServer.rootFolder.getChildNamed('Inbox');
const header=folder.QueryInterface(Ci.nsIMsgLocalMailFolder).addMessage("""+json.dumps(raw)+""");
document.getElementById('tabmail').currentAbout3Pane.messagePane.displayMessage(folder.getUriForMsg(header));
return true;
""")
                check(requested.wait(10), 'Remote images load automatically from the local test server')
                check(js("return !Services.prefs.getBoolPref('mail.inappnotifications.enabled')&&!Services.prefs.getBoolPref('mailnews.start_page.enabled');"), 'Promotional notifications and the start page stay disabled')
                check(js("return [...ChromeUtils.importESModule('resource:///modules/MailServices.sys.mjs').MailServices.accounts.allServers].every(s=>s.type==='none');"), 'The test profile contains only local mail servers')
                js("const w=document.getElementById('tabmail').currentAbout3Pane;w.threadTree.selectedIndex=-1;for(let i=0;i<w.gDBView.rowCount;i++){if(w.gDBView.getMsgHdrAt(i).mime2DecodedSubject==='Website design review'){w.threadTree.selectedIndex=i;break;}}return true;")
                wait_for(lambda: js(f"return {view}?.messages?.length===4&&!{view}.hidden;"))
                wait_for(lambda: js(f"return {view}.shadowRoot.querySelector('browser')?.contentDocument?.querySelector('#messagepane')?.contentDocument?.body?.textContent?.includes('ready for review');"))
                from reliability import run as reliability_checks
                reliability_checks(js, wait_for, check, view)
                js("const w=document.getElementById('tabmail').currentAbout3Pane;const h=[...w.gDBView.msgFolder.messages].find(h=>h.messageId==='design-0@example.test');w.document.querySelector('conversation-view').show(h);return true;")
                wait_for(lambda: js(f"return {view}?.messages?.length===4;"))
                icons = js("const w=document.getElementById('tabmail').currentAbout3Pane;const row=w.document.querySelector('.card-layout');const info=row.querySelector('.thread-card-icon-info');const subject=row.querySelector('.subject');return {below:info.getBoundingClientRect().top>=subject.getBoundingClientRect().bottom-1,size:w.getComputedStyle(row.querySelector('.button-star')).backgroundSize};")
                check(icons['below'] and icons['size']=='13px 13px', 'Small star and attachment controls occupy a separate row below the subject')
                for attempt in range(2):
                    js("return (async()=>{const {AddonManager}=ChromeUtils.importESModule('resource://gre/modules/AddonManager.sys.mjs');const addon=await AddonManager.getAddonByID('outlook-bird@mocky.local');await addon.reload();return true;})();")
                    wait_for(lambda: js("const w=document.getElementById('tabmail').currentAbout3Pane;return document.querySelectorAll('#ob-ribbon').length===1&&w.document.querySelectorAll('#ob-folder-heading').length===1&&w.document.querySelectorAll('#ob-filter-tabs').length===1;"))
                    wait_for(lambda: js(f"const root={view}.shadowRoot;return [...root.querySelectorAll('article[aria-expanded=\"false\"]')].every(a=>a.dataset.obInitials)&&root.querySelectorAll('article[aria-expanded=\"false\"]').length===3;"))
                check(True, 'Initials and controls survive repeated reloads without disappearing or duplicating')
                check(js("return !Services.console.getMessageArray().some(e=>e instanceof Ci.nsIScriptError&&e.sourceName?.includes('outlook-bird')&&e.errorMessage?.includes('dead object'));"), 'Message-document cleanup produces no dead-document errors')
                from table_layout import run as table_checks
                table_checks(js, wait_for, check)
                if args.table_screenshot:
                    image = client.call('WebDriver:TakeScreenshot', {'full':False})
                    encoded = image['value'] if isinstance(image, dict) else image
                    args.table_screenshot.parent.mkdir(parents=True, exist_ok=True)
                    args.table_screenshot.write_bytes(base64.b64decode(encoded))
                from compose import run as compose_checks
                fixture = Path(temporary)/'draft-notes.txt'
                fixture.write_text('Local draft attachment fixture.')
                compose_checks(js, wait_for, check, fixture)
                client.call('Marionette:Quit', {'flags':['eAttemptQuit']})
                client.socket.close()
                client = None
                process.wait(timeout=15)
                process = subprocess.Popen([
                    args.thunderbird, '--headless', '--new-instance', '--offline',
                    '--profile', str(profile), '--marionette',
                ], env=environment, stdout=log, stderr=subprocess.STDOUT)
                client = wait_for(Marionette)
                wait_for(lambda: js("return !!document.getElementById('ob-ribbon')&&!!document.getElementById('tabmail').currentAbout3Pane;"))
                js("const w=document.getElementById('tabmail').currentAbout3Pane;const {MailServices}=ChromeUtils.importESModule('resource:///modules/MailServices.sys.mjs');w.displayFolder(MailServices.accounts.localFoldersServer.rootFolder.getChildNamed('Inbox').URI);window.resizeTo(1680,1000);return true;")
                wait_for(lambda: js("const w=document.getElementById('tabmail').currentAbout3Pane;return w.gDBView?.rowCount>=2;"))
                js("const w=document.getElementById('tabmail').currentAbout3Pane;w.threadTree.selectedIndex=-1;for(let i=0;i<w.gDBView.rowCount;i++){if(w.gDBView.getMsgHdrAt(i).mime2DecodedSubject==='Website design review'){w.threadTree.selectedIndex=i;break;}}return true;")
                wait_for(lambda: js(f"const v={view};return v?.messages?.length===4&&[...v.shadowRoot.querySelectorAll('article[aria-expanded=\"false\"]')].filter(a=>a.dataset.obInitials).length===3;"))
                wait_for(lambda: js(f"return {view}.shadowRoot.querySelector('browser')?.contentDocument?.querySelector('#messagepane')?.contentDocument?.body?.textContent?.includes('ready for review');"))
                check(True, 'Initials and message bodies render after quitting and relaunching the application')
                wait_for(lambda: js(f"return {view}.shadowRoot.querySelector('browser').contentDocument.querySelector('.ob-account-photo')?.naturalWidth>0;"))
                check(True, 'Configured sender photos survive a cold application restart')
                js("return (async()=>{const {AddonManager}=ChromeUtils.importESModule('resource://gre/modules/AddonManager.sys.mjs');await (await AddonManager.getAddonByID('outlook-bird@mocky.local')).disable();return true;})();")
                wait_for(lambda: js("return !document.getElementById('ob-ribbon');"))
                check(js(f"return !{view}.shadowRoot.querySelector('browser').contentDocument.documentElement.dataset.obMessage&&!{view}.shadowRoot.querySelector('browser').contentDocument.getElementById('messagepane').contentDocument.querySelector('[data-ob-reading-style]');"), 'Disabling the extension removes injected reader styles and controls')
                js("return (async()=>{const {AddonManager}=ChromeUtils.importESModule('resource://gre/modules/AddonManager.sys.mjs');await (await AddonManager.getAddonByID('outlook-bird@mocky.local')).enable();return true;})();")
                wait_for(lambda: js(f"return !!document.getElementById('ob-ribbon')&&{view}.shadowRoot.querySelector('browser').dataset.obLoadState==='ready';"))
                check(True, 'Re-enabling restores the layout without restarting')
                check(js("return ChromeUtils.importESModule('resource:///modules/MailServices.sys.mjs').MailServices.accounts.localFoldersServer.rootFolder.getChildNamed('Drafts').getTotalMessages(false)===1;"), 'The local draft remains saved after restarting the application')
                js("const w=document.getElementById('tabmail').currentAbout3Pane;w.paneLayout.folderPaneSplitter.width=292;w.paneLayout.messagePaneSplitter.width=Math.max(400,w.innerWidth-652);return true;")
                if args.screenshot:
                    image = client.call('WebDriver:TakeScreenshot', {'full':False})
                    encoded = image['value'] if isinstance(image, dict) else image
                    args.screenshot.parent.mkdir(parents=True, exist_ok=True)
                    args.screenshot.write_bytes(base64.b64decode(encoded))
            finally:
                if client:
                    try:
                        errors = js("return Services.console.getMessageArray().filter(e=>e instanceof Ci.nsIScriptError&&(/outlook-bird|moz-extension/.test(e.sourceName))).map(e=>e.errorMessage+' at '+e.sourceName+':'+e.lineNumber);")
                        if errors: print('Extension diagnostics:', errors, flush=True)
                    except Exception: pass
                if client:
                    client.close()
                if server:
                    server.shutdown()
                    server.server_close()
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--thunderbird', default='thunderbird')
    parser.add_argument('--workdir', type=Path, default=Path.cwd()/'work')
    parser.add_argument('--screenshot', type=Path)
    parser.add_argument('--table-screenshot', type=Path)
    run(parser.parse_args())
