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
      source_url: row.source_url, metadata: row.metadata, source_health: row.source_health,
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
    var link = P.link("btn ghost external-result__source", href, "Source ↗");
    link.setAttribute("target", "_blank");
    link.setAttribute("rel", "noopener noreferrer");
    link.setAttribute("aria-label", "Source for " + row.spec_id + " (opens in a new tab)");
    td.appendChild(link);
    var health = row.source_health;
    if (health && health.available === false) {
      td.appendChild(P.el("span", "external-result__source-status", "Source unchecked"));
      var date = new Date(health.last_available_at || "");
      var detail = Number.isFinite(date.getTime())
        ? "Last available " + date.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric", timeZone: "UTC" })
        : "No successful check yet";
      td.appendChild(P.el("span", "external-result__source-detail", detail));
    }
    return td;
  }

  function renderRow(row, scoreCell) {
    var tr = P.el("tr", "external-result");
    tr.appendChild(P.el("td", "num", row.rank));
    tr.appendChild(P.el("td", "col-mark"));
    var model = P.el("td", "cell-wrap");
    var description = "External result; not reproducible.";
    var note = comparisonNote(row);
    model.title = description + (typeof note === "string" && note.trim() ? " " + note : "");
    model.appendChild(P.el("span", "mono", row.spec_id));
    model.appendChild(P.el("span", "sr-only", description));
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

  function comparisonNote(row) {
    var metadata = row.metadata || {};
    var note = metadata.comparison_note;
    if (typeof note !== "string" || !note.trim()) {
      note = metadata.comparison && metadata.comparison.prompt_note;
    }
    return typeof note === "string" ? note.trim() : "";
  }

  function renderComparisonNotes(container, rows) {
    if (!container) return;
    P.clear(container);
    container.hidden = true;
    var groups = new Map();
    rows.forEach(function (row) {
      if (!row.external) return;
      var note = comparisonNote(row);
      if (!note) return;
      if (!groups.has(note)) groups.set(note, new Set());
      groups.get(note).add(row.spec_id);
    });
    if (!groups.size) return;
    container.appendChild(P.el("summary", null, "Comparison notes"));
    var content = P.el("div", "external-comparison__content");
    // Shared wording appears once; different notes keep their model attribution.
    groups.forEach(function (models, note) {
      var group = P.el("div", "external-comparison__group");
      group.appendChild(P.el("p", "external-comparison__models", Array.from(models).join(", ")));
      group.appendChild(P.el("p", null, note));
      content.appendChild(group);
    });
    container.appendChild(content);
    container.hidden = false;
  }

  window.SFExternalResults = {
    selectRows: selectRows, renderRow: renderRow, renderComparisonNotes: renderComparisonNotes,
  };
})(window.ScorePortal);
