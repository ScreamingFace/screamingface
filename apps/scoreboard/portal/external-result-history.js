/* WHY: old observations have a reading surface, never a rank or runnable recipe. */
(function (P) {
  "use strict";

  function field(list, label, value) {
    list.appendChild(P.el("dt", null, label));
    list.appendChild(P.el("dd", null, value));
  }

  function versionCard(version, currentRevision) {
    var card = P.el("section", "external-history__version");
    card.appendChild(P.el("h2", null, version.revision === currentRevision ? "Current result" : "Previous result"));
    var score = P.el("p", "external-history__score mono", P.formatScore(version.score));
    if (version.metric_name) score.appendChild(P.el("span", "external-history__metric", version.metric_name));
    card.appendChild(score);
    var facts = P.el("dl", "external-history__facts");
    field(facts, "Recorded", version.recorded_at ? P.formatDate(version.recorded_at) : "Date unknown");
    field(facts, "Source read", version.observed_at ? P.formatDate(version.observed_at) : "Date unknown");
    card.appendChild(facts);
    var href = P.httpUrlOrNull(version.source_url);
    if (href) {
      var link = P.link("external-result__source", href, "Source ↗");
      link.setAttribute("target", "_blank");
      link.setAttribute("rel", "noopener noreferrer");
      link.setAttribute("aria-label", "Source for version " + version.revision + " (opens in a new tab)");
      card.appendChild(link);
    }
    var note = version.metadata && version.metadata.comparison_note;
    if (typeof note === "string" && note.trim()) card.appendChild(P.el("p", null, note));
    return card;
  }

  P.ready(function () {
    var status = document.getElementById("history-status");
    var more = document.getElementById("history-more");
    var versions = document.getElementById("history-versions");
    var before = null, busy = false, count = 0, currentRevision = null;
    var benchmark, result;
    try {
      benchmark = P.requireParam("benchmark");
      result = P.requireParam("result");
    } catch (error) {
      status.textContent = "Open history from a leaderboard result.";
      return;
    }
    document.getElementById("history-back").setAttribute("href", "benchmark.html?id=" + encodeURIComponent(benchmark));
    function load() {
      if (busy) return Promise.resolve();
      busy = true;
      more.disabled = true;
      status.hidden = false;
      status.textContent = "Loading…";
      var path = "/v1/leaderboard/" + encodeURIComponent(benchmark) + "/external-results/"
        + encodeURIComponent(result) + "/history?limit=20" + (before === null ? "" : "&before=" + before);
      return P.fetchJson(path).then(function (data) {
        document.getElementById("history-model").textContent = data.model_name;
        // WHY: keep one current marker during paging. New edits require a refresh,
        // otherwise a late page could silently relabel the initially loaded snapshot.
        if (currentRevision === null) currentRevision = data.current_revision;
        data.versions.forEach(function (version) { versions.appendChild(versionCard(version, currentRevision)); });
        count += data.versions.length;
        before = data.next_before;
        more.hidden = before === null;
        more.textContent = "Show older versions";
        status.textContent = count ? "" : "No saved history yet.";
        if (data.current_revision !== currentRevision) status.textContent = "This result changed. Refresh to see the latest version.";
        status.hidden = !status.textContent;
      }).catch(function () {
        status.textContent = "Could not load history. Try again.";
        more.hidden = false;
        more.textContent = "Retry";
      }).finally(function () { busy = false; more.disabled = false; });
    }
    more.addEventListener("click", load);
    load();
  });
})(window.ScorePortal);
