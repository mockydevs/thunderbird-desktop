# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, you can obtain one at https://mozilla.org/MPL/2.0/.
"""Local draft/reply/forward checks; no outgoing server is configured."""
import json

COMPOSE = "Services.wm.getMostRecentWindow('msgcompose')"


def run(js, wait_for, check, fixture):
    js("const {MailServices}=ChromeUtils.importESModule('resource:///modules/MailServices.sys.mjs');const root=MailServices.accounts.localFoldersServer.rootFolder;if(!root.containsChildNamed('Drafts'))root.createSubfolder('Drafts',null);return true;")
    wait_for(lambda: js("return ChromeUtils.importESModule('resource:///modules/MailServices.sys.mjs').MailServices.accounts.localFoldersServer.rootFolder.containsChildNamed('Drafts');"))
    js("const {MailServices}=ChromeUtils.importESModule('resource:///modules/MailServices.sys.mjs');const identity=MailServices.accounts.createIdentity();identity.email='preview@example.test';identity.fullName='Local preview';identity.htmlSigFormat=true;identity.htmlSigText='<p>Local preview signature</p>';const account=MailServices.accounts.accounts[0];account.addIdentity(identity);account.defaultIdentity=identity;const drafts=MailServices.accounts.localFoldersServer.rootFolder.getChildNamed('Drafts');drafts.setFlag(Ci.nsMsgFolderFlags.Drafts);identity.draftsFolderURI=drafts.URI;identity.doFcc=false;return true;")
    js("const {MailServices}=ChromeUtils.importESModule('resource:///modules/MailServices.sys.mjs');const params=Cc['@mozilla.org/messengercompose/composeparams;1'].createInstance(Ci.nsIMsgComposeParams);params.identity=MailServices.accounts.accounts[0].defaultIdentity;params.type=Ci.nsIMsgCompType.New;params.format=Ci.nsIMsgCompFormat.HTML;params.composeFields=Cc['@mozilla.org/messengercompose/composefields;1'].createInstance(Ci.nsIMsgCompFields);params.composeFields.to='recipient@example.test';params.composeFields.subject='Local draft recovery';params.composeFields.body='<p>Draft survives closing and reopening.</p>';const attachment=Cc['@mozilla.org/messengercompose/attachment;1'].createInstance(Ci.nsIMsgAttachment);const file=Cc['@mozilla.org/file/local;1'].createInstance(Ci.nsIFile);file.initWithPath("+json.dumps(str(fixture))+");attachment.url=Services.io.newFileURI(file).spec;attachment.name='draft-notes.txt';params.composeFields.addAttachment(attachment);MailServices.compose.OpenComposeWindowWithParams(null,params);return true;")
    wait_for(lambda: js(f"return !!{COMPOSE}?.gMsgCompose?.editor?.document?.body?.textContent.includes('Draft survives');"))
    check(js(f"const w={COMPOSE};return w.document.getElementById('msgSubject').value==='Local draft recovery'&&w.document.getElementById('attachmentBucket').itemCount===1;"), 'Native compose preserves subject and visible attachment')
    check(js(f"const w={COMPOSE};return w.getComputedStyle(w.document.getElementById('msgSubject')).fontSize==='15px';"), 'Compose window loads the readable subject styling')
    check(js(f"return {COMPOSE}.gMsgCompose.editor.document.body.textContent.includes('Local preview signature');"), 'The native signature remains present in a new message')
    js(f"return (async()=>{{await {COMPOSE}.SaveAsDraft();return true;}})();")
    wait_for(lambda: js("return ChromeUtils.importESModule('resource:///modules/MailServices.sys.mjs').MailServices.accounts.localFoldersServer.rootFolder.getChildNamed('Drafts').getTotalMessages(false)===1;"))
    js(f"{COMPOSE}.gContentChanged=false;{COMPOSE}.gMsgCompose.bodyModified=false;{COMPOSE}.close();return true;")
    wait_for(lambda: js(f"return !{COMPOSE};"))
    js("const {MailServices}=ChromeUtils.importESModule('resource:///modules/MailServices.sys.mjs');const drafts=MailServices.accounts.localFoldersServer.rootFolder.getChildNamed('Drafts');const header=[...drafts.messages][0];MailServices.compose.OpenComposeWindow(null,header,drafts.getUriForMsg(header),Ci.nsIMsgCompType.Draft,Ci.nsIMsgCompFormat.Default,MailServices.accounts.accounts[0].defaultIdentity,null,null);return true;")
    wait_for(lambda: js(f"return !!{COMPOSE}?.gMsgCompose?.editor?.document?.body?.textContent.includes('Draft survives');"))
    check(js(f"return {COMPOSE}.document.getElementById('attachmentBucket').itemCount===1;"), 'A saved local draft reopens with its body and attachment')
    js(f"{COMPOSE}.gContentChanged=false;{COMPOSE}.gMsgCompose.bodyModified=false;{COMPOSE}.close();return true;")
    wait_for(lambda: js(f"return !{COMPOSE};"))
    for name, kind in [('reply', 'Reply'), ('forward', 'ForwardAsAttachment')]:
        js("const {MailServices}=ChromeUtils.importESModule('resource:///modules/MailServices.sys.mjs');const f=MailServices.accounts.localFoldersServer.rootFolder.getChildNamed('Inbox');const h=[...f.messages].find(h=>h.messageId==='design-0@example.test');MailServices.compose.OpenComposeWindow(null,h,f.getUriForMsg(h),Ci.nsIMsgCompType."+kind+",Ci.nsIMsgCompFormat.Default,MailServices.accounts.accounts[0].defaultIdentity,null,null);return true;")
        wait_for(lambda: js(f"return !!{COMPOSE}?.gMsgCompose?.editor?.document?.body;"))
        if name == 'reply':
            wait_for(lambda: js(f"return {COMPOSE}.gMsgCompose.editor.document.body.textContent.includes('updated proposal');"))
            check(True, 'Reply retains the quoted original message')
        else:
            wait_for(lambda: js(f"return {COMPOSE}.document.getElementById('attachmentBucket').itemCount===1;"))
            check(True, 'Forward as attachment retains the original message')
        js(f"{COMPOSE}.gContentChanged=false;{COMPOSE}.gMsgCompose.bodyModified=false;{COMPOSE}.close();return true;")
        wait_for(lambda: js(f"return !{COMPOSE};"))
    check(js("return ChromeUtils.importESModule('resource:///modules/MailServices.sys.mjs').MailServices.outgoingServer.servers.length===0;"), 'Compose tests have no SMTP server and cannot send mail')
