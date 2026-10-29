/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, you can obtain one at https://mozilla.org/MPL/2.0/. */

var OB_READING_STYLE = "__OUTLOOK_BIRD_MESSAGE_BODY_CSS__";

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
    this.status = pane.document.createElement("div");
    this.status.classList.add("ob-message-loading");
    this.status.textContent = labels.loadingMessage;
    browser.before(this.status);
    this.cleanups.push(() => this.status.remove());
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
    for (const browser of this.view.shadowRoot.querySelectorAll("browser")) {
      delete browser.dataset.obActive;
    }
    this.browser.dataset.obActive = "true";
    this.updateControls();
  }

  render() {
    if (this.destroyed || !this.browser.isConnected) return;
    const doc = this.browser.contentDocument;
    if (doc?.documentURI !== "about:message") return;
    this.decoratePhotos(doc);
    const message = doc.getElementById("messagepane");
    if (!message) return;
    if (this.doc !== doc) {
      this.doc = doc;
      doc.documentElement.dataset.obMessage = "true";
      doc.getElementById("singleMessage").classList.add("in-conversation");
      const attachment = doc.getElementById("attachmentView");
      const originalNext = attachment.nextSibling;
      message.before(attachment);
      const onContentLoad = () => this.render();
      message.addEventListener("load", onContentLoad, true);
      this.cleanups.push(() =>
        message.removeEventListener("load", onContentLoad, true),
      );
      const restoreAttachment = () => {
        if (originalNext?.parentNode === message.parentNode) {
          message.parentNode.insertBefore(attachment, originalNext);
        }
      };
      this.cleanups.push(restoreAttachment);
      const activate = () => this.activate();
      doc.addEventListener("pointerdown", activate, true);
      doc.addEventListener("focusin", activate, true);
      this.cleanups.push(() => {
        doc.removeEventListener("pointerdown", activate, true);
        doc.removeEventListener("focusin", activate, true);
        delete doc.documentElement.dataset.obMessage;
      });
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
      this.cleanups.push(() => collapse.remove());
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
      this.cleanups.push(() => footer.remove());
      const changes = new doc.defaultView.MutationObserver(() => {
        this.attachmentCards();
        this.queueSize();
      });
      changes.observe(doc.getElementById("attachmentList"), {
        childList: true,
      });
      this.cleanups.push(() => changes.disconnect());
      const dimensions = new doc.defaultView.ResizeObserver(() =>
        this.queueSize(),
      );
      dimensions.observe(doc.getElementById("singleMessage"));
      dimensions.observe(attachment);
      this.cleanups.push(() => dimensions.disconnect());
    }
    const content = message.contentDocument;
    this.status.hidden =
      !!content?.body &&
      content.documentURI !== "about:blank" &&
      (content.body.textContent.trim().length > 0 ||
        content.body.querySelector("img,table") ||
        content.readyState === "complete");
    if (
      content?.body &&
      content.documentURI !== "about:blank" &&
      content !== this.contentDoc
    ) {
      if (this.contentCleanup) cleanupUI(this.contentCleanup);
      this.contentDoc = content;
      const style = content.createElement("style");
      style.textContent = OB_READING_STYLE;
      content.head.append(style);
      const dimensions = new content.defaultView.ResizeObserver(() =>
        this.queueSize(),
      );
      dimensions.observe(content.body);
      this.contentCleanup = () => {
        cleanupUI(() => dimensions.disconnect());
        cleanupUI(() => style.remove());
      };
    }
    for (const button of doc.querySelectorAll(".ob-message-actions button")) {
      button.disabled = !doc.defaultView.commandController?.isCommandEnabled(
        button.dataset.obCommand,
      );
    }
    this.attachmentCards();
    if (!this.view.shadowRoot.querySelector("browser[data-ob-active]"))
      this.activate();
    else this.updateControls();
    this.queueSize();
  }

  attachmentCards() {
    const list = this.doc?.getElementById("attachmentList");
    if (!list) return;
    if (list.collapsed && list.itemCount)
      this.doc.defaultView.toggleAttachmentList(true, false);
    for (const item of list.querySelectorAll(".attachmentItem")) {
      if (item.querySelector(".ob-attachment-menu")) continue;
      const name = item.querySelector(".attachmentcell-name");
      const extension = item.querySelector(".attachmentcell-extension");
      const originalName = name.textContent;
      name.textContent = originalName + extension.textContent;
      this.cleanups.push(() => {
        name.textContent = originalName;
      });
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
      this.cleanups.push(() => button.remove());
    }
  }

  queueSize() {
    if (this.destroyed) return;
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
    if (this.contentCleanup) cleanupUI(this.contentCleanup);
    for (const cleanup of this.cleanups) cleanupUI(cleanup);
    this.cleanups.length = 0;
    cleanupUI(() => this.browser.style.removeProperty("block-size"));
    cleanupUI(() => this.browser.style.removeProperty("min-block-size"));
  }
}

