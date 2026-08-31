/*
 * Click-to-sort table headers for the HA Docs add-on.
 *
 * The docs set is table-heavy - INVENTORY.md, DEVICES.md, ENTITY-INDEX.md and
 * dashboard-macros.md are all long rosters read by scanning for one value - and
 * a pipe table has exactly one order: the one it was written in.
 *
 * Material documents a tablesort integration, but it loads the library from
 * unpkg and drives column types from `data-sort-method` attributes on each
 * <th>. Neither works here. The box has no outbound access (see
 * mermaid-init.js for the same reasoning), and those attributes would have to
 * be authored in the docs repo, which is deliberately free of any site
 * scaffolding so that it keeps rendering identically on GitHub. Both problems
 * go away by sniffing the column type from its own cells, which is most of
 * what the library would have done anyway - so nothing is vendored for this
 * and the offline guarantee holds by construction.
 *
 * Interaction with annotate.js, which was checked rather than assumed:
 *
 *  - Existing highlights need nothing. paint() wraps text in <mark> elements
 *    inside the cell, so they are descendants of the <tr> and move with it.
 *    Repainting after a sort would be actively wrong - render() does not
 *    unpaint first, and re-resolving against a stored hint measured in the
 *    original order could walk a correctly-placed highlight onto another row.
 *  - Nothing can be orphaned. A sort permutes substrings, so a stored `exact`
 *    is always still somewhere in the flattened text.
 *  - Nothing can be corrupted. locate() never writes back, and the popover
 *    re-POSTs the anchor fields unchanged.
 *
 * What is left is one accepted limitation, documented in DOCS.md: a highlight
 * CREATED while a table is sorted has its prefix/suffix/hint captured in the
 * sorted order, so after a reload it resolves by bare `exact`. Unique text
 * (an entity ID, a name) still lands correctly; a short repeated value such as
 * `Approved` can land on a sibling row. Clicking back to the original order
 * before highlighting avoids it entirely.
 */
(function () {
  "use strict";

  // A 3-row table gains nothing from sorting and loses a clean header to the
  // affordance. At 5 this covers the rosters (197 of the 486 tables in the
  // docs set) and leaves the small reference tables alone - including, on
  // plans/README.md, the 4-row status vocabulary sitting directly above the
  // 8-row index that does get it.
  var MIN_ROWS = 5;

  // numeric: true is what sorts "row 2" before "row 10" and makes the plans
  // index (001, 002, ...) come out right even when a stray cell keeps the
  // column off the numeric branch. sensitivity: "base" so an entity ID does
  // not sort away from the same word capitalised.
  var collator = new Intl.Collator(undefined, {
    numeric: true,
    sensitivity: "base"
  });

  // Thousands separators and a trailing unit should not force a column onto
  // the text branch: descriptions-before-008.md has "87,493" against "73,780",
  // which compares backwards as a string.
  var NUMERIC = /^[-+]?\d[\d,]*(\.\d+)?\s*[%a-zA-Z/]{0,12}$/;
  var ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

  function cells(row) {
    return Array.prototype.slice.call(row.cells);
  }

  // The rendered text is what the reader is scanning, so `code`, **bold** and
  // link labels all collapse to it. Whitespace is normalised because the HTML
  // carries the source's line wrapping inside a cell.
  function key(cell) {
    return cell ? cell.textContent.replace(/\s+/g, " ").trim() : "";
  }

  function toNumber(text) {
    return parseFloat(text.replace(/[^0-9.eE+-]/g, ""));
  }

  // Sniffed once per column, from the column itself. Blank cells are ignored
  // rather than disqualifying: a mostly-numeric column with two gaps is still
  // a numeric column.
  function columnType(rows, index) {
    var seen = 0;
    var numeric = true;
    var dates = true;

    for (var i = 0; i < rows.length; i++) {
      var text = key(rows[i].cells[index]);
      if (!text) {
        continue;
      }
      seen++;
      if (numeric && !(NUMERIC.test(text) && isFinite(toNumber(text)))) {
        numeric = false;
      }
      if (dates && !ISO_DATE.test(text)) {
        dates = false;
      }
      if (!numeric && !dates) {
        return "text";
      }
    }

    if (!seen) {
      return "text";
    }
    // Dates are checked first because an ISO date is lexically ordered
    // already, and stripping its hyphens for a numeric compare would turn
    // 2026-08-28 into a single 8-digit number with the sign of its own dashes.
    return dates ? "date" : numeric ? "number" : "text";
  }

  function compare(a, b, type) {
    // An empty cell is missing data, not a minimum. Sorting it to the bottom
    // in both directions keeps the rows you can actually read together,
    // instead of putting a block of blanks at the top of every descending
    // sort. Returned unsigned, so the caller's direction flip cannot drag them
    // back up.
    if (!a || !b) {
      return !a && !b ? 0 : a ? -1 : 1;
    }
    if (type === "number") {
      return toNumber(a) - toNumber(b);
    }
    return collator.compare(a, b);
  }

  // Appended to <body>, deliberately NOT into the article. annotate.js flattens
  // article.md-content__inner into one string to anchor highlights by character
  // offset, so a live region inside it would inject text into that index and
  // shift every offset after it.
  var live = null;

  function announce(message) {
    if (!live) {
      live = document.createElement("div");
      live.setAttribute("aria-live", "polite");
      live.setAttribute("role", "status");
      // Clipped rather than display:none or visibility:hidden, both of which
      // take the element out of the accessibility tree and silence it.
      live.style.cssText =
        "position:absolute;width:1px;height:1px;overflow:hidden;" +
        "clip:rect(0 0 0 0);clip-path:inset(50%);white-space:nowrap";
      document.body.appendChild(live);
    }
    live.textContent = message;
  }

  function sort(table, th, index, direction) {
    var body = table.tBodies[0];
    var rows = Array.prototype.slice.call(body.rows);

    if (direction === "none") {
      rows.sort(function (x, y) {
        return x._haOrder - y._haOrder;
      });
    } else {
      var type = th._haType;
      if (type === undefined) {
        type = th._haType = columnType(rows, index);
      }
      var sign = direction === "ascending" ? 1 : -1;
      rows.sort(function (x, y) {
        var a = key(x.cells[index]);
        var b = key(y.cells[index]);
        // Blanks are placed by compare() alone, before the direction is
        // applied, so they stay at the bottom either way.
        if (!a || !b) {
          return compare(a, b, type) || x._haOrder - y._haOrder;
        }
        var result = compare(a, b, type);
        // Ties fall back to the authored order, which makes the sort stable in
        // both directions - two rows sharing a status stay in the order they
        // were written rather than swapping on every re-sort.
        return result ? result * sign : x._haOrder - y._haOrder;
      });
    }

    // One write. Appending an already-parented row moves it, so the fragment
    // ends up holding every row and the tbody is refilled in a single
    // operation rather than reflowing once per row.
    var fragment = document.createDocumentFragment();
    rows.forEach(function (row) {
      fragment.appendChild(row);
    });
    body.appendChild(fragment);

    Array.prototype.forEach.call(table.tHead.rows[0].cells, function (other) {
      if (other !== th) {
        // Only the direction is cleared; the sniffed type stays cached on the
        // header, since the cells it was derived from have not changed.
        other.setAttribute("aria-sort", "none");
      }
    });
    th.setAttribute("aria-sort", direction);

    // aria-sort alone is announced inconsistently across screen readers, so
    // the live region is the dependable route.
    var label = key(th);
    announce(
      direction === "none"
        ? "Original order restored"
        : "Sorted by " + (label || "column " + (index + 1)) + ", " + direction
    );
  }

  function advance(th) {
    var current = th.getAttribute("aria-sort");
    if (current === "ascending") {
      return "descending";
    }
    // Third click returns the table to the order it was written in. These
    // tables are curated - the plans index is in plan-number order, INVENTORY
    // is grouped by domain - so the authored order is a real destination and
    // not merely "unsorted".
    return current === "descending" ? "none" : "ascending";
  }

  function enable(table) {
    if (!table.tHead || !table.tHead.rows.length || table.tBodies.length !== 1) {
      return;
    }

    var body = table.tBodies[0];
    if (body.rows.length < MIN_ROWS) {
      return;
    }

    var headers = cells(table.tHead.rows[0]);
    var width = headers.length;

    // GFM pipe tables never emit a span or a ragged row, but md_in_html is
    // enabled, so a hand-written table could. Sorting one would shred it.
    var irregular = Array.prototype.some.call(body.rows, function (row) {
      return (
        row.cells.length !== width ||
        Array.prototype.some.call(row.cells, function (cell) {
          return cell.colSpan > 1 || cell.rowSpan > 1;
        })
      );
    });
    if (irregular) {
      return;
    }

    // A property rather than a data- attribute: annotate.js walks the article
    // for text nodes and rebuilds character offsets from what it finds, and
    // there is no reason to add anything to the DOM that it then has to skip.
    Array.prototype.forEach.call(body.rows, function (row, i) {
      row._haOrder = i;
    });

    // Deliberately no class on the <table>. Material styles ordinary markdown
    // tables through `.md-typeset table:not([class])`, so adding any class at
    // all - even an unused one - drops the borders, padding and header shading
    // off every table this touches. aria-sort has to be set regardless, so
    // tables.css hooks the styling to that instead and the table element is
    // left exactly as MkDocs emitted it.
    headers.forEach(function (th, index) {
      th.setAttribute("aria-sort", "none");
      th.tabIndex = 0;

      th.addEventListener("click", function (event) {
        // A header is ordinary prose too: it can hold a link, and annotate.js
        // lets you highlight it. Neither should be hijacked into a sort.
        if (event.target.closest("a, mark.anno")) {
          return;
        }
        // Dragging out a selection ends in a click. Without this, selecting a
        // header to highlight it would also re-sort the table out from under
        // the selection.
        var selection = window.getSelection();
        if (selection && !selection.isCollapsed) {
          return;
        }
        sort(table, th, index, advance(th));
      });

      th.addEventListener("keydown", function (event) {
        if (event.key === "Enter" || event.key === " ") {
          // Space scrolls the page by default, which would throw the reader
          // off the table they just sorted.
          event.preventDefault();
          sort(table, th, index, advance(th));
        }
      });
    });
  }

  function start() {
    // Same root as annotate.js, and for the same reason: the sidebar and the
    // footer also contain markup, and neither should grow sort affordances.
    var root =
      document.querySelector("article.md-content__inner") ||
      document.querySelector(".md-typeset");
    if (!root) {
      return;
    }
    Array.prototype.forEach.call(root.querySelectorAll("table"), enable);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
