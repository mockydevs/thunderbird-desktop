# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, you can obtain one at https://mozilla.org/MPL/2.0/.
"""Real native-reader regression for narrow PR identifiers and author columns."""
import json


def run(js, wait_for, check):
    description = 'Improve the document editor so that opening, editing and saving embedded artwork preserves its original format and all supported changes. ' * 3
    html = '<html><body><h2>Planned PRs</h2><table><thead><tr><th>PR</th><th>Author</th><th>What</th></tr></thead><tbody>'
    html += '<tr><td><a href="https://example.test/pr/123456">#123456</a></td><td><a href="https://example.test/author">@averylongreviewerauthorname</a></td><td>'+description+'</td></tr>'
    html += '<tr><td>#8571</td><td>@reviewer</td><td>Retain native attachment actions and keyboard access.</td></tr></tbody></table><table id="other-table"><tr><th>Product</th><th>Author</th><th>What</th></tr><tr><td>Sample</td><td>A</td><td>Untouched layout</td></tr></table></body></html>'
    raw = 'From: Review fixture <review@example.test>\r\nTo: preview@example.test\r\nSubject: PR table layout\r\nMessage-ID: <table@example.test>\r\nMIME-Version: 1.0\r\nContent-Type: text/html; charset=UTF-8\r\n\r\n'+html+'\r\n'
    js("const w=document.getElementById('tabmail').currentAbout3Pane;const f=w.gDBView.msgFolder;const h=f.QueryInterface(Ci.nsIMsgLocalMailFolder).addMessage("+json.dumps(raw)+");w.messagePane.displayMessage(f.getUriForMsg(h));return true;")
    document = "document.getElementById('tabmail').currentAbout3Pane.document.getElementById('messageBrowser').contentDocument.getElementById('messagepane').contentDocument"
    wait_for(lambda: js(f"return !!{document}?.querySelector('.ob-pr-table');"))
    geometry = js(f"""const d={document};const t=d.querySelector('.ob-pr-table');const cells=t.rows[1].cells;
function lines(node){{const range=d.createRange();range.selectNodeContents(node);return new Set([...range.getClientRects()].filter(r=>r.width>0).map(r=>Math.round(r.top))).size;}}
return {{pr:lines(cells[0].firstChild),author:lines(cells[1].firstChild),description:cells[2].clientHeight, lineHeight:parseFloat(d.defaultView.getComputedStyle(cells[2]).lineHeight),authorWidth:cells[1].clientWidth,descWidth:cells[2].clientWidth,tableWidth:t.getBoundingClientRect().width,bodyWidth:d.body.clientWidth,other:d.getElementById('other-table').classList.contains('ob-pr-table')}};""")
    check(geometry['pr']==1 and geometry['author']==1, 'PR numbers and full author names stay on one line')
    check(geometry['description']>=geometry['lineHeight']*3 and geometry['descWidth']>geometry['authorWidth'], 'Descriptions wrap over multiple lines in the remaining table width')
    check(geometry['tableWidth']<=geometry['bodyWidth']+1, 'Review table fits within the reading pane')
    check(not geometry['other'], 'Unrelated email tables retain their original layout')
