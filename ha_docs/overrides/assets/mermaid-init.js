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
 *
 * The runtime is 3.5 MB and is loaded by this script, asynchronously and only
 * when the page has a diagram (Plan 021). Loaded from extra_javascript it
 * blocked every page, and annotate.js and checker.js behind it, whether or not
 * there was anything to draw. Diagrams then render one at a time as they come
 * within a viewport of the screen, not all at once on load.
 */
(function () {
  "use strict";

  var SELECTOR = ".diagram";

  // Captured now: document.currentScript is null once this first synchronous
  // run is over. Derived from this script's own URL, never location, because
  // ingress mounts the site under a /api/hassio_ingress/<token>/ prefix that
  // rotates - the same rule annotate.js follows for its API base.
  var RUNTIME = (function () {
    var el = document.currentScript;
    if (!el) {
      var all = document.getElementsByTagName("script");
      for (var i = 0; i < all.length; i++) {
        if (/assets\/mermaid-init\.js(\?|$)/.test(all[i].src)) {
          el = all[i];
          break;
        }
      }
    }
    // Keeps this script's ?v= (asset_version.py). The digest covers the runtime
    // too, so the versioned URL can be cached as immutable like every other
    // asset instead of revalidating 3.5 MB on every page with a diagram.
    return el ? el.src.replace(/mermaid-init\.js(\?.*)?$/, "mermaid.min.js$1") : null;
  })();

  function currentTheme() {
    return document.body.getAttribute("data-md-color-scheme") === "slate"
      ? "dark"
      : "default";
  }

  function diagrams() {
    return Array.prototype.slice.call(document.querySelectorAll(SELECTOR));
  }

  // One shared load. A palette toggle or a second diagram scrolling into view
  // while the runtime is still arriving must not inject it again.
  var loading = null;

  function loadRuntime() {
    if (window.mermaid) {
      return Promise.resolve(window.mermaid);
    }
    if (!loading) {
      loading = new Promise(function (resolve, reject) {
        if (!RUNTIME) {
          reject(new Error("cannot locate mermaid.min.js"));
          return;
        }
        var script = document.createElement("script");
        script.src = RUNTIME;
        script.async = true;
        script.onload = function () {
          if (window.mermaid) {
            resolve(window.mermaid);
          } else {
            reject(new Error("mermaid.min.js loaded but defined nothing"));
          }
        };
        script.onerror = function () {
          reject(new Error("mermaid.min.js did not load"));
        };
        document.head.appendChild(script);
      });
    }
    return loading;
  }

  // Monotonic, so two diagrams can never share an SVG id. This is not
  // decoration: mermaid.run() derives its id from Date.now(), so three
  // diagrams on one page render fast enough to collide, and the later ones
  // come out as an empty <svg> with no viewBox and no error.
  var seq = 0;

  // Bumped by every palette change. A render started under an older value
  // throws its result away - success or failure - so a slow render in the old
  // theme can never land on top of a newer one.
  var generation = 0;
  var configured = -1;

  // Renders run strictly one after another. mermaid.initialize() is global
  // state, so renders overlapping a palette change are exactly how the old
  // theme could leak into the new one.
  var chain = Promise.resolve();

  // Per-diagram progress, kept on the element:
  //   waiting   - observed, not near the viewport yet
  //   queued    - on the chain
  //   rendering - render() in flight
  //   drawn     - SVG or error block in place
  function state(el, value) {
    if (value === undefined) {
      return el.getAttribute("data-diagram-state");
    }
    el.setAttribute("data-diagram-state", value);
  }

  function configure(mermaid) {
    if (configured === generation) {
      return;
    }
    mermaid.initialize({
      startOnLoad: false,
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
    configured = generation;
  }

  function renderOne(el) {
    return loadRuntime().then(function (mermaid) {
      var started = generation;
      configure(mermaid);
      state(el, "rendering");
      var id = "diagram-" + seq++;
      return mermaid.render(id, el.dataset.diagramSource).then(
        function (result) {
          if (started !== generation) {
            return;
          }
          el.innerHTML = result.svg;
          if (result.bindFunctions) {
            result.bindFunctions(el);
          }
          el.setAttribute("data-processed", "true");
          state(el, "drawn");
        },
        function (err) {
          if (started !== generation) {
            return;
          }
          el.classList.add("diagram--error");
          // Leaving data-processed off puts the block back in the
          // ":not([data-processed])" style, which is what makes the message
          // and its source render as readable monospace.
          el.removeAttribute("data-processed");
          el.textContent =
            "Diagram failed to render — " +
            ((err && err.message) || String(err)) +
            "\n\n" +
            el.dataset.diagramSource;
          state(el, "drawn");
        }
      );
    });
  }

  var reported = false;

  function enqueue(el) {
    if (state(el) === "queued") {
      return;
    }
    state(el, "queued");
    chain = chain
      .then(function () {
        return renderOne(el);
      })
      .catch(function (err) {
        // Only the runtime failing to load gets here - a parse error is
        // handled per diagram above. The fence text is still on the page, so
        // the reader keeps the source; say why once, not once per diagram.
        state(el, "waiting");
        if (!reported) {
          reported = true;
          console.error("[ha_docs] " + err.message + " — diagrams will show as text.");
        }
      });
  }

  function paletteChanged() {
    generation++;
    diagrams().forEach(function (el) {
      var current = state(el);
      if (current === "drawn") {
        // Mermaid replaced the source with an <svg>; put it back first.
        el.textContent = el.dataset.diagramSource;
        el.removeAttribute("data-processed");
        el.classList.remove("diagram--error");
        enqueue(el);
      } else if (current === "rendering") {
        // Its result will be discarded as stale; queue a fresh one.
        enqueue(el);
      }
      // "queued" renders under the new theme when it is reached, and
      // "waiting" when it scrolls into view - neither needs anything.
    });
  }

  function start() {
    var els = diagrams();
    if (!els.length) {
      // No diagram, no 3.5 MB download.
      return;
    }

    var observer = null;
    if ("IntersectionObserver" in window) {
      observer = new IntersectionObserver(
        function (entries) {
          entries.forEach(function (entry) {
            if (entry.isIntersecting) {
              observer.unobserve(entry.target);
              enqueue(entry.target);
            }
          });
        },
        // Start a viewport early, so a diagram is usually drawn by the time
        // it is scrolled to.
        { rootMargin: "100% 0px" }
      );
    }

    els.forEach(function (el) {
      // Mermaid replaces the element's content with an <svg>, so the source
      // is only readable once. Stash it before anything else touches it.
      el.dataset.diagramSource = el.textContent;
      state(el, "waiting");
      if (observer) {
        observer.observe(el);
      } else {
        enqueue(el);
      }
    });

    // Material rewrites data-md-color-scheme on <body> when the palette is
    // toggled. `navigation.instant` is not enabled, so ordinary page loads
    // re-run this script and need no further hook.
    new MutationObserver(function (records) {
      for (var i = 0; i < records.length; i++) {
        if (records[i].attributeName === "data-md-color-scheme") {
          paletteChanged();
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
