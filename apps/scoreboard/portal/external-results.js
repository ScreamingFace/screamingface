/* WHY: imported reference scores, separate from ranked submissions. */
(function (P) {
  "use strict";

  function sourceCell(row) {
    var td = P.el("td");
    // WHY: an outside source must be an absolute HTTP(S) URL. The shared helper
    // also supports our relative links, which would be misleading for a source citation.
    var href = typeof row.source_url === "string" && /^https?:\/\//i.test(row.source_url)
      ? P.httpUrlOrNull(row.source_url) : null;
    if (!href) {
      td.textContent = "Source unavailable";
      return td;
    }
    var link = P.link("external-result__source", href, "View source");
    link.setAttribute("target", "_blank");
    link.setAttribute("rel", "noopener noreferrer");
    link.setAttribute("aria-label", "View source for " + row.model_name);
    td.appendChild(link);
    return td;
  }

  function renderRow(row) {
    var tr = P.el("tr", "external-result");
    var model = P.el("td", "external-result__model");
    model.appendChild(P.el("span", "mono", row.model_name));
    model.appendChild(P.el("span", "external-result__label", "External · Not reproducible"));
    tr.appendChild(model);
    // WHY native units: not every board is accuracy. This is the same formatter as
    // community scores; metadata must not turn a published percentage into a second scale.
    tr.appendChild(P.el("td", "num", P.formatScore(row.score)));
    tr.appendChild(P.el("td", null, P.formatDate(row.imported_at)));
    tr.appendChild(sourceCell(row));
    var note = row.metadata && row.metadata.comparison_note;
    tr.appendChild(P.el("td", "external-result__note",
      typeof note === "string" && note.trim() ? note : "Evaluation details not provided."));
    return tr;
  }

  function render(baselines) {
    var section = document.getElementById("external-results");
    var body = document.getElementById("external-results-body");
    if (!section || !body) return;
    P.clear(body);
    section.hidden = true;
    if (!Array.isArray(baselines)) return;
    baselines.forEach(function (row) {
      if (!row || typeof row.model_name !== "string" || !row.model_name.trim()
          || typeof row.score !== "number" || !Number.isFinite(row.score)) return;
      body.appendChild(renderRow(row));
    });
    // WHY: never mix baselines into the ranked entry array, chart, or summaries.
    // Import order is retained; this view makes no claim about their relative ranks.
    section.hidden = !body.firstChild;
  }

  window.SFExternalResults = { render: render };
})(window.ScorePortal);
