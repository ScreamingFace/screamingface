/* WHY: imported scores share table ranks, but never acquire a runnable recipe. */
(function (P) {
  "use strict";

  function externalRow(row) {
    // Missing eligibility (including an older API) must never grant a shared rank.
    if (!row || row.ranking_eligible !== true
        || typeof row.model_name !== "string" || !row.model_name.trim()
        || typeof row.score !== "number" || !Number.isFinite(row.score)) return null;
    return {
      external: true, spec_id: row.model_name, score: row.score,
      baseline_id: row.id, benchmark_id: row.benchmark_id,
      observation_revision: row.observation_revision, observation_updated_at: row.observation_updated_at,
      source_url: row.source_url, metadata: row.metadata,
      submitted_at: row.imported_at || null,
      ran_with_providers: [], authors: [], run_cost_usd: null,
    };
  }

  function selectRows(entries, baselines, limit) {
    var measured = entries.map(function (row) { return Object.assign({}, row, { external: false }); });
    var imported = Array.isArray(baselines) ? baselines.map(externalRow).filter(Boolean) : [];
    // WHY limit AFTER merging: a baseline below the fetched community page could have
    // unseen competitors. Only the merged top-N prefix has known, correct global ranks.
    // Stable score sorting preserves community tie order and puts them before external ties.
    return measured.concat(imported).sort(function (a, b) { return b.score - a.score; })
      .slice(0, limit).map(function (row, index) { return Object.assign(row, { rank: index + 1 }); });
  }

  function sourceUrl(value) {
    if (typeof value !== "string") return null;
    try {
      // No base: a relative URL must not be mistaken for an external citation.
      var url = new URL(value);
      return url.protocol === "http:" || url.protocol === "https:" ? url.href : null;
    } catch (error) {
      return null;
    }
  }

  function sourceCell(row) {
    var td = P.el("td", "col-run");
    var href = sourceUrl(row.source_url);
    if (!href) {
      td.textContent = P.EM_DASH;
      return td;
    }
    var link = P.link("external-result__source", href, "Original result ↗");
    link.setAttribute("target", "_blank");
    link.setAttribute("rel", "noopener noreferrer");
    link.setAttribute("aria-label", "Original result for " + row.spec_id + " (opens in a new tab)");
    td.appendChild(link);
    return td;
  }

  function renderRow(row, scoreCell) {
    var tr = P.el("tr", "external-result");
    tr.appendChild(P.el("td", "num", row.rank));
    tr.appendChild(P.el("td", "col-mark"));
    var model = P.el("td", "cell-wrap");
    var description = "External result; not reproducible.";
    var note = row.metadata && row.metadata.comparison_note;
    if ((typeof note !== "string" || !note.trim()) && row.metadata && row.metadata.comparison) {
      note = row.metadata.comparison.prompt_note;
    }
    model.title = description + (typeof note === "string" && note.trim() ? " " + note : "");
    model.appendChild(P.el("span", "mono", row.spec_id));
    model.appendChild(P.el("span", "sr-only", description));
    if (typeof note === "string" && note.trim()) {
      var details = P.el("details", "external-result__comparison");
      details.appendChild(P.el("summary", null, "Comparison"));
      details.appendChild(P.el("p", null, note));
      model.appendChild(details);
    }
    tr.appendChild(model);
    tr.appendChild(P.el("td", null, P.EM_DASH));
    tr.appendChild(P.el("td", null, P.EM_DASH));
    tr.appendChild(scoreCell);
    tr.appendChild(P.el("td", "num", P.EM_DASH));
    var date = P.el("td", null, P.formatDate(row.submitted_at));
    if (row.submitted_at) date.title = "Imported on " + row.submitted_at;
    if (row.observation_revision > 1 && row.baseline_id && row.benchmark_id) {
      var history = P.link("external-result__history", "external-result-history.html?benchmark="
        + encodeURIComponent(row.benchmark_id) + "&result=" + encodeURIComponent(row.baseline_id), "Updated");
      history.setAttribute("aria-label", "View update history for " + row.spec_id);
      if (row.observation_updated_at) history.title = "Updated " + P.formatDate(row.observation_updated_at);
      date.appendChild(history);
    }
    tr.appendChild(date);
    tr.appendChild(sourceCell(row));
    return tr;
  }

  window.SFExternalResults = { selectRows: selectRows, renderRow: renderRow };
})(window.ScorePortal);
