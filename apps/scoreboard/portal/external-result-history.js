/* WHY: old observations have a reading surface, never a rank or runnable recipe. */
(function (P) {
  "use strict";

  function versionCard(version, currentRevision) {
    var current = version.revision === currentRevision;
    var card = P.el("li", "external-history__version" + (current ? " external-history__version--current" : ""));
    var label = P.el("div", "external-history__identity");
    label.appendChild(P.el("span", "external-history__state", current ? "Current result" : "Previous result"));
    label.appendChild(P.el("span", "external-history__number mono", "Version " + version.revision));
    card.appendChild(label);
    var score = P.el("div", "external-history__score");
    score.appendChild(P.el("span", "mono", P.formatScore(version.score)));
    if (version.metric_name) {
      var metric = version.metric_name === "sad_score" ? "SAD score" : version.metric_name.split("_").join(" ");
      score.appendChild(P.el("span", "external-history__metric", metric));
    }
    card.appendChild(score);
    var saved = P.el("div", "external-history__saved");
    saved.appendChild(P.el("span", "external-history__label", "Saved on"));
    saved.appendChild(P.el("span", null, version.recorded_at ? P.formatDate(version.recorded_at) : "Date unknown"));
    card.appendChild(saved);
    var source = P.el("div", "external-history__source");
    var href = P.httpUrlOrNull(version.source_url);
    if (href) {
      var link = P.link("btn ghost external-result__source", href, "Source ↗");
      link.setAttribute("target", "_blank");
      link.setAttribute("rel", "noopener noreferrer");
      link.setAttribute("aria-label", "Source for version " + version.revision + " (opens in a new tab)");
      source.appendChild(link);
    } else {
      source.appendChild(P.el("span", "external-history__muted", "Source unavailable"));
    }
    card.appendChild(source);
    var details = P.el("div", "external-history__details");
    var checked = version.observed_at ? "Source checked on " + P.formatDate(version.observed_at) : "Source-check date unknown";
    details.appendChild(P.el("p", "external-history__checked", checked));
    var note = P.comparisonNote(version);
    if (typeof note === "string" && note.trim()) details.appendChild(P.el("p", null, note));
    card.appendChild(details);
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
