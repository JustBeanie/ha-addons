/*
 * Mermaid bootstrap for the HA Docs add-on.
 *
 * Material for MkDocs ships its own Mermaid integration, but it fetches the
 * runtime from cdn.jsdelivr.net at page load. This add-on serves a LAN-only
 * box with no outbound access, so that path is deliberately avoided: the
 * superfences custom fence in mkdocs.yml emits `<div class="diagram">` rather
 * than the `mermaid` class Material looks for, which leaves its integration
 * dormant, and the runtime is vendored into the image by the Dockerfile.
 *
 * Consequences of owning the bootstrap ourselves:
 *  - the palette toggle has to re-render, because Mermaid bakes theme colours
 *    into the SVG at render time rather than reading CSS variables;
 *  - a diagram that fails to parse has to say so on the page. Left to itself
 *    Mermaid logs to the console and leaves an empty block, and `mkdocs build`
 *    still exits 0 - so a typo would reach the site as a silent gap.
 */
(function () {
  "use strict";

  var SELECTOR = ".diagram";

  function currentTheme() {
    return document.body.getAttribute("data-md-color-scheme") === "slate"
      ? "dark"
      : "default";
  }

  function diagrams() {
    return Array.prototype.slice.call(document.querySelectorAll(SELECTOR));
  }

  // Monotonic, so two diagrams can never share an SVG id. This is not
  // decoration: mermaid.run() derives its id from Date.now(), so three
  // diagrams on one page render fast enough to collide, and the later ones
  // come out as an empty <svg> with no viewBox and no error.
  var seq = 0;

  function renderOne(el) {
    var id = "diagram-" + seq++;
    return window.mermaid
      .render(id, el.dataset.diagramSource)
      .then(function (result) {
        el.innerHTML = result.svg;
        if (result.bindFunctions) {
          result.bindFunctions(el);
        }
        el.setAttribute("data-processed", "true");
      })
      .catch(function (err) {
        el.classList.add("diagram--error");
        // Leaving data-processed off puts the block back in the
        // ":not([data-processed])" style, which is what makes the message and
        // its source render as readable monospace.
        el.removeAttribute("data-processed");
        el.textContent =
          "Diagram failed to render — " +
          ((err && err.message) || String(err)) +
          "\n\n" +
          el.dataset.diagramSource;
      });
  }

  function render() {
    var els = diagrams();
    if (!els.length) {
      return;
    }

    els.forEach(function (el) {
      // Mermaid replaces the element's content with an <svg>, so the source
      // is only readable once. Stash it on the first pass; every later pass
      // (palette toggle) restores it before re-rendering.
      if (el.dataset.diagramSource === undefined) {
        el.dataset.diagramSource = el.textContent;
      } else {
        el.textContent = el.dataset.diagramSource;
      }
      el.removeAttribute("data-processed");
      el.classList.remove("diagram--error");
    });

    window.mermaid.initialize({
      startOnLoad: false,
      // Repository diagrams are untrusted.  Make the security boundary
      // explicit rather than inheriting a future Mermaid default, disable HTML
      // labels/click handlers, and cap parser work per block.
      securityLevel: "strict",
      htmlLabels: false,
      maxTextSize: 50000,
      theme: currentTheme(),
      // `font: false` in mkdocs.yml puts the page on system fonts. Mermaid's
      // own default stack would make every diagram look foreign to its page.
      fontFamily: "inherit",
      // Render at natural size and let .diagram scroll. With useMaxWidth on,
      // mermaid shrinks a large flowchart to the container width instead -
      // which under ingress, in a narrow sidebar iframe, produces a diagram
      // too small to read and with nothing to scroll.
      flowchart: { useMaxWidth: false },
      sequence: { useMaxWidth: false },
      state: { useMaxWidth: false }
    });

    els.forEach(renderOne);
  }

  function start() {
    if (!window.mermaid) {
      console.error(
        "[ha_docs] mermaid.min.js did not load — diagrams will show as text."
      );
      return;
    }

    render();

    // Material rewrites data-md-color-scheme on <body> when the palette is
    // toggled. `navigation.instant` is not enabled, so ordinary page loads
    // re-run this script and need no further hook.
    new MutationObserver(function (records) {
      for (var i = 0; i < records.length; i++) {
        if (records[i].attributeName === "data-md-color-scheme") {
          render();
          return;
        }
      }
    }).observe(document.body, { attributes: true });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
