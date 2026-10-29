/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, you can obtain one at https://mozilla.org/MPL/2.0/. */

/* Shadow-root styling for Thunderbird 159's native conversation component. */
var OB_CONVERSATION_STYLE = "__OUTLOOK_BIRD_CONVERSATION_CSS__";

// Profile-owned images remain private and never require a remote request.
var OB_AVATARS = {};
function avatarFor(sender) {
  const address = sender.match(/<([^>]+)>/)?.[1] || sender.trim();
  return OB_AVATARS[address.toLowerCase()] || "";
}
function paintPhoto(node, sender) {
  const photo = avatarFor(sender);
  node.style.setProperty(
    "--ob-avatar-photo",
    photo ? `url("${photo}")` : "none",
  );
  node.toggleAttribute("data-ob-photo", Boolean(photo));
}

/** Completes teardown even after a removed message document destroys its wrappers. */
function cleanupUI(callback) {
  try {
    callback();
  } catch (error) {
    if (!String(error).includes("dead object")) console.error(error);
  }
}

/* __OUTLOOK_BIRD_MESSAGE_LAYOUT__ */

/** Watches the native sender header without inspecting the message body. */
function watchSenderPhoto(messageDoc, win) {
  const paint = () => {
    const sender = messageDoc.defaultView.gMessage?.mime2DecodedAuthor || "";
    const photo = avatarFor(sender);
    for (const avatar of messageDoc.querySelectorAll(
      "#expandedfromBox .recipient-avatar",
    )) {
      let image = avatar.querySelector("img.ob-account-photo");
      if (!photo) {
        image?.remove();
        continue;
      }
      if (!image) {
        image = messageDoc.createElementNS(
          "http://www.w3.org/1999/xhtml",
          "img",
        );
        image.classList.add("ob-account-photo");
        image.alt = "";
        image.style.cssText =
          "position:absolute;inset:0;width:100%;height:100%;object-fit:contain;background:white;border-radius:50%";
        avatar.style.position = "relative";
        avatar.append(image);
      }
      if (image.src !== photo) image.src = photo;
    }
  };
  let frame = 0;
  const schedule = () => {
    if (!frame)
      frame = win.requestAnimationFrame(() => {
        frame = 0;
        paint();
      });
  };
  const observer = new win.MutationObserver(schedule);
  observer.observe(
    messageDoc.getElementById("expandedfromBox") || messageDoc.documentElement,
    {
      childList: true,
      subtree: true,
    },
  );
  messageDoc.addEventListener("MsgLoaded", paint, true);
  const cleanup = () => {
    observer.disconnect();
    if (frame) win.cancelAnimationFrame(frame);
    messageDoc.removeEventListener("MsgLoaded", paint, true);
    messageDoc
      .querySelectorAll(".ob-account-photo")
      .forEach((image) => image.remove());
  };
  paint();
  return cleanup;
}

/* UI-only experiment. Mail actions run solely after an explicit toolbar click. */
var { ExtensionCommon } = ChromeUtils.importESModule(
  "resource://gre/modules/ExtensionCommon.sys.mjs",
);
var { ExtensionSupport } = ChromeUtils.importESModule(
  "resource:///modules/ExtensionSupport.sys.mjs",
);

/** Adds mail controls, cached previews and folder-local conversation cards. */
var outlookBird = class extends ExtensionCommon.ExtensionAPI {
  /** @type {Map<Window, Array<() => void>>} */
  windows = new Map();
  registered = false;
  /** @type {boolean|null} */
  originalConversationPref = null;

  getAPI() {
    return {
      outlookBird: {
        start: async (labels) => {
          this.labels = labels;
          try {
            const file = PathUtils.join(
              Services.dirsvc.get("ProfD", Ci.nsIFile).path,
              "chrome",
              "avatars.json",
            );
            const images = await IOUtils.readJSON(file);
            OB_AVATARS = Object.fromEntries(
              Object.entries(images).filter(
                ([email, uri]) =>
                  email.includes("@") &&
                  typeof uri === "string" &&
                  uri.length < 2000000 &&
                  /^data:image\/(png|jpeg);base64,[A-Za-z0-9+/=]+$/.test(uri),
              ),
            );
          } catch (error) {
            OB_AVATARS = {};
            if (error.name !== "NotFoundError")
              console.warn("Unable to read local avatar configuration");
          }
          if (this.registered) return;
          this.registered = true;
          this.originalConversationPref = Services.prefs.getBoolPref(
            "mail.thread.conversation.enabled",
            false,
          );
          Services.prefs.setBoolPref("mail.thread.conversation.enabled", true);
          ExtensionSupport.registerWindowListener(this.extension.id, {
            chromeURLs: [
              "chrome://messenger/content/messenger.xhtml",
              "chrome://messenger/content/messageWindow.xhtml",
            ],
            onLoadWindow: (win) => {
              if (win.document.documentURI.endsWith("/messageWindow.xhtml"))
                this.attachReadingWindow(win);
              else this.attach(win);
            },
            onUnloadWindow: (win) => this.detach(win),
          });
        },
      },
    };
  }

  /**
   * Adds the toolbar and registers pane decoration for a mail window.
   *
   * @param {Window} win - Thunderbird's main mail window.
   */
  attach(win) {
    if (this.windows.has(win)) return;
    const doc = win.document;
    const cleanups = [];
    this.windows.set(win, cleanups);
    const ribbon = doc.createElementNS("http://www.w3.org/1999/xhtml", "div");
    ribbon.id = "ob-ribbon";
    ribbon.setAttribute("role", "toolbar");
    ribbon.setAttribute("aria-label", this.labels.mailActions);
    const actions = [
      [this.labels.newMail, "cmd_newMessage", "new-mail", "ob-new"],
      [this.labels.delete, "cmd_delete", "trash"],
      [this.labels.archive, "cmd_archive", "archive"],
      null,
      [this.labels.reply, "cmd_reply", "reply"],
      [this.labels.replyAll, "cmd_replyall", "reply-all"],
      [this.labels.forward, "cmd_forward", "forward"],
      null,
      [this.labels.readUnread, "cmd_toggleRead", "unread"],
      [this.labels.print, "cmd_print", "print"],
    ];
    const browserCommands = new Set([
      "cmd_reply",
      "cmd_replyall",
      "cmd_forward",
      "cmd_print",
    ]);
    /**
     * Returns the active message controller for reply, forward and print.
     * Other commands use the main window's selection controller.
     *
     * @param {string} command - Native Thunderbird command ID.
     * @returns {nsIController|null} The controller for the command.
     */
    const controllerFor = (command) => {
      const pane = doc.getElementById("tabmail").currentAbout3Pane;
      const conversation = pane?.document.querySelector("conversation-view");
      const browser =
        conversation && !conversation.hidden
          ? conversation.shadowRoot?.querySelector("browser[data-ob-active]") ||
            [
              ...(conversation.shadowRoot?.querySelectorAll("browser") || []),
            ].at(-1)
          : null;
      if (browser && browserCommands.has(command))
        return browser.contentWindow.commandController;
      return doc.commandDispatcher.getControllerForCommand(command);
    };
    const updateControls = () => {
      for (const button of ribbon.querySelectorAll("[data-ob-command]")) {
        const command = button.dataset.obCommand;
        try {
          button.disabled = !controllerFor(command)?.isCommandEnabled(command);
        } catch {
          button.disabled = true;
        }
      }
    };
    for (const action of actions) {
      if (!action) {
        const separator = doc.createElementNS(
          "http://www.w3.org/1999/xhtml",
          "span",
        );
        separator.classList.add("ob-separator");
        separator.setAttribute("aria-hidden", "true");
        ribbon.append(separator);
        continue;
      }
      const [label, command, icon, className] = action;
      const button = doc.createXULElement("toolbarbutton");
      button.setAttribute("label", label);
      button.setAttribute("tooltiptext", label);
      button.dataset.obCommand = command;
      button.addEventListener("command", () => {
        const controller = controllerFor(command);
        if (controller?.isCommandEnabled(command))
          controller.doCommand(command);
        updateControls();
      });
      button.classList.add("toolbarbutton-1");
      if (className) button.classList.add(className);
      button.setAttribute(
        "image",
        `chrome://messenger/skin/icons/new/compact/${icon}.svg`,
      );
      ribbon.append(button);
    }
    doc.getElementById("navigation-toolbox").append(ribbon);
    cleanups.push(() => ribbon.remove());
    for (const event of ["select", "MsgLoaded", "TabSelect", "focus"]) {
      doc.addEventListener(event, updateControls, true);
      cleanups.push(() => doc.removeEventListener(event, updateControls, true));
    }
    const commands = new win.MutationObserver(updateControls);
    for (const command of doc.querySelectorAll("command"))
      commands.observe(command, {
        attributes: true,
        attributeFilter: ["disabled"],
      });
    cleanups.push(() => commands.disconnect());
    updateControls();

    const brand = doc.createElementNS("http://www.w3.org/1999/xhtml", "span");
    brand.id = "ob-brand";
    brand.textContent = this.labels.mail;
    const placeholder = doc.querySelector("global-search-bar .kbd-container");
    if (placeholder) {
      placeholder.dataset.obPlaceholder = this.labels.searchMail;
      cleanups.push(() => delete placeholder.dataset.obPlaceholder);
    }
    doc.getElementById("unifiedToolbar").prepend(brand);
    cleanups.push(() => brand.remove());

    const decorated = new Map();
    const decoratePane = (pane) => {
      if (
        !pane ||
        pane.document.documentURI !== "about:3pane" ||
        decorated.has(pane)
      )
        return;
      const tree = pane.document.getElementById("threadTree");
      if (!tree) return;
      if (!pane.customElements.get("conversation-view")) {
        pane.ChromeUtils.importESModule(
          "chrome://messenger/content/conversation-view.mjs",
          { global: "current" },
        );
      }
      pane.document.documentElement.dataset.obRibbon = "true";
      const heading = pane.document.createElement("span");
      heading.id = "ob-folder-heading";
      heading.textContent = this.labels.folders;
      pane.document.getElementById("folderPaneHeaderBar").prepend(heading);
      const filterTabs = pane.document.createElement("div");
      filterTabs.id = "ob-filter-tabs";
      filterTabs.setAttribute("role", "group");
      filterTabs.setAttribute("aria-label", this.labels.readStatus);
      for (const [label, unread] of [
        [this.labels.all, false],
        [this.labels.unread, true],
      ]) {
        const button = pane.document.createElement("button");
        button.textContent = label;
        button.type = "button";
        button.dataset.obUnread = String(unread);
        button.addEventListener("click", () => {
          pane.quickFilterBar.setFilterValue("unread", unread || null);
          pane.quickFilterBar.updateFiltersSettings("unread", unread || null);
          pane.quickFilterBar.reflectFiltererState();
          pane.quickFilterBar.updateSearch();
        });
        filterTabs.append(button);
      }
      pane.document
        .getElementById("threadPaneHeaderBar")
        .querySelector(".list-header-bar-container-start")
        .append(filterTabs);
      const syncFilters = () => {
        const unread = !!pane.quickFilterBar.filterer?.filterValues.unread;
        for (const button of filterTabs.children)
          button.setAttribute(
            "aria-pressed",
            String((button.dataset.obUnread === "true") === unread),
          );
      };
      const filterObserver = new pane.MutationObserver(syncFilters);
      filterObserver.observe(pane.document.getElementById("qfb-unread"), {
        attributes: true,
        attributeFilter: ["aria-pressed"],
      });
      syncFilters();
      let frame = 0;
      const paint = () => {
        frame = 0;
        updateControls();
        for (const row of tree.querySelectorAll(
          ".card-layout:not([data-properties~='dummy'])",
        )) {
          const container = row.querySelector(".card-container");
          const senderNode = row.querySelector(".sender");
          const sender = (
            senderNode?.title ||
            senderNode?.textContent ||
            ""
          ).trim();
          if (!container || !sender) continue;
          const name = sender
            .replace(/<[^>]*>/g, "")
            .replace(/^["']|["']$/g, "")
            .trim()
            .split("@")[0];
          // Present the display name, retaining the full address in the native tooltip.
          const label = sender.replace(/\s*<[^>]*>/g, "").trim();
          if (label && senderNode.textContent !== label)
            senderNode.textContent = label;
          const index = row.index;
          const header = Number.isInteger(index)
            ? pane.gDBView?.getMsgHdrAt(index)
            : null;
          const preview = header?.getStringProperty("preview")?.trim() || "";
          const dynamic = row.querySelector(".thread-card-dynamic-row");
          let snippet = dynamic.querySelector(".ob-preview");
          if (preview) {
            if (!snippet) {
              snippet = pane.document.createElement("span");
              snippet.classList.add("ob-preview");
              dynamic.append(snippet);
            }
            if (snippet.textContent !== preview) snippet.textContent = preview;
          } else {
            snippet?.remove();
          }
          const words = name.match(/[\p{L}\p{N}]+/gu) || ["?"];
          const initials = (
            words.length > 1
              ? words[0][0] + words.at(-1)[0]
              : words[0].slice(0, 1)
          ).toUpperCase();
          let hash = 0;
          for (const char of sender)
            hash = (hash * 31 + char.codePointAt(0)) | 0;
          const palette = [
            "#b4dfb4",
            "#afe4ec",
            "#f8dfa6",
            "#d7c8ed",
            "#f2c6c6",
          ];
          container.dataset.obInitials = initials;
          paintPhoto(container, sender);
          container.style.setProperty(
            "--ob-avatar-bg",
            palette[(hash >>> 0) % palette.length],
          );
        }
      };
      const schedule = () => {
        if (!frame) frame = pane.requestAnimationFrame(paint);
      };
      const Conversation = pane.customElements.get("conversation-view");
      const originalShow = Conversation.prototype.show;
      Conversation.prototype.show = function (header) {
        // A selected thread is already available in the folder DB. Avoid requiring
        // the global search index just to open the messages the user selected.
        const thread = pane.gDBView?.getThreadContainingMsgHdr(header);
        if (!thread) return originalShow.call(this, header);
        const headers = Array.from({ length: thread.numChildren }, (_, i) =>
          thread.getChildHdrAt(i),
        );
        headers.sort((a, b) => a.date - b.date);
        this.onQueryCompleted({
          items: [
            {
              conversation: {
                getMessagesCollection(listener) {
                  listener.onQueryCompleted({
                    items: headers.map((folderMessage) => ({ folderMessage })),
                  });
                },
              },
            },
          ],
        });
        this.hidden = false;
      };
      const styled = new Map();
      const styleConversation = () => {
        const view = pane.document.querySelector("conversation-view");
        const root = view?.shadowRoot;
        if (!root || styled.has(root)) return;
        const style = pane.document.createElement("style");
        style.textContent = OB_CONVERSATION_STYLE;
        root.append(style);
        const layouts = new Map();
        let indexedMessages = null;
        let headerIndex = new Map();
        const findHeader = (id) => {
          if (indexedMessages !== view.messages) {
            indexedMessages = view.messages;
            headerIndex = new Map(
              (view.messages || []).map((header) => [header.messageId, header]),
            );
          }
          return headerIndex.get(id);
        };
        const collapse = (article) => {
          const header = findHeader(article.dataset.messageId);
          if (!header) return;
          const closed = pane.document
            .getElementById("conversationViewMessageTemplate")
            .content.cloneNode(true).firstElementChild;
          closed.dataset.messageId = header.messageId;
          closed.querySelector("address").textContent =
            header.mime2DecodedAuthor;
          closed.querySelector("time").textContent = new Intl.DateTimeFormat(
            Services.locale.appLocalesAsBCP47,
            { dateStyle: "medium", timeStyle: "short" },
          ).format(new Date(header.date / 1000));
          closed.querySelector("p").textContent =
            header.getStringProperty("preview");
          article.replaceWith(closed);
          closed.tabIndex = 0;
          closed.focus({ preventScroll: true });
        };
        const expand = (article) => {
          const header = findHeader(article.dataset.messageId);
          if (!header) return;
          const opened = pane.document.createElement("article");
          opened.setAttribute("role", "listitem");
          opened.setAttribute("aria-expanded", "true");
          opened.dataset.messageId = header.messageId;
          const browser = pane.document.createXULElement("browser");
          browser.setAttribute("src", "about:message");
          browser.hidden = true;
          for (const other of root.querySelectorAll("browser"))
            delete other.dataset.obActive;
          browser.dataset.obActive = "true";
          const loadMessage = (event) => {
            if (
              event.target?.documentURI !== "about:message" ||
              typeof browser.contentWindow.displayMessage !== "function"
            )
              return;
            browser.removeEventListener("load", loadMessage, true);
            browser.contentWindow.displayMessage(
              header.folder.getUriForMsg(header),
              pane.gViewWrapper,
            );
            browser.hidden = false;
          };
          browser.addEventListener("load", loadMessage, true);
          opened.append(browser);
          article.replaceWith(opened);
          browser.docShell.allowDNSPrefetch = false;
          opened.tabIndex = -1;
          opened.focus({ preventScroll: true });
        };
        const onExpand = (event) => {
          const article = event.target.closest?.(
            "article[aria-expanded='false']",
          );
          if (!article) return;
          event.stopImmediatePropagation();
          expand(article);
        };
        root.addEventListener("click", onExpand, true);
        const paintArticles = () => {
          updateControls();
          for (const article of root.querySelectorAll(
            "article[aria-expanded='false']",
          )) {
            const author = article.querySelector("address")?.textContent || "";
            const parts = author.match(/[\p{L}\p{N}]+/gu) || ["?"];
            article.dataset.obInitials = parts[0][0].toUpperCase();
            paintPhoto(article, author);
            const header = findHeader(article.dataset.messageId);
            const preview = header?.getStringProperty("preview");
            const snippet = article.querySelector("p");
            if (preview && snippet && snippet.textContent !== preview)
              snippet.textContent = preview;
            if (!article.hasAttribute("tabindex")) {
              article.tabIndex = 0;
              const onKey = (event) => {
                if (
                  !event.repeat &&
                  (event.key === "Enter" || event.key === " ")
                ) {
                  event.preventDefault();
                  article.click();
                  const expanded = [...root.querySelectorAll("article")].find(
                    (node) =>
                      node.dataset.messageId === article.dataset.messageId,
                  );
                  if (!expanded) return;
                  expanded.tabIndex = -1;
                  expanded.focus({ preventScroll: true });
                }
              };
              article.addEventListener("keydown", onKey);
            }
          }
          for (const [browser, layout] of layouts) {
            if (
              Components.utils.isDeadWrapper(browser) ||
              !browser.isConnected
            ) {
              layout.destroy();
              layouts.delete(browser);
            }
          }
          for (const browser of root.querySelectorAll("browser")) {
            if (!layouts.has(browser)) {
              const layout = new MessageLayout(
                browser,
                pane,
                view,
                this.labels,
                updateControls,
                collapse,
                decoratePhotos,
              );
              layouts.set(browser, layout);
              layout.render();
            }
          }
        };
        let paintFrame = 0;
        const changes = new pane.MutationObserver(() => {
          if (!paintFrame)
            paintFrame = pane.requestAnimationFrame(() => {
              paintFrame = 0;
              paintArticles();
            });
        });
        changes.observe(root.querySelector("#mainConversation"), {
          childList: true,
          subtree: true,
        });
        paintArticles();
        styled.set(root, () => {
          changes.disconnect();
          if (paintFrame) pane.cancelAnimationFrame(paintFrame);
          root.removeEventListener("click", onExpand, true);
          for (const layout of layouts.values()) layout.destroy();
          style.remove();
        });
      };
      const paneChanges = new pane.MutationObserver(styleConversation);
      paneChanges.observe(pane.document.getElementById("messagePane"), {
        childList: true,
      });
      styleConversation();
      const observer = new pane.MutationObserver(schedule);
      observer.observe(tree, {
        childList: true,
        characterData: true,
        subtree: true,
      });
      paint();
      const cleanup = () => {
        observer.disconnect();
        paneChanges.disconnect();
        for (const cleanup of styled.values()) cleanupUI(cleanup);
        Conversation.prototype.show = originalShow;
        tree.querySelectorAll(".ob-preview").forEach((node) => node.remove());
        tree.querySelectorAll(".sender[title]").forEach((node) => {
          node.textContent = node.title;
        });
        heading.remove();
        filterObserver.disconnect();
        filterTabs.remove();
        delete pane.document.documentElement.dataset.obRibbon;
        if (frame) pane.cancelAnimationFrame(frame);
        tree.querySelectorAll("[data-ob-initials]").forEach((node) => {
          delete node.dataset.obInitials;
          node.style.removeProperty("--ob-avatar-bg");
          node.style.removeProperty("--ob-avatar-photo");
          node.removeAttribute("data-ob-photo");
        });
        decorated.delete(pane);
      };
      decorated.set(pane, cleanup);
      pane.addEventListener("unload", cleanup, { once: true });
    };
    const photoDocs = new Map();
    const singleLayouts = new Map();
    const decoratePhotos = (messageDoc) => {
      if (
        messageDoc?.documentURI !== "about:message" ||
        photoDocs.has(messageDoc)
      )
        return;
      photoDocs.set(messageDoc, watchSenderPhoto(messageDoc, win));
      messageDoc.defaultView.addEventListener(
        "unload",
        () => {
          const cleanup = photoDocs.get(messageDoc);
          photoDocs.delete(messageDoc);
          if (cleanup) cleanupUI(cleanup);
        },
        { once: true },
      );
    };
    const decorateSingle = (messageDoc) => {
      if (messageDoc?.documentURI !== "about:message") return;
      const browser = messageDoc.defaultView.browsingContext?.embedderElement;
      if (
        !browser ||
        browser.getRootNode().host?.localName === "conversation-view"
      )
        return;
      if (!singleLayouts.has(browser)) {
        const layout = new MessageLayout(
          browser,
          win,
          null,
          this.labels,
          updateControls,
          null,
          decoratePhotos,
        );
        singleLayouts.set(browser, layout);
        messageDoc.defaultView.addEventListener(
          "unload",
          () => {
            cleanupUI(() => layout.destroy());
            singleLayouts.delete(browser);
          },
          { once: true },
        );
      }
      singleLayouts.get(browser).render();
    };
    const onLoad = (event) => {
      decoratePhotos(event.target);
      decorateSingle(event.target);
      if (event.target?.documentURI === "about:3pane")
        decoratePane(event.target.defaultView);
    };
    doc.addEventListener("load", onLoad, true);
    cleanups.push(() => {
      doc.removeEventListener("load", onLoad, true);
      for (const cleanup of photoDocs.values()) cleanupUI(cleanup);
      for (const layout of singleLayouts.values())
        cleanupUI(() => layout.destroy());
      for (const cleanup of [...decorated.values()]) cleanupUI(cleanup);
    });
    const tabs = doc.getElementById("tabmail");
    for (const tab of tabs.tabInfo)
      decoratePane(tab.chromeBrowser?.contentWindow);
    decoratePane(tabs.currentAbout3Pane);
    const scanPhotos = (document) => {
      decoratePhotos(document);
      decorateSingle(document);
      for (const browser of document.querySelectorAll("browser")) {
        try {
          if (browser.contentDocument) scanPhotos(browser.contentDocument);
        } catch {}
      }
    };
    scanPhotos(doc);
  }

  /** Applies the same native reader layout in a separate message window. */
  attachReadingWindow(win) {
    if (this.windows.has(win)) return;
    const browser = win.document.getElementById("messageBrowser");
    const photos = new Map();
    const decoratePhotos = (doc) => {
      if (!photos.has(doc)) photos.set(doc, watchSenderPhoto(doc, win));
    };
    const layout = new MessageLayout(
      browser,
      win,
      null,
      this.labels,
      () => {},
      null,
      decoratePhotos,
    );
    this.windows.set(win, [
      () => layout.destroy(),
      () => {
        for (const cleanup of photos.values()) cleanupUI(cleanup);
      },
    ]);
    layout.render();
  }

  detach(win) {
    for (const cleanup of this.windows.get(win) || []) cleanupUI(cleanup);
    this.windows.delete(win);
  }

  onShutdown() {
    if (this.originalConversationPref !== null)
      Services.prefs.setBoolPref(
        "mail.thread.conversation.enabled",
        this.originalConversationPref,
      );
    if (this.registered)
      ExtensionSupport.unregisterWindowListener(this.extension.id);
    for (const win of [...this.windows.keys()]) this.detach(win);
  }
};
