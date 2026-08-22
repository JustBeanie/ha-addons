/*
 * Live status for the two HA Docs link checkers.
 *
 * The add-on runs a documentation-source anchor check on every refresh pass and
 * a report-only Docs-link Repair scan over every automation and script. Both
 * used to report only into the add-on log, which is the one place you are not
 * looking while reading the docs. This surfaces both, and in particular
 * surfaces the case that is otherwise invisible: a broken source anchor stops
 * the rebuild, so the site silently keeps serving the previous commit.
 *
 * Read-only. Nothing here starts a scan or writes to Home Assistant; the whole
 * client is one GET against /anno/scan.
 *
 * ---------------------------------------------------------------------------
 * Why this is a separate file from annotate.js
 *
 * The two share nothing but about thirty lines of plumbing, and annotate.js is
 * already twelve hundred lines of anchoring logic that has no business being
 * reopened to add a status panel. The one place they touch is the drawer mount
 * point described under "narrow layout" below.
 * ---------------------------------------------------------------------------
 */
(function () {
  "use strict";

  var SCRIPT = document.currentScript;

  // Ingress mounts the add-on under /api/hassio_ingress/<token>/ and the token
  // rotates, so an absolute fetch("/anno/...") would leave the add-on entirely.
  // Derived from this script's own URL, the one base-relative thing on the page.
  var BASE = (function () {
    var el = SCRIPT;
    if (!el) {
      var all = document.getElementsByTagName("script");
      for (var i = 0; i < all.length; i++) {
        if (/assets\/checker\.js(\?|$)/.test(all[i].src)) {
          el = all[i];
          break;
        }
      }
    }
    return el ? el.src.replace(/assets\/checker\.js(\?.*)?$/, "") : null;
  })();

  // Below this the header button is hidden by CSS and the panel moves into the
  // highlights drawer instead. One value, shared with checker.css - a phone
  // header already carries a hamburger, a title, search, Sync and Highlights.
  var NARROW = "(max-width: 44.9375em)";

  var POLL_FAST = 3000;
  var POLL_SLOW = 30000;

  // A rebuild swaps the site directory underneath nginx, so a request landing
  // in that window fails once. Only give up on the state after a few in a row.
  var FAIL_LIMIT = 3;

  var state = null;
  var failures = 0;
  var timer = null;

  var button = null;
  var badge = null;
  var drawer = null;
  var narrowDot = null;
  var narrow = null;

  function api(route) {
    return fetch(BASE + "anno/" + route, {
      headers: { "Content-Type": "application/json" }
    }).then(function (response) {
      if (!response.ok) {
        throw new Error("anno/" + route + " -> " + response.status);
      }
      return response.json();
    });
  }

  // ---------------------------------------------------------------------------
  // Small DOM helpers. Deliberately duplicated rather than shared with
  // annotate.js: a shared runtime would be a third file to load in order.
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

  var ICON_LINK =
    "M10.59,13.41C11,13.8 11,14.44 10.59,14.83C10.2,15.22 9.56,15.22 9.17,14.83C7.22,12.88 7.22,9.71 9.17,7.76V7.76L12.71,4.22C14.66,2.27 17.83,2.27 19.78,4.22C21.73,6.17 21.73,9.34 19.78,11.29L18.29,12.78C18.3,11.96 18.17,11.14 17.89,10.36L18.36,9.88C19.54,8.71 19.54,6.81 18.36,5.64C17.19,4.46 15.29,4.46 14.12,5.64L10.59,9.17C9.41,10.34 9.41,12.24 10.59,13.41M13.41,9.17C13.8,8.78 14.44,8.78 14.83,9.17C16.78,11.12 16.78,14.29 14.83,16.24V16.24L11.29,19.78C9.34,21.73 6.17,21.73 4.22,19.78C2.27,17.83 2.27,14.66 4.22,12.71L5.71,11.22C5.7,12.04 5.83,12.86 6.11,13.65L5.64,14.12C4.46,15.29 4.46,17.19 5.64,18.36C6.81,19.54 8.71,19.54 9.88,18.36L13.41,14.83C14.59,13.66 14.59,11.76 13.41,10.59C13,10.2 13,9.56 13.41,9.17Z";
  var ICON_CLOSE =
    "M19,6.41L17.59,5L12,10.59L6.41,5L5,6.41L10.59,12L5,17.59L6.41,19L12,13.41L17.59,19L19,17.59L13.41,12L19,6.41Z";

  function stamp(seconds) {
    if (!seconds) {
      return "never";
    }
    var delta = Date.now() / 1000 - seconds;
    if (delta < 60) {
      return "just now";
    }
    if (delta < 3600) {
      return Math.round(delta / 60) + " min ago";
    }
    if (delta < 86400) {
      return Math.round(delta / 3600) + " h ago";
    }
    return new Date(seconds * 1000).toLocaleDateString();
  }

  function full(seconds) {
    return seconds ? new Date(seconds * 1000).toLocaleString() : "";
  }

  function plural(count, one, many) {
    return count + " " + (count === 1 ? one : many);
  }

  // ---------------------------------------------------------------------------
  // What the indicator says
  //
  // Ordered by what most needs acting on. A broken source anchor outranks
  // everything because it is the one that has stopped the site updating; the
  // Repair checker being switched off outranks its own results because those
  // results are then stale by definition.
  // ---------------------------------------------------------------------------

  function severity() {
    if (!state) {
      return "unknown";
    }
    if (state.source && state.source.broken > 0) {
      return "error";
    }
    if (!state.enabled) {
      return "off";
    }
    var repairs = state.repairs || {};
    if ((repairs.issues || []).length) {
      return "warn";
    }
    if (repairs.state === "running") {
      return "busy";
    }
    if (repairs.state === "stalled" || repairs.state === "failed") {
      return "stalled";
    }
    return "ok";
  }

  function count() {
    if (!state) {
      return 0;
    }
    if (state.source && state.source.broken > 0) {
      return state.source.broken;
    }
    return ((state.repairs || {}).issues || []).length;
  }

  var LABELS = {
    unknown: "Link checkers - status unavailable",
    error: "Link checkers - broken anchors are blocking the rebuild",
    off: "Link checkers - Repair reporting is switched off",
    warn: "Link checkers - open Docs-link repairs",
    busy: "Link checkers - scanning",
    stalled: "Link checkers - last scan did not finish",
    ok: "Link checkers - all clear"
  };

  // ---------------------------------------------------------------------------
  // Panel contents
  // ---------------------------------------------------------------------------

  function section(title) {
    var node = el("section", "chk-section");
    node.appendChild(el("h3", "chk-section__title", title));
    return node;
  }

  function line(className, text) {
    return el("p", "chk-line " + className, text);
  }

  function timeLine(label, seconds) {
    var node = el("p", "chk-meta", label + " " + stamp(seconds));
    if (seconds) {
      node.title = full(seconds);
    }
    return node;
  }

  function sourceSection() {
    var node = section("Documentation source");
    var source = state.source;
    if (!source) {
      node.appendChild(line("chk-line--muted", "Not checked yet."));
      return node;
    }

    if (source.broken > 0) {
      node.appendChild(line("chk-line--error", plural(source.broken, "broken link", "broken links") +
        " of " + source.checked + " checked"));
      // The consequence, not just the count: this is why the site has stopped
      // moving, and it is not obvious from a number on its own.
      node.appendChild(line("chk-line--error-note",
        "The site is not being rebuilt until these are fixed - you are reading the last good commit."));
      var list = el("ul", "chk-list");
      (source.examples || []).forEach(function (item) {
        var row = el("li", "chk-list__item");
        row.appendChild(el("code", "chk-code", item.source));
        row.appendChild(el("span", "chk-arrow", " → "));
        row.appendChild(el("code", "chk-code", item.target));
        row.appendChild(el("span", "chk-tag", item.problem));
        list.appendChild(row);
      });
      node.appendChild(list);
      if (source.truncated) {
        node.appendChild(line("chk-line--muted", "More in the add-on log."));
      }
    } else {
      node.appendChild(line("chk-line--ok", source.checked + " links, all resolving"));
    }
    node.appendChild(timeLine("Checked", source.finished));
    return node;
  }

  function issueRow(issue) {
    var row = el("li", "chk-issue");
    var head = el("div", "chk-issue__head");
    var link = entityHref(issue);
    if (link) {
      var anchor = el("a", "chk-issue__entity", issue.entity_id);
      anchor.href = link;
      // Breaks out of the ingress iframe, which is same-origin with the HA
      // frontend, so this lands on the editor rather than nesting a page.
      anchor.target = "_top";
      head.appendChild(anchor);
    } else {
      head.appendChild(el("span", "chk-issue__entity", issue.entity_id));
    }
    row.appendChild(head);
    if (issue.reason) {
      row.appendChild(el("p", "chk-issue__reason", issue.reason));
    }
    if (issue.rule) {
      row.appendChild(el("p", "chk-meta", "Suggested fix: " + issue.rule));
    }
    return row;
  }

  function entityHref(issue) {
    var id = issue.entity_id || "";
    // No config id means no reliable editor URL. Better a plain row than a
    // guessed link that lands on a 404.
    if (!issue.config_id) {
      return null;
    }
    if (id.indexOf("automation.") === 0) {
      return "/config/automation/edit/" + encodeURIComponent(issue.config_id);
    }
    if (id.indexOf("script.") === 0) {
      return "/config/script/edit/" + encodeURIComponent(issue.config_id);
    }
    return null;
  }

  function repairsSection() {
    var node = section("Docs-link repairs");
    if (!state.enabled) {
      node.appendChild(line("chk-line--muted",
        "Switched off in the add-on configuration (report_doc_link_repairs)."));
      return node;
    }

    var repairs = state.repairs || {};
    var issues = repairs.issues || [];

    if (repairs.state === "running") {
      var progress = "Scanning";
      if (repairs.total) {
        progress += " - " + (repairs.completed || 0) + " of " + repairs.total;
      }
      node.appendChild(line("chk-line--busy", progress));
    } else if (repairs.state === "stalled") {
      node.appendChild(line("chk-line--warn", "The last scan stopped before it finished - check the add-on log."));
    } else if (repairs.state === "failed") {
      node.appendChild(line("chk-line--warn", "The last scan finished with failures - check the add-on log."));
    } else if (repairs.state === "unknown") {
      node.appendChild(line("chk-line--muted", "No scan has run yet."));
    } else {
      node.appendChild(line("chk-line--ok", "Idle"));
    }

    if (repairs.state !== "unknown") {
      var counts = [];
      if (repairs.healthy != null) {
        counts.push(repairs.healthy + " healthy");
      }
      if (repairs.raised != null) {
        counts.push(plural(repairs.raised, "repair raised", "repairs raised"));
      }
      if (repairs.skipped) {
        counts.push(repairs.skipped + " skipped");
      }
      if (repairs.failures) {
        counts.push(repairs.failures + " failed");
      }
      if (counts.length) {
        node.appendChild(el("p", "chk-meta", "Last full scan: " + counts.join(" · ")));
      }
      node.appendChild(timeLine("Completed", repairs.finished));
    }

    if (issues.length) {
      var list = el("ul", "chk-issues");
      issues.forEach(function (issue) {
        list.appendChild(issueRow(issue));
      });
      node.appendChild(list);

      var repairsLink = el("a", "chk-action", "Open Settings › Repairs");
      repairsLink.href = "/config/repairs";
      repairsLink.target = "_top";
      node.appendChild(repairsLink);
    } else {
      node.appendChild(line("chk-line--ok", "No open repairs."));
    }

    var recent = (state.recent || [])[0];
    if (recent) {
      node.appendChild(el("p", "chk-meta",
        "Last entity checked: " + recent.entity_id + " - " +
        (recent.verdict === "valid" ? "link is good" : recent.verdict) +
        ", " + stamp(recent.finished)));
    } else if (!state.watcher) {
      node.appendChild(el("p", "chk-meta", "Entity-update watching is switched off."));
    }
    return node;
  }

  function contents() {
    var body = document.createDocumentFragment();
    if (!state) {
      body.appendChild(line("chk-line--muted", "Cannot reach the add-on status service."));
      return body;
    }
    body.appendChild(sourceSection());
    body.appendChild(repairsSection());
    return body;
  }

  // ---------------------------------------------------------------------------
  // Two homes for the same panel
  //
  // Wide: its own drawer, opened from its own header button.
  // Narrow: the same sections rendered into the mount node annotate.js leaves at
  // the top of the highlights drawer, because a third header button does not fit.
  // ---------------------------------------------------------------------------

  function mountPoint() {
    return document.querySelector(".anno-drawer__extra");
  }

  function isOpen() {
    return !!drawer || !!(narrow && narrow.matches && mountPoint());
  }

  function paint() {
    var level = severity();

    if (button) {
      button.className = "md-header__button md-icon chk-open chk-open--" + level;
      button.title = LABELS[level];
      button.setAttribute("aria-label", LABELS[level]);
      var n = count();
      badge.textContent = n ? String(n) : "";
      badge.style.display = n ? "" : "none";
    }

    // The same signal on the highlights button while our own is hidden.
    if (narrow && narrow.matches) {
      var host = document.querySelector(".anno-open");
      if (host) {
        if (!narrowDot) {
          narrowDot = el("span", "chk-dot");
        }
        narrowDot.className = "chk-dot chk-dot--" + level;
        narrowDot.style.display = level === "ok" || level === "unknown" ? "none" : "";
        if (narrowDot.parentNode !== host) {
          host.appendChild(narrowDot);
        }
      }
    } else if (narrowDot && narrowDot.parentNode) {
      narrowDot.parentNode.removeChild(narrowDot);
    }

    if (drawer) {
      var body = drawer.querySelector(".chk-body");
      body.textContent = "";
      body.appendChild(contents());
    }
    var mount = mountPoint();
    if (mount && narrow && narrow.matches) {
      mount.textContent = "";
      mount.appendChild(contents());
    }
  }

  function toggleDrawer() {
    if (drawer) {
      drawer.remove();
      drawer = null;
      schedule();
      return;
    }
    drawer = el("div", "anno-ui chk-drawer");
    var head = el("div", "chk-head");
    head.appendChild(el("h2", null, "Link checkers"));
    var close = el("button", "chk-close");
    close.type = "button";
    close.setAttribute("aria-label", "Close");
    close.innerHTML = icon(ICON_CLOSE);
    close.addEventListener("click", toggleDrawer);
    head.appendChild(close);
    drawer.appendChild(head);
    drawer.appendChild(el("div", "chk-body"));
    document.body.appendChild(drawer);
    paint();
    // Open means watched closely; and refresh now rather than showing whatever
    // the last slow poll left behind.
    poll();
  }

  function addButton() {
    var header = document.querySelector(".md-header__inner");
    if (!header) {
      return;
    }
    button = el("button", "md-header__button md-icon chk-open");
    button.type = "button";
    button.innerHTML = icon(ICON_LINK);
    badge = el("span", "chk-open__badge");
    badge.style.display = "none";
    button.appendChild(badge);
    button.addEventListener("click", toggleDrawer);
    header.appendChild(button);
  }

  // ---------------------------------------------------------------------------
  // Polling
  // ---------------------------------------------------------------------------

  function wantsFast() {
    return isOpen() || !!(state && (state.repairs || {}).state === "running");
  }

  function schedule() {
    clearTimeout(timer);
    // Nothing at all while the tab is hidden. On a phone the companion app
    // backgrounds this page and there is no reason to keep asking.
    if (document.hidden) {
      return;
    }
    timer = setTimeout(poll, wantsFast() ? POLL_FAST : POLL_SLOW);
  }

  function poll() {
    clearTimeout(timer);
    api("scan")
      .then(function (payload) {
        failures = 0;
        state = payload;
        paint();
      })
      .catch(function (err) {
        failures += 1;
        if (failures >= FAIL_LIMIT) {
          console.error("[ha_docs] checker status unreachable", err);
          state = null;
          paint();
        }
      })
      .then(schedule);
  }

  // ---------------------------------------------------------------------------
  // Wiring
  // ---------------------------------------------------------------------------

  function start() {
    if (!BASE) {
      return;
    }
    narrow = window.matchMedia ? window.matchMedia(NARROW) : null;
    addButton();

    if (narrow) {
      var onChange = function () {
        // Moving across the breakpoint relocates the panel without a reload:
        // a rotate should not strand it in a drawer that is no longer shown.
        if (drawer && narrow.matches) {
          toggleDrawer();
        }
        paint();
      };
      if (narrow.addEventListener) {
        narrow.addEventListener("change", onChange);
      } else if (narrow.addListener) {
        narrow.addListener(onChange);
      }
    }

    document.addEventListener("ha-docs:drawer-open", function () {
      paint();
      if (narrow && narrow.matches) {
        poll();
      }
    });
    document.addEventListener("ha-docs:drawer-close", schedule);

    document.addEventListener("visibilitychange", function () {
      if (document.hidden) {
        clearTimeout(timer);
      } else {
        poll();
      }
    });

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && drawer) {
        toggleDrawer();
      }
    });

    poll();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
