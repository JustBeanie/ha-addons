/*
 * Desktop sidebar controls for the HA Docs add-on.
 *
 * Material exposes the document navigation and page contents as independent
 * sidebars, but its built-in toggles only turn them into drawers below the
 * desktop breakpoint. These controls keep the wide layout useful for a long
 * document or a narrow ingress window without replacing Material navigation.
 */
(function () {
  "use strict";

  var STORAGE_PREFIX = "ha-docs:panel:";
  var panels = [
    {
      name: "navigation",
      selector: ".md-sidebar--primary",
      icon: "<svg viewBox=\"0 0 24 24\" aria-hidden=\"true\"><path d=\"M3 5h18v2H3V5zm0 6h18v2H3v-2zm0 6h18v2H3v-2z\"/></svg>"
    },
    {
      name: "contents",
      selector: ".md-sidebar--secondary",
      icon: "<svg viewBox=\"0 0 24 24\" aria-hidden=\"true\"><path d=\"M3 5h2v2H3V5zm4 0h14v2H7V5zM3 11h2v2H3v-2zm4 0h14v2H7v-2zm-4 6h2v2H3v-2zm4 0h14v2H7v-2z\"/></svg>"
    }
  ];

  function key(name) {
    return STORAGE_PREFIX + name;
  }

  function read(name) {
    try {
      return window.localStorage.getItem(key(name)) === "collapsed";
    } catch (err) {
      return false;
    }
  }

  function write(name, collapsed) {
    try {
      window.localStorage.setItem(key(name), collapsed ? "collapsed" : "open");
    } catch (err) {
      // Browsers may deny storage in a private or embedded context. The
      // control still works for this page load, it just cannot be remembered.
    }
  }

  function label(panel, collapsed) {
    return (collapsed ? "Show " : "Hide ") + panel.name;
  }

  function apply(panel, collapsed) {
    var attribute = "data-ha-docs-" + panel.name + "-collapsed";
    var button = panel.button;

    if (collapsed) {
      document.body.setAttribute(attribute, "");
    } else {
      document.body.removeAttribute(attribute);
    }

    button.setAttribute("aria-pressed", String(collapsed));
    button.setAttribute("aria-label", label(panel, collapsed));
    button.title = label(panel, collapsed);
  }

  function addButton(panel) {
    var header = document.querySelector(".md-header__inner");
    if (!header || !document.querySelector(panel.selector)) {
      return;
    }

    var button = document.createElement("button");
    button.type = "button";
    button.className = "md-header__button md-icon ha-docs-panel-toggle";
    button.setAttribute("data-ha-docs-panel", panel.name);
    button.innerHTML = panel.icon;
    panel.button = button;

    var collapsed = read(panel.name);
    apply(panel, collapsed);
    button.addEventListener("click", function () {
      var next = !document.body.hasAttribute(
        "data-ha-docs-" + panel.name + "-collapsed"
      );
      apply(panel, next);
      write(panel.name, next);
    });
    header.appendChild(button);
  }

  function start() {
    // Material supplies drawer toggles at smaller widths. The controls remain
    // in the DOM for a stable preference, but CSS hides them until both
    // sidebars are actually part of the desktop layout.
    for (var i = 0; i < panels.length; i++) {
      addButton(panels[i]);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
