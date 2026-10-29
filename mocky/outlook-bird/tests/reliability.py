# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, you can obtain one at https://mozilla.org/MPL/2.0/.
"""Additional real-application checks; all messages stay in Local Folders."""
import json
import time


def run(js, wait_for, check, view):
    single = "document.getElementById('tabmail').currentAbout3Pane.document.getElementById('messageBrowser')"
    js("const w=document.getElementById('tabmail').currentAbout3Pane;const h=[...w.gDBView.msgFolder.messages].find(h=>h.messageId==='design-3@example.test');w.messagePane.displayMessage(h.folder.getUriForMsg(h));return true;")
    wait_for(lambda: js(f"return {single}.contentDocument?.documentElement.dataset.obMessage==='true'&&{single}.contentDocument.getElementById('messagepane').contentDocument?.body?.textContent.includes('ready for review');"))
    check(js(f"const d={single}.contentDocument;return d.getElementById('attachmentView').getBoundingClientRect().bottom<=d.getElementById('messagepane').getBoundingClientRect().top&&d.getElementById('messagepane').contentWindow.getComputedStyle(d.getElementById('messagepane').contentDocument.body).fontSize==='14px';"), 'Single-message HTML uses the same reading size and top attachments')
    # Navigate within one native reader to catch stale observers and attachment menus.
    js("const w=document.getElementById('tabmail').currentAbout3Pane;const h=[...w.gDBView.msgFolder.messages].find(h=>h.messageId==='design-0@example.test');w.messagePane.displayMessage(h.folder.getUriForMsg(h));return true;")
    wait_for(lambda: js(f"return {single}.contentDocument.getElementById('messagepane').contentDocument?.body?.textContent.includes('updated proposal');"))
    check(js(f"const d={single}.contentDocument;return d.querySelectorAll('.ob-attachment-menu').length===1&&d.getElementById('messagepane').contentWindow.getComputedStyle(d.getElementById('messagepane').contentDocument.body).fontSize==='14px';"), 'Plain-text navigation keeps consistent typography without duplicate attachment controls')
    # Simulate a MIME browser that never delivers a body, then exercise native reload.
    js(f"const d={single}.contentDocument;Services.prefs.setIntPref('extensions.outlook-bird.loadTimeout',100);d.getElementById('messagepane').setAttribute('src','about:blank');for(const l of d.defaultView.gMessageListeners) l.onStartHeaders?.();return true;")
    wait_for(lambda: js(f"return {single}.dataset.obLoadState==='error';"))
    check(js(f"const s={single}.previousElementSibling;return !s.hidden&&s.getAttribute('role')==='status'&&!s.querySelector('button').hidden;"), 'A stalled message exposes an accessible retry action')
    js(f"{single}.previousElementSibling.querySelector('button').click();return true;")
    wait_for(lambda: js(f"return {single}.dataset.obLoadState==='ready'&&{single}.contentDocument.getElementById('messagepane').contentDocument?.body?.textContent.includes('updated proposal');"))
    js("Services.prefs.clearUserPref('extensions.outlook-bird.loadTimeout');return true;")
    check(True, 'Retry reloads the original message through Thunderbird')
    empty = 'From: Empty fixture <empty@example.test>\r\nTo: preview@example.test\r\nSubject: Empty message\r\nMessage-ID: <empty@example.test>\r\nMIME-Version: 1.0\r\nContent-Type: text/html; charset=UTF-8\r\n\r\n<html><body></body></html>\r\n'
    js("const w=document.getElementById('tabmail').currentAbout3Pane;const f=w.gDBView.msgFolder;const h=f.QueryInterface(Ci.nsIMsgLocalMailFolder).addMessage("+json.dumps(empty)+");w.messagePane.displayMessage(f.getUriForMsg(h));return true;")
    try:
        wait_for(lambda: js(f"return {single}.dataset.obLoadState==='empty';"))
    except AssertionError:
        print(js(f"const b={single};return {{state:b.dataset.obLoadState,body:b.contentDocument.getElementById('messagepane').contentDocument.body.outerHTML}};"), flush=True)
        raise
    check(js(f"return {single}.previousElementSibling.textContent.includes('no body text');"), 'An empty message is explained instead of appearing broken')

    # Large threads create summaries, not a native browser for every message.
    messages = []
    for i in range(120):
        messages.append(f'From: Bulk fixture <bulk@example.test>\r\nTo: preview@example.test\r\nSubject: {"Re: " if i else ""}Large local thread\r\nMessage-ID: <bulk-{i}@example.test>\r\n'+(f'In-Reply-To: <bulk-{i-1}@example.test>\r\nReferences: <bulk-0@example.test>\r\n' if i else '')+f'Date: Thu, 29 Oct 2026 12:{i//60:02d}:{i%60:02d} +0300\r\n\r\nLocal message {i}.\r\n')
    started = time.monotonic()
    js("const f=document.getElementById('tabmail').currentAbout3Pane.gDBView.msgFolder;for(const raw of "+json.dumps(messages)+")f.QueryInterface(Ci.nsIMsgLocalMailFolder).addMessage(raw);return true;")
    js("const w=document.getElementById('tabmail').currentAbout3Pane;const h=[...w.gDBView.msgFolder.messages].find(h=>h.messageId==='bulk-0@example.test');w.document.querySelector('conversation-view').show(h);return true;")
    wait_for(lambda: js(f"return {view}.messages?.length===120&&{view}.shadowRoot.querySelectorAll('article').length===120;"))
    check(js(f"return {view}.shadowRoot.querySelectorAll('browser').length===1;"), 'A 120-message thread keeps only one initial message browser')
    print(f'Large-thread fixture loaded in {time.monotonic()-started:.2f}s (includes local imports).', flush=True)
    # Expand two independently and verify keyboard focus follows the requested card.
    for index in [1, 2]:
        js(f"const a={view}.shadowRoot.querySelectorAll('article[aria-expanded=\"false\"]')[{index}];const id=a.dataset.messageId;a.focus();a.dispatchEvent(new a.ownerDocument.defaultView.KeyboardEvent('keydown',{{key:'Enter',bubbles:true}}));return true;")
        check(js(f"return {view}.shadowRoot.activeElement?.getAttribute('aria-expanded')==='true';"), 'Keyboard focus follows the newly expanded conversation card')

    js("window.resizeTo(1100,780);const w=document.getElementById('tabmail').currentAbout3Pane;w.document.querySelector('#ob-filter-tabs button').focus({focusVisible:true});return true;")
    wait_for(lambda: js("return window.innerWidth<=1100;"))
    check(js("const r=document.getElementById('ob-ribbon');return r.scrollWidth<=r.clientWidth+1;"), 'Mail toolbar fits a smaller desktop window')
    check(js("const w=document.getElementById('tabmail').currentAbout3Pane;const b=w.document.querySelector('#ob-filter-tabs button');const s=w.getComputedStyle(b);return s.outlineStyle==='none'&&s.boxShadow==='none'&&parseFloat(s.borderTopWidth)===1;"), 'Keyboard focus uses one visible border rather than stacked rings')
    # Headless Linux cannot switch the OS accessibility theme. Exercise the
    # shipped forced-colour declarations directly, without claiming an OS test.
    check(js("""const w=document.getElementById('tabmail').currentAbout3Pane;
const rules=[];
function visit(sheet){for(const rule of sheet.cssRules||[]){
if(rule.styleSheet)visit(rule.styleSheet);
else if(rule.conditionText?.includes('forced-colors'))rules.push(...[...rule.cssRules].map(r=>r.cssText));
else if(rule.cssRules)visit(rule);
}}
for(const sheet of w.document.styleSheets)visit(sheet);
const style=w.document.createElement('style');style.textContent=rules.join('\\n');w.document.head.append(style);
const button=w.document.querySelector('#ob-filter-tabs button');button.focus({focusVisible:true});
const computed=w.getComputedStyle(button);
const valid=rules.length>0&&computed.outlineStyle==='none'&&computed.borderTopStyle==='solid'&&computed.borderTopColor!=='transparent';
style.remove();return valid;"""), 'Shipped forced-colour focus rules keep a single visible border')
    js("const w=document.getElementById('tabmail').currentAbout3Pane;w.browsingContext.fullZoom=1.5;return true;")
    wait_for(lambda: js("return document.getElementById('tabmail').currentAbout3Pane.browsingContext.fullZoom===1.5;"))
    check(js(f"return {view}.clientWidth>0&&{view}.shadowRoot.querySelector('article')?.getBoundingClientRect().width<={view}.clientWidth;"), 'Conversation cards remain inside the reading pane at 150 percent zoom')
    js("document.getElementById('tabmail').currentAbout3Pane.browsingContext.fullZoom=1;window.resizeTo(1680,1000);return true;")

    js("const {MailServices}=ChromeUtils.importESModule('resource:///modules/MailServices.sys.mjs');const f=MailServices.accounts.localFoldersServer.rootFolder.getChildNamed('Inbox');const h=[...f.messages].find(h=>h.messageId==='design-3@example.test');ChromeUtils.importESModule('resource:///modules/MailUtils.sys.mjs').MailUtils.openMessageInNewWindow(h);return true;")
    standalone = "Services.wm.getMostRecentWindow('mail:messageWindow')"
    wait_for(lambda: js(f"return {standalone}?.document.getElementById('messageBrowser')?.contentDocument?.documentElement.dataset.obMessage==='true';"))
    wait_for(lambda: js(f"return {standalone}.document.getElementById('messageBrowser').contentDocument.getElementById('messagepane').contentDocument?.body?.textContent.includes('ready for review');"))
    check(js(f"const d={standalone}.document.getElementById('messageBrowser').contentDocument;return d.getElementById('attachmentView').getBoundingClientRect().bottom<=d.getElementById('messagepane').getBoundingClientRect().top;"), 'Separate message windows use the same top attachment layout')
    js(f"{standalone}.close();return true;")
