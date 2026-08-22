/*
 * Highlights and notes for the HA Docs add-on.
 *
 * Select text to highlight it, optionally attach a note, and review everything
 * you have flagged from the button in the header. Annotations are stored by
 * annotations.py in /data, not in the browser, so the same set shows up in the
 * companion app and on the desktop.
 *
 * Written by hand rather than pulled from a library for the same reason
 * Mermaid is vendored into the image: this box has no outbound access, so a
 * dependency would have to be vendored too, and the part of annotator.js this
 * actually needs is the part below.
 *
 * ---------------------------------------------------------------------------
 * Anchoring
 *
 * The site is rebuilt from scratch on every commit to the docs repo, so a DOM
 * path or a character offset stored today is meaningless after the next edit.
 * Annotations are anchored the way the W3C annotation model does it: by the
 * quoted text plus a little context either side (a TextQuoteSelector). On load
 * the article's text is flattened, whitespace-normalised - so re-wrapping a
 * paragraph in the Markdown does not break anything - and searched.
 *
 * When the quote can no longer be found the annotation is reported as orphaned
 * in the review drawer, with its text, and is NOT drawn on the page. Guessing
 * would be worse than admitting it: a highlight silently attached to the wrong
 * sentence is a lie about what you flagged.
 * ---------------------------------------------------------------------------
 */
(function () {
  "use strict";

  var SCRIPT = document.currentScript;

  var COLORS = ["yellow", "green", "blue", "pink"];
  var DEFAULT_COLOR = "yellow";

  // Characters of context stored either side of the quote. Long enough to make
  // a repeated phrase ("Notes", "See below") unambiguous, short enough that an
  // edit to the neighbouring sentence usually leaves one side intact.
  var CONTEXT = 40;

  // Text inside these never gets annotated. `.diagram` matters most: Mermaid
  // replaces that subtree with an SVG on every render and on every palette
  // toggle, so nothing anchored there would survive.
  var SKIP_TAGS = { SCRIPT: 1, STYLE: 1, NOSCRIPT: 1, BUTTON: 1, SVG: 1, TEXTAREA: 1 };
  var SKIP_CLASSES = ["diagram", "headerlink", "anno-ui", "md-search"];

  // ---------------------------------------------------------------------------
  // Where we are
  //
  // Ingress mounts the add-on under /api/hassio_ingress/<token>/ and that token
  // rotates, so location.pathname cannot be a storage key and an absolute
  // fetch("/anno/...") would leave the add-on entirely. Both are derived from
  // this script's own URL instead, which is the one thing on the page that is
  // always base-relative.
  // ---------------------------------------------------------------------------
  var BASE = (function () {
    var el = SCRIPT;
    if (!el) {
      var all = document.getElementsByTagName("script");
      for (var i = 0; i < all.length; i++) {
        if (/assets\/annotate\.js(\?|$)/.test(all[i].src)) {
          el = all[i];
          break;
        }
      }
    }
    if (!el) {
      return null;
    }
    return el.src.replace(/assets\/annotate\.js(\?.*)?$/, "");
  })();

  var PAGE = (function () {
    if (!BASE) {
      return null;
    }
    var basePath = new URL(BASE, location.href).pathname;
    var here = location.pathname;
    var key = here.indexOf(basePath) === 0 ? here.slice(basePath.length) : here;
    key = key.replace(/^\/+/, "");
    if (!key || key.charAt(key.length - 1) === "/") {
      key += "index.html";
    }
    return key;
  })();

  function api(route, body) {
    var options = { headers: { "Content-Type": "application/json" } };
    if (body) {
      options.method = "POST";
      options.body = JSON.stringify(body);
    }
    return fetch(BASE + "anno/" + route, options).then(function (response) {
      if (!response.ok) {
        throw new Error("anno/" + route + " -> " + response.status);
      }
      return response.json();
    });
  }

  // ---------------------------------------------------------------------------
  // Flattened, whitespace-normalised view of the article
  // ---------------------------------------------------------------------------

  function contentRoot() {
    return document.querySelector("article.md-content__inner") ||
      document.querySelector(".md-typeset");
  }

  function accept(node) {
    if (!node.nodeValue) {
      return NodeFilter.FILTER_REJECT;
    }
    var el = node.parentElement;
    while (el) {
      var tag = (el.tagName || "").toUpperCase();
      if (SKIP_TAGS[tag]) {
        return NodeFilter.FILTER_REJECT;
      }
      if (el.classList) {
        for (var i = 0; i < SKIP_CLASSES.length; i++) {
          if (el.classList.contains(SKIP_CLASSES[i])) {
            return NodeFilter.FILTER_REJECT;
          }
        }
      }
      if (el === document.body) {
        break;
      }
      el = el.parentElement;
    }
    return NodeFilter.FILTER_ACCEPT;
  }

  /*
   * Returns:
   *   nodes/starts - the text nodes in document order and each one's offset
   *                  into the raw concatenation
   *   norm         - the same text with every run of whitespace collapsed to a
   *                  single space; this is what quotes are stored and matched
   *                  against, so re-flowing a paragraph is invisible to us
   *   map          - norm index -> raw index
   *   inv          - raw index -> norm index
   *
   * Rebuilt after every paint: wrapping a quote splits text nodes, which
   * invalidates nodes/starts even though the text itself never changes.
   */
  function buildIndex() {
    var root = contentRoot();
    if (!root) {
      return null;
    }

    var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode: accept
    });

    var nodes = [];
    var starts = [];
    var raw = "";
    var node;
    while ((node = walker.nextNode())) {
      starts.push(raw.length);
      nodes.push(node);
      raw += node.nodeValue;
    }

    var norm = "";
    var map = [];
    var inv = new Array(raw.length + 1);
    var pendingSpaceAt = -1;

    for (var i = 0; i < raw.length; i++) {
      var ch = raw.charAt(i);
      if (ch === " " || ch === "\t" || ch === "\n" || ch === "\r" || ch === "\f") {
        if (pendingSpaceAt < 0) {
          pendingSpaceAt = i;
        }
        inv[i] = norm.length;
        continue;
      }
      if (pendingSpaceAt >= 0) {
        if (norm.length > 0) {
          // The collapsed space maps back to the first whitespace character of
          // the run, so a range that happens to end on one lands on real text.
          norm += " ";
          map.push(pendingSpaceAt);
        }
        pendingSpaceAt = -1;
      }
      inv[i] = norm.length;
      norm += ch;
      map.push(i);
    }
    inv[raw.length] = norm.length;

    return {
      root: root,
      nodes: nodes,
      starts: starts,
      raw: raw,
      norm: norm,
      map: map,
      inv: inv
    };
  }

  // Raw offsets covered by a live selection range, or null.
  function rawBounds(index, range) {
    var start = -1;
    var end = -1;
    for (var i = 0; i < index.nodes.length; i++) {
      var node = index.nodes[i];
      if (!range.intersectsNode(node)) {
        continue;
      }
      var length = node.nodeValue.length;
      var from = node === range.startContainer ? range.startOffset : 0;
      var to = node === range.endContainer ? range.endOffset : length;
      if (to <= from) {
        continue;
      }
      if (start < 0) {
        start = index.starts[i] + from;
      }
      end = index.starts[i] + to;
    }
    return start < 0 ? null : { start: start, end: end };
  }

  // Every occurrence is a candidate; the one nearest the position the
  // annotation was made at wins. That only matters for short quotes, which is
  // exactly when duplicates happen.
  function nearest(hay, needle, hint, delta) {
    if (!needle) {
      return -1;
    }
    var best = -1;
    var bestDistance = Infinity;
    var from = 0;
    var at;
    while ((at = hay.indexOf(needle, from)) !== -1) {
      var position = at + delta;
      var distance = typeof hint === "number" ? Math.abs(position - hint) : 0;
      if (distance < bestDistance) {
        bestDistance = distance;
        best = position;
      }
      from = at + 1;
    }
    return best;
  }

  // Progressively weaker anchors: both sides of context, then either side,
  // then the bare quote. Anything looser than this starts inventing matches.
  function locate(index, record) {
    var exact = record.exact || "";
    if (!exact) {
      return null;
    }
    var prefix = record.prefix || "";
    var suffix = record.suffix || "";
    var hay = index.norm;

    var start = nearest(hay, prefix + exact + suffix, record.hint, prefix.length);
    if (start < 0) {
      start = nearest(hay, prefix + exact, record.hint, prefix.length);
    }
    if (start < 0) {
      start = nearest(hay, exact + suffix, record.hint, 0);
    }
    if (start < 0) {
      start = nearest(hay, exact, record.hint, 0);
    }
    if (start < 0) {
      return null;
    }

    var end = start + exact.length;
    if (end > index.norm.length) {
      return null;
    }
    return { start: index.map[start], end: index.map[end - 1] + 1 };
  }

  // ---------------------------------------------------------------------------
  // Drawing
  // ---------------------------------------------------------------------------

  function paint(index, bounds, record) {
    var made = [];
    for (var i = 0; i < index.nodes.length; i++) {
      var node = index.nodes[i];
      var nodeStart = index.starts[i];
      var length = node.nodeValue.length;
      if (nodeStart + length <= bounds.start || nodeStart >= bounds.end) {
        continue;
      }

      var from = Math.max(0, bounds.start - nodeStart);
      var to = Math.min(length, bounds.end - nodeStart);
      if (to <= from) {
        continue;
      }

      // splitText only ever touches the node being wrapped, so iterating the
      // snapshot taken before the loop stays valid.
      var target = node;
      if (to < length) {
        target.splitText(to);
      }
      if (from > 0) {
        target = target.splitText(from);
      }

      var mark = document.createElement("mark");
      mark.className = "anno anno--" + (record.color || DEFAULT_COLOR);
      mark.setAttribute("data-anno-id", record.id);
      if (record.note) {
        mark.setAttribute("data-anno-note", "1");
      }
      target.parentNode.insertBefore(mark, target);
      mark.appendChild(target);
      made.push(mark);
    }
    return made;
  }

  function marksFor(id) {
    return Array.prototype.slice.call(
      document.querySelectorAll('mark.anno[data-anno-id="' + id + '"]')
    );
  }

  function unpaint(id) {
    marksFor(id).forEach(function (mark) {
      var parent = mark.parentNode;
      while (mark.firstChild) {
        parent.insertBefore(mark.firstChild, mark);
      }
      parent.removeChild(mark);
      // Re-joins the text nodes the split left behind, so repeated
      // highlight/delete cycles do not shred the DOM.
      parent.normalize();
    });
  }

  function restyle(record) {
    marksFor(record.id).forEach(function (mark) {
      mark.className = "anno anno--" + (record.color || DEFAULT_COLOR);
      if (record.note) {
        mark.setAttribute("data-anno-note", "1");
      } else {
        mark.removeAttribute("data-anno-note");
      }
    });
  }

  // ---------------------------------------------------------------------------
  // State
  // ---------------------------------------------------------------------------

  var all = [];        // every annotation, every page - drives the drawer
  var orphans = [];    // on this page, but the quoted text no longer exists

  function cloneRecord(record) {
    return JSON.parse(JSON.stringify(record));
  }

  function replaceRecord(record) {
    var i = all.findIndex(function (item) { return item.id === record.id; });
    if (i >= 0) {
      all[i] = record;
    } else {
      all.push(record);
    }
  }

  function repaintRecord(record) {
    unpaint(record.id);
    if (record.page !== PAGE) return;
    var index = buildIndex();
    var bounds = index && locate(index, record);
    if (bounds) paint(index, bounds, record);
  }

  function onThisPage() {
    return all.filter(function (record) {
      return record.page === PAGE;
    });
  }

  function pageTitle() {
    var heading = document.querySelector("article.md-content__inner h1");
    if (!heading) {
      return document.title.trim();
    }
    // `permalink: true` in mkdocs.yml appends a pilcrow anchor to every
    // heading, and textContent would drag it into the drawer and into every
    // to-do item.
    var copy = heading.cloneNode(true);
    Array.prototype.forEach.call(copy.querySelectorAll(".headerlink"), function (a) {
      a.remove();
    });
    return copy.textContent.trim();
  }

  function newId() {
    return (
      Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 8)
    );
  }

  function render() {
    orphans = [];
    var records = onThisPage();
    for (var i = 0; i < records.length; i++) {
      var index = buildIndex();
      if (!index) {
        return;
      }
      var bounds = locate(index, records[i]);
      if (!bounds) {
        orphans.push(records[i]);
        continue;
      }
      paint(index, bounds, records[i]);
    }
    updateBadge();
  }

  // ---------------------------------------------------------------------------
  // UI plumbing
  // ---------------------------------------------------------------------------

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) {
      node.className = className;
    }
    if (text != null) {
      node.textContent = text;
    }
    return node;
  }

  function icon(path) {
    return (
      '<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">' +
      '<path fill="currentColor" d="' + path + '"/></svg>'
    );
  }

  var ICON_BOOKMARK =
    "M17,18L12,15.82L7,18V5H17M17,3H7A2,2 0 0,0 5,5V21L12,18L19,21V5C19,3.89 18.1,3 17,3Z";
  var ICON_CLOSE =
    "M19,6.41L17.59,5L12,10.59L6.41,5L5,6.41L10.59,12L5,17.59L6.41,19L12,13.41L17.59,19L19,17.59L13.41,12L19,6.41Z";
  var ICON_NOTE =
    "M14,10H19.5L14,4.5V10M5,3H15L21,9V19A2,2 0 0,1 19,21H5A2,2 0 0,1 3,19V5A2,2 0 0,1 5,3M5,12V14H19V12H5M5,16V18H14V16H5Z";
  var ICON_TRASH =
    "M19,4H15.5L14.5,3H9.5L8.5,4H5V6H19M6,19A2,2 0 0,0 8,21H16A2,2 0 0,0 18,19V7H6V19Z";

  // Falls back rather than trusting innerWidth outright: this runs inside the
  // ingress iframe, and a viewport that reports 0 would clamp every popup to a
  // negative offset and put it off-screen.
  function viewport() {
    var width = window.innerWidth || document.documentElement.clientWidth || 0;
    var height = window.innerHeight || document.documentElement.clientHeight || 0;
    return {
      width: width > 0 ? width : 1024,
      height: height > 0 ? height : 768
    };
  }

  function swatches(current, onPick) {
    var row = el("div", "anno-swatches");
    COLORS.forEach(function (color) {
      var button = el("button", "anno-swatch anno-swatch--" + color);
      button.type = "button";
      button.title = color;
      button.setAttribute("aria-label", "Highlight " + color);
      if (color === current) {
        button.classList.add("anno-swatch--on");
      }
      button.addEventListener("click", function (event) {
        event.preventDefault();
        event.stopPropagation();
        onPick(color);
      });
      row.appendChild(button);
    });
    return row;
  }

  // --- selection toolbar -----------------------------------------------------

  var toolbar = null;
  var pending = null; // the anchor captured from the current selection

  function hideToolbar() {
    if (toolbar) {
      toolbar.remove();
      toolbar = null;
    }
    pending = null;
  }

  function captureSelection() {
    var selection = window.getSelection();
    if (!selection || selection.isCollapsed || selection.rangeCount === 0) {
      return null;
    }
    var range = selection.getRangeAt(0);
    var index = buildIndex();
    if (!index || !index.root.contains(range.commonAncestorContainer)) {
      return null;
    }

    var bounds = rawBounds(index, range);
    if (!bounds) {
      return null;
    }

    var start = index.inv[bounds.start];
    var end = index.inv[bounds.end];
    // Trim, so a selection that runs to the end of a line does not store a
    // trailing space that the next build might not produce.
    while (start < end && index.norm.charAt(start) === " ") {
      start++;
    }
    while (end > start && index.norm.charAt(end - 1) === " ") {
      end--;
    }
    if (end <= start) {
      return null;
    }

    return {
      page: PAGE,
      title: pageTitle(),
      exact: index.norm.slice(start, end),
      prefix: index.norm.slice(Math.max(0, start - CONTEXT), start),
      suffix: index.norm.slice(end, end + CONTEXT),
      hint: start
    };
  }

  function showToolbar() {
    var anchor = captureSelection();
    if (!anchor) {
      hideToolbar();
      return;
    }

    var rect = window.getSelection().getRangeAt(0).getBoundingClientRect();
    if (!rect || (!rect.width && !rect.height)) {
      hideToolbar();
      return;
    }

    if (!toolbar) {
      toolbar = el("div", "anno-ui anno-toolbar");
      toolbar.appendChild(
        swatches(null, function (color) {
          create(pending, color, false);
        })
      );
      var note = el("button", "anno-toolbar__note");
      note.type = "button";
      note.innerHTML = icon(ICON_NOTE) + "<span>Note</span>";
      note.addEventListener("click", function (event) {
        event.preventDefault();
        create(pending, DEFAULT_COLOR, true);
      });
      toolbar.appendChild(note);
      document.body.appendChild(toolbar);
    }

    pending = anchor;

    var view = viewport();
    var width = toolbar.offsetWidth;
    var height = toolbar.offsetHeight;
    var left = Math.max(
      8,
      Math.min(rect.left + rect.width / 2 - width / 2, view.width - width - 8)
    );
    var above = rect.top - height - 8;
    toolbar.style.left = left + "px";
    toolbar.style.top = (above > 8 ? above : rect.bottom + 8) + "px";
  }

  function create(anchor, color, openNote) {
    if (!anchor) {
      return;
    }
    var record = {
      id: newId(),
      page: anchor.page,
      title: anchor.title,
      exact: anchor.exact,
      prefix: anchor.prefix,
      suffix: anchor.suffix,
      hint: anchor.hint,
      color: color,
      note: ""
    };

    var selection = window.getSelection();
    if (selection) {
      selection.removeAllRanges();
    }
    hideToolbar();

    var index = buildIndex();
    var bounds = index && locate(index, record);
    if (bounds) {
      paint(index, bounds, record);
    }
    all.push(record);
    updateBadge();

    save(record).then(function (ok) {
      if (!ok) return;
      if (openNote) {
        var mark = marksFor(record.id)[0];
        if (mark) {
          openPopover(record, mark);
        }
      }
    });
  }

  function save(record) {
    return api("save", record)
      .then(function (result) {
        if (result && result.annotation) {
          // Keep the server's view (created, todo_pushed) rather than ours.
          replaceRecord(result.annotation);
        }
        return true;
      })
      .catch(function (err) {
        console.error("[ha_docs] could not save annotation", err);
        flash("Could not save - is the add-on still running?");
        return false;
      });
  }

  // --- note popover ----------------------------------------------------------

  var popover = null;

  function closePopover() {
    if (popover) {
      popover.remove();
      popover = null;
    }
  }

  function openPopover(record, anchorEl) {
    closePopover();
    hideToolbar();

    popover = el("div", "anno-ui anno-popover");

    var head = el("div", "anno-popover__head");
    head.appendChild(el("div", "anno-popover__quote", record.exact));
    popover.appendChild(head);

    var textarea = document.createElement("textarea");
    textarea.className = "anno-popover__note";
    textarea.rows = 4;
    textarea.placeholder = "Note (added to the review list)";
    textarea.value = record.note || "";
    popover.appendChild(textarea);

    var current = record.color;
    var row = el("div", "anno-popover__row");
    var picker = swatches(current, function (color) {
      current = color;
      Array.prototype.forEach.call(
        picker.querySelectorAll(".anno-swatch"),
        function (button, i) {
          button.classList.toggle("anno-swatch--on", COLORS[i] === color);
        }
      );
    });
    row.appendChild(picker);

    var remove = el("button", "anno-btn anno-btn--danger", "Delete");
    remove.type = "button";
    remove.addEventListener("click", function () {
      destroy(record);
      closePopover();
    });
    row.appendChild(remove);

    var done = el("button", "anno-btn anno-btn--primary", "Save");
    done.type = "button";
    done.addEventListener("click", function () {
      var before = cloneRecord(record);
      var had = !!record.note;
      record.note = textarea.value.trim();
      record.color = current;
      restyle(record);
      done.disabled = true;
      save(record).then(function (ok) {
        if (!ok) {
          Object.keys(record).forEach(function (key) { delete record[key]; });
          Object.assign(record, before);
          replaceRecord(record);
          repaintRecord(record);
          renderDrawer();
          done.disabled = false;
          return;
        }
        if (!had && record.note) flash("Added to the review list");
        closePopover();
      });
    });
    row.appendChild(done);

    popover.appendChild(row);
    document.body.appendChild(popover);

    var view = viewport();
    var rect = anchorEl.getBoundingClientRect();
    var width = popover.offsetWidth;
    var left = Math.max(8, Math.min(rect.left, view.width - width - 8));
    var below = rect.bottom + 8;
    var fits = below + popover.offsetHeight < view.height - 8;
    popover.style.left = left + "px";
    popover.style.top =
      (fits ? below : Math.max(8, rect.top - popover.offsetHeight - 8)) + "px";

    textarea.focus();
  }

  function destroy(record) {
    var snapshot = cloneRecord(record);
    unpaint(record.id);
    all = all.filter(function (r) {
      return r.id !== record.id;
    });
    orphans = orphans.filter(function (r) {
      return r.id !== record.id;
    });
    updateBadge();
    renderDrawer();
    api("delete", { id: record.id })
      .then(function () {
        // The add-on completes the to-do item on a thread it does not wait for,
        // so this reports what was asked for rather than what came back. A
        // completion that fails lands in the add-on log, not here.
        flash(
          record.todo_pushed
            ? "Note deleted · to-do ticked off"
            : "Note deleted"
        );
      })
      .catch(function (err) {
        console.error("[ha_docs] could not delete annotation", err);
        replaceRecord(snapshot);
        repaintRecord(snapshot);
        updateBadge();
        renderDrawer();
        flash("Could not delete - is the add-on still running?");
      });
  }

  // --- review drawer ---------------------------------------------------------

  var drawer = null;
  var badge = null;

  function updateBadge() {
    if (badge) {
      badge.textContent = all.length ? String(all.length) : "";
      badge.style.display = all.length ? "" : "none";
    }
  }

  function addHeaderButton() {
    var header = document.querySelector(".md-header__inner");
    if (!header) {
      return;
    }
    var button = el("button", "md-header__button md-icon anno-open");
    button.type = "button";
    button.title = "Highlights and notes";
    button.setAttribute("aria-label", "Highlights and notes");
    button.innerHTML = icon(ICON_BOOKMARK);
    badge = el("span", "anno-open__badge");
    badge.style.display = "none";
    button.appendChild(badge);
    button.addEventListener("click", toggleDrawer);
    header.appendChild(button);
    updateBadge();
  }

  function toggleDrawer() {
    if (drawer) {
      disarm();
      drawer.remove();
      drawer = null;
      return;
    }
    drawer = el("div", "anno-ui anno-drawer");

    var head = el("div", "anno-drawer__head");
    head.appendChild(el("h2", null, "Highlights & notes"));
    var close = el("button", "anno-drawer__close");
    close.type = "button";
    close.setAttribute("aria-label", "Close");
    close.innerHTML = icon(ICON_CLOSE);
    close.addEventListener("click", toggleDrawer);
    head.appendChild(close);
    drawer.appendChild(head);

    drawer.appendChild(el("div", "anno-drawer__body"));
    document.body.appendChild(drawer);

    // Re-fetch on open: the other device may have added something since this
    // page was loaded.
    api("all")
      .then(function (result) {
        all = result.annotations || [];
        updateBadge();
        renderDrawer();
      })
      .catch(function () {
        renderDrawer();
      });

    renderDrawer();
  }

  // ---------------------------------------------------------------------------
  // Deleting from the drawer
  //
  // This is the only route to an orphan: it is not painted anywhere, so there is
  // no highlight to click and open the popover on. Same for anything on a page
  // you are not currently reading.
  //
  // Two taps, because the drawer is scrolled with a thumb and there is no undo.
  // Only ever one armed button - arming a second disarms the first, so a stray
  // tap further down the list cannot become the confirming tap for a row you
  // stopped looking at.
  // ---------------------------------------------------------------------------

  var DELETE_LABEL = "Delete note";
  var CONFIRM_LABEL = "Tap again to delete";

  var armed = null;
  var armedTimer = null;

  function disarm() {
    if (armedTimer) {
      clearTimeout(armedTimer);
      armedTimer = null;
    }
    if (armed) {
      armed.classList.remove("anno-item__delete--armed");
      armed.innerHTML = icon(ICON_TRASH);
      armed.title = DELETE_LABEL;
      armed.setAttribute("aria-label", DELETE_LABEL);
      armed = null;
    }
  }

  function deleteButton(record) {
    var button = el("button", "anno-item__delete");
    button.type = "button";
    button.title = DELETE_LABEL;
    button.setAttribute("aria-label", DELETE_LABEL);
    button.innerHTML = icon(ICON_TRASH);

    button.addEventListener("click", function (event) {
      // The button's sibling is a link and a delegated handler on document
      // watches for clicks on highlights; neither should see this.
      event.preventDefault();
      event.stopPropagation();

      if (armed === button) {
        disarm();
        destroy(record);
        return;
      }

      disarm();
      armed = button;
      button.classList.add("anno-item__delete--armed");
      button.textContent = "Delete?";
      button.title = CONFIRM_LABEL;
      button.setAttribute("aria-label", CONFIRM_LABEL);
      armedTimer = setTimeout(disarm, 3000);
    });

    return button;
  }

  function renderDrawer() {
    if (!drawer) {
      return;
    }
    // Every row is about to be rebuilt, so an armed button is a stale node and
    // its timer would fire against nothing.
    disarm();
    var body = drawer.querySelector(".anno-drawer__body");
    body.textContent = "";

    if (!all.length) {
      body.appendChild(
        el(
          "p",
          "anno-drawer__empty",
          "Nothing flagged yet. Select any text in a doc to highlight it."
        )
      );
      return;
    }

    var orphaned = {};
    orphans.forEach(function (record) {
      orphaned[record.id] = true;
    });

    var groups = {};
    var order = [];
    all.forEach(function (record) {
      if (!groups[record.page]) {
        groups[record.page] = [];
        order.push(record.page);
      }
      groups[record.page].push(record);
    });

    // Whatever you are reading first, then the rest as they were created.
    order.sort(function (a, b) {
      if (a === PAGE) return -1;
      if (b === PAGE) return 1;
      return 0;
    });

    order.forEach(function (page) {
      var records = groups[page];
      var section = el("section", "anno-group");
      section.appendChild(
        el("h3", null, records[0].title || page.replace(/\.html$/, ""))
      );

      records
        .sort(function (a, b) {
          return (a.hint || 0) - (b.hint || 0);
        })
        .forEach(function (record) {
          // The delete button cannot live inside the anchor - a button nested in
          // a link is invalid, and the nesting swallows the click - so the row is
          // a wrapper holding the two side by side.
          var row = el("div", "anno-row");

          var item = el("a", "anno-item anno-item--" + record.color);
          item.href = BASE + page + "#anno-" + record.id;
          if (orphaned[record.id]) {
            item.classList.add("anno-item--orphan");
          }
          item.appendChild(el("div", "anno-item__quote", record.exact));
          if (record.note) {
            item.appendChild(el("div", "anno-item__note", record.note));
          }
          if (orphaned[record.id]) {
            item.appendChild(
              el(
                "div",
                "anno-item__flag",
                "The text this was on has changed - it is no longer shown on the page."
              )
            );
          }
          // Same page: no navigation, just scroll to it.
          if (page === PAGE && !orphaned[record.id]) {
            item.addEventListener("click", function (event) {
              event.preventDefault();
              jumpTo(record.id);
            });
          }

          row.appendChild(item);
          row.appendChild(deleteButton(record));
          section.appendChild(row);
        });

      body.appendChild(section);
    });
  }

  function jumpTo(id) {
    var mark = marksFor(id)[0];
    if (!mark) {
      return;
    }
    mark.scrollIntoView({ block: "center", behavior: "smooth" });
    marksFor(id).forEach(function (node) {
      node.classList.add("anno--flash");
      setTimeout(function () {
        node.classList.remove("anno--flash");
      }, 1600);
    });
  }

  // --- transient message -----------------------------------------------------

  var toast = null;

  function flash(message) {
    if (toast) {
      toast.remove();
    }
    toast = el("div", "anno-ui anno-toast", message);
    document.body.appendChild(toast);
    setTimeout(function () {
      if (toast) {
        toast.remove();
        toast = null;
      }
    }, 3000);
  }

  // ---------------------------------------------------------------------------
  // Wiring
  // ---------------------------------------------------------------------------

  function start() {
    if (!BASE || !PAGE || !contentRoot()) {
      return;
    }

    addHeaderButton();

    api("all")
      .then(function (result) {
        all = result.annotations || [];
        render();
        var hash = location.hash;
        if (hash.indexOf("#anno-") === 0) {
          jumpTo(hash.slice(6));
        }
      })
      .catch(function (err) {
        console.error("[ha_docs] annotation service unreachable", err);
      });

    var timer = null;
    function schedule(delay) {
      clearTimeout(timer);
      timer = setTimeout(showToolbar, delay);
    }

    // mouseup/touchend catch the common case immediately; selectionchange is
    // the fallback for keyboard selection and for dragging the iOS handles,
    // debounced so the toolbar does not chase the selection while it grows.
    document.addEventListener("mouseup", function () {
      schedule(10);
    });
    document.addEventListener("touchend", function () {
      schedule(10);
    });
    document.addEventListener("selectionchange", function () {
      schedule(400);
    });

    document.addEventListener("click", function (event) {
      var mark = event.target.closest && event.target.closest("mark.anno");
      if (mark) {
        var id = mark.getAttribute("data-anno-id");
        var record = all.filter(function (r) {
          return r.id === id;
        })[0];
        if (record) {
          event.preventDefault();
          openPopover(record, mark);
        }
        return;
      }
      if (event.target.closest && event.target.closest(".anno-ui, .anno-open")) {
        return;
      }
      closePopover();
    });

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        closePopover();
        hideToolbar();
        if (drawer) {
          toggleDrawer();
        }
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
