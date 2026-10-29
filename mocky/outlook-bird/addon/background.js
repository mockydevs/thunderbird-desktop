/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, you can obtain one at https://mozilla.org/MPL/2.0/. */

const keys = [
  "newMail",
  "delete",
  "archive",
  "reply",
  "replyAll",
  "forward",
  "readUnread",
  "print",
  "mailActions",
  "mail",
  "folders",
  "readStatus",
  "all",
  "unread",
  "searchMail",
  "collapseMessage",
  "attachmentActions",
  "loadingMessage",
];
const labels = Object.fromEntries(
  keys.map((key) => [key, messenger.i18n.getMessage(key)]),
);
messenger.outlookBird.start(labels).catch(console.error);
