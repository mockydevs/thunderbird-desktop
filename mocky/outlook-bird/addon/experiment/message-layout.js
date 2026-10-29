/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, you can obtain one at https://mozilla.org/MPL/2.0/. */

var OB_READING_STYLE = "__OUTLOOK_BIRD_MESSAGE_BODY_CSS__";

/** Decorates simple PR/author/description tables without changing email content. */
function decorateReviewTables(content) {
  const tables = [];
  for (const table of content.querySelectorAll("table")) {
    const rows = [...table.rows];
    const headers = [...(rows[0]?.cells || [])].map((cell) =>
      cell.textContent.trim().toLowerCase(),
    );
    if (
      headers.length !== 3 ||
      headers[0] !== "pr" ||
      headers[1] !== "author" ||
      !["what", "description"].includes(headers[2]) ||
      rows.some(
        (row) =>
          row.cells.length !== 3 ||
          [...row.cells].some(
            (cell) => cell.colSpan !== 1 || cell.rowSpan !== 1,
          ),
      )
    )
      continue;
    table.classList.add("ob-pr-table");
    tables.push(table);
  }
  return () => {
    for (const table of tables) table.classList.remove("ob-pr-table");
  };
}

/** Sizes a native message browser and places its attachment controls above the body. */
class MessageLayout {
  constructor(
    browser,
    pane,
    view,
    labels,
    updateControls,
    collapse,
    decoratePhotos,
  ) {
    this.browser = browser;
    this.pane = pane;
    this.view = view;
    this.labels = labels;
    this.updateControls = updateControls;
    this.collapse = collapse;
    this.decoratePhotos = decoratePhotos;
    this.cleanups = [];
    this.documentCleanups = [];
    this.attachmentCleanups = new Map();
    this.status = pane.document.createElement("div");
    this.status.classList.add("ob-message-loading");
    this.status.setAttribute("role", "status");
    this.status.setAttribute("aria-live", "polite");
    this.status.hidden = true;
    this.statusLabel = pane.document.createElement("span");
    this.status.append(this.statusLabel);
    this.retryButton = pane.document.createElement("button");
    this.retryButton.type = "button";
    this.retryButton.textContent = labels.retryMessage;
    this.retryButton.hidden = true;
    this.retryButton.addEventListener("click", () => this.retry());
    this.status.append(this.retryButton);
    browser.before(this.status);
    this.cleanups.push(() => this.status.remove());
    const visibility = new pane.MutationObserver(() => {
      this.status.hidden = browser.hidden || this.state === "ready";
    });
    visibility.observe(browser, {
      attributes: true,
      attributeFilter: ["hidden"],
    });
    this.cleanups.push(() => visibility.disconnect());
    this.contentCleanup = null;
    this.doc = null;
    this.contentDoc = null;
    this.frame = 0;
    this.destroyed = false;
    this.onLoad = () => this.render();
    browser.addEventListener("load", this.onLoad, true);
    browser.addEventListener("MsgLoaded", this.onLoad, true);
  }

  activate() {
    if (!this.view) return;
    for (const browser of this.view.shadowRoot.querySelectorAll("browser")) {
      delete browser.dataset.obActive;
    }
    this.browser.dataset.obActive = "true";
    this.updateControls();
  }

  setLoadingState(state) {
    if (this.destroyed || this.state === state) return;
    this.state = state;
    this.browser.dataset.obLoadState = state;
    this.status.hidden = this.browser.hidden || state === "ready";
    this.browser.setAttribute("aria-busy", String(state === "loading"));
    this.statusLabel.textContent =
      this.labels[
        state === "error"
          ? "messageLoadError"
          : state === "empty"
            ? "emptyMessage"
            : "loadingMessage"
      ];
    this.retryButton.hidden = state !== "error";
    if (this.loadTimer) this.pane.clearTimeout(this.loadTimer);
    this.loadTimer = 0;
    if (state === "loading") {
      const delay = Math.max(
        100,
        Math.min(
          60000,
          Services.prefs.getIntPref(
            "extensions.outlook-bird.loadTimeout",
            15000,
          ),
        ),
      );
      this.loadTimer = this.pane.setTimeout(() => {
        this.loadTimer = 0;
        this.setLoadingState("error");
      }, delay);
    }
  }

  retry() {
    if (this.destroyed || !this.doc?.defaultView.gMessageURI) return;
    this.setLoadingState("loading");
    try {
      this.doc.defaultView.ReloadMessage();
    } catch {
      this.setLoadingState("error");
    }
  }

  resetDocument() {
    if (this.contentCleanup) cleanupUI(this.contentCleanup);
    this.contentCleanup = null;
    this.contentDoc = null;
    for (const cleanup of this.attachmentCleanups.values()) cleanupUI(cleanup);
    this.attachmentCleanups.clear();
    for (const cleanup of this.documentCleanups) cleanupUI(cleanup);
    this.documentCleanups.length = 0;
  }

  render() {
    if (this.destroyed || !this.browser.isConnected) return;
    const doc = this.browser.contentDocument;
    if (doc?.documentURI !== "about:message") return;
    this.decoratePhotos(doc);
    const message = doc.getElementById("messagepane");
    if (!message) return;
    if (this.doc !== doc) {
      this.resetDocument();
      this.doc = doc;
      doc.documentElement.dataset.obMessage = "true";
      const singleMessage = doc.getElementById("singleMessage");
      const wasConversation =
        singleMessage.classList.contains("in-conversation");
      if (this.view) singleMessage.classList.add("in-conversation");
      this.documentCleanups.push(() => {
        singleMessage.classList.toggle("in-conversation", wasConversation);
      });
      const listener = {
        onStartHeaders: () => {
          this.previousBody = doc.getElementById("messagepane").contentDocument;
          this.setLoadingState("loading");
        },
        onEndHeaders: () => this.render(),
      };
      doc.defaultView.gMessageListeners.push(listener);
      this.documentCleanups.push(() => {
        const listeners = doc.defaultView.gMessageListeners;
        const index = listeners.indexOf(listener);
        if (index >= 0) listeners.splice(index, 1);
      });
      const attachment = doc.getElementById("attachmentView");
      const originalNext = attachment.nextSibling;
      message.before(attachment);
      const onContentLoad = () => this.render();
      message.addEventListener("load", onContentLoad, true);
      this.documentCleanups.push(() =>
        message.removeEventListener("load", onContentLoad, true),
      );
      const restoreAttachment = () => {
        if (originalNext?.parentNode === message.parentNode) {
          message.parentNode.insertBefore(attachment, originalNext);
        }
      };
      this.documentCleanups.push(restoreAttachment);
      const activate = () => this.activate();
      doc.addEventListener("pointerdown", activate, true);
      doc.addEventListener("focusin", activate, true);
      this.documentCleanups.push(() => {
        doc.removeEventListener("pointerdown", activate, true);
        doc.removeEventListener("focusin", activate, true);
        delete doc.documentElement.dataset.obMessage;
      });
      if (this.view) {
        const collapse = doc.createXULElement("toolbarbutton");
        collapse.classList.add(
          "toolbarbutton-1",
          "message-header-view-button",
          "ob-collapse-message",
        );
        collapse.setAttribute(
          "image",
          "chrome://messenger/skin/icons/new/compact/nav-up.svg",
        );
        collapse.setAttribute("tooltiptext", this.labels.collapseMessage);
        collapse.setAttribute("aria-label", this.labels.collapseMessage);
        collapse.addEventListener("command", () =>
          this.collapse(this.browser.parentElement),
        );
        doc.getElementById("header-view-toolbar").append(collapse);
        this.documentCleanups.push(() => collapse.remove());
      }
      const footer = doc.createElementNS("http://www.w3.org/1999/xhtml", "div");
      footer.classList.add("ob-message-actions");
      for (const [label, command] of [
        [this.labels.reply, "cmd_reply"],
        [this.labels.forward, "cmd_forward"],
      ]) {
        const button = doc.createElementNS(
          "http://www.w3.org/1999/xhtml",
          "button",
        );
        button.textContent = label;
        button.type = "button";
        button.dataset.obCommand = command;
        button.addEventListener("click", () => {
          const controller = doc.defaultView.commandController;
          if (controller.isCommandEnabled(command))
            controller.doCommand(command);
        });
        footer.append(button);
      }
      message.after(footer);
      this.documentCleanups.push(() => footer.remove());
      const changes = new doc.defaultView.MutationObserver(() => {
        this.attachmentCards();
        this.queueSize();
      });
      changes.observe(doc.getElementById("attachmentList"), {
        childList: true,
      });
      this.documentCleanups.push(() => changes.disconnect());
      const dimensions = new doc.defaultView.ResizeObserver(() =>
        this.queueSize(),
      );
      dimensions.observe(doc.getElementById("singleMessage"));
      dimensions.observe(attachment);
      this.documentCleanups.push(() => dimensions.disconnect());
    }
    const content = message.contentDocument;
    if (!doc.defaultView.gMessageURI) {
      this.setLoadingState("ready");
    } else if (content?.documentURI.startsWith("about:neterror")) {
      this.setLoadingState("error");
    } else if (
      content?.body &&
      content.documentURI !== "about:blank" &&
      content.readyState === "complete" &&
      content !== this.previousBody
    ) {
      const parts = [
        ...content.querySelectorAll(
          ".moz-text-html, .moz-text-plain, .moz-text-flowed",
        ),
      ];
      const hasBody = (parts.length ? parts : [content.body]).some(
        (part) =>
          part.textContent.trim() ||
          part.querySelector("img,table,svg,video,audio"),
      );
      this.setLoadingState(hasBody ? "ready" : "empty");
    } else if (this.state !== "loading" && this.state !== "error") {
      this.setLoadingState("loading");
    }
    if (
      content?.body &&
      content.documentURI !== "about:blank" &&
      content !== this.contentDoc
    ) {
      if (this.contentCleanup) cleanupUI(this.contentCleanup);
      this.contentDoc = content;
      const style = content.createElement("style");
      style.dataset.obReadingStyle = "true";
      style.textContent = OB_READING_STYLE;
      content.head.append(style);
      const restoreTables = decorateReviewTables(content);
      const dimensions = new content.defaultView.ResizeObserver(() =>
        this.queueSize(),
      );
      dimensions.observe(content.body);
      this.contentCleanup = () => {
        cleanupUI(() => dimensions.disconnect());
        cleanupUI(() => style.remove());
        cleanupUI(restoreTables);
      };
    }
    for (const button of doc.querySelectorAll(".ob-message-actions button")) {
      button.disabled = !doc.defaultView.commandController?.isCommandEnabled(
        button.dataset.obCommand,
      );
    }
    this.attachmentCards();
    if (
      this.view &&
      !this.view.shadowRoot.querySelector("browser[data-ob-active]")
    )
      this.activate();
    else this.updateControls();
    this.queueSize();
  }

  attachmentCards() {
    const list = this.doc?.getElementById("attachmentList");
    if (!list) return;
    for (const [item, cleanup] of this.attachmentCleanups) {
      if (!item.isConnected) {
        cleanupUI(cleanup);
        this.attachmentCleanups.delete(item);
      }
    }
    if (list.collapsed && list.itemCount)
      this.doc.defaultView.toggleAttachmentList(true, false);
    for (const item of list.querySelectorAll(".attachmentItem")) {
      if (item.querySelector(".ob-attachment-menu")) continue;
      const name = item.querySelector(".attachmentcell-name");
      const extension = item.querySelector(".attachmentcell-extension");
      const originalName = name.textContent;
      name.textContent = originalName + extension.textContent;

      const button = this.doc.createElementNS(
        "http://www.w3.org/1999/xhtml",
        "button",
      );
      button.classList.add("ob-attachment-menu");
      button.type = "button";
      button.setAttribute(
        "aria-label",
        this.labels.attachmentActions + ": " + item.attachment.name,
      );
      button.setAttribute("aria-haspopup", "menu");
      button.addEventListener("click", (event) => {
        event.stopPropagation();
        list.selectedItem = item;
        const popup = this.doc.getElementById("attachmentItemContext");
        popup.openPopup(button, "after_start", 0, 0, true, false, event);
      });
      item.append(button);
      this.attachmentCleanups.set(item, () => {
        button.remove();
        name.textContent = originalName;
      });
    }
  }

  queueSize() {
    if (this.destroyed || !this.view) return;
    if (!this.frame)
      this.frame = this.pane.requestAnimationFrame(() => {
        this.frame = 0;
        this.sizeToContent();
      });
  }

  sizeToContent() {
    if (this.destroyed) return;
    const doc = this.doc;
    const message = doc?.getElementById("messagepane");
    const body = message?.contentDocument?.body;
    if (!body || !this.browser.isConnected) return;
    const view = doc.defaultView;
    const margin = (element) => {
      const style = view.getComputedStyle(element);
      return (
        (parseFloat(style.marginBlockStart) || 0) +
        (parseFloat(style.marginBlockEnd) || 0)
      );
    };
    let height =
      Math.ceil(
        Math.max(body.scrollHeight, body.getBoundingClientRect().height),
      ) +
      margin(message) +
      4;
    for (const element of message.parentElement.children) {
      if (element !== message)
        height += element.getBoundingClientRect().height + margin(element);
    }
    height = Math.max(200, Math.ceil(height));
    if (this.browser.style.blockSize !== `${height}px`) {
      this.browser.style.blockSize = `${height}px`;
      this.browser.style.minBlockSize = `${height}px`;
    }
    this.browser.parentElement.style.minHeight = "0px";
  }

  destroy() {
    this.destroyed = true;
    cleanupUI(() =>
      this.browser.removeEventListener("load", this.onLoad, true),
    );
    cleanupUI(() =>
      this.browser.removeEventListener("MsgLoaded", this.onLoad, true),
    );
    if (this.frame) cleanupUI(() => this.pane.cancelAnimationFrame(this.frame));
    if (this.loadTimer) cleanupUI(() => this.pane.clearTimeout(this.loadTimer));
    this.resetDocument();
    for (const cleanup of this.cleanups) cleanupUI(cleanup);
    this.cleanups.length = 0;
    cleanupUI(() => this.browser.style.removeProperty("block-size"));
    cleanupUI(() => this.browser.style.removeProperty("min-block-size"));
    cleanupUI(() => {
      delete this.browser.dataset.obLoadState;
      delete this.browser.dataset.obActive;
      this.browser.removeAttribute("aria-busy");
    });
  }
}
