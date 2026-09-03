/* Score/cost Pareto chart for the public benchmark board (OME-923 part C).
 *
 * The pure model is exported to Node for the existing portal test gate. The browser half renders
 * an SVG with DOM APIs only: spec ids are community input, so no value ever reaches innerHTML.
 */
(function (root, factory) {
  "use strict";
  var logic;
  if (typeof module === "object" && module.exports) {
    logic = require("./leaderboard-logic.js");
    module.exports = factory(logic);
  } else {
    root.SFParetoChart = factory(root.SFLeaderboardLogic);
  }
})(typeof self !== "undefined" ? self : this, function (L) {
  "use strict";

  var SVG_NS = "http://www.w3.org/2000/svg";

  function finiteScore(entry) {
    return !!entry && typeof entry.score === "number" && isFinite(entry.score);
  }

  function normalize(value, low, high, logarithmic) {
    if (low === high) return 0.5;
    if (logarithmic) {
      return (Math.log(value) - Math.log(low)) / (Math.log(high) - Math.log(low));
    }
    return (value - low) / (high - low);
  }

  function sourcePoint(entry, leaderScore) {
    var cost = L.costNumber(entry);
    return {
      entry: entry,
      specId: String(entry.spec_id || "Unnamed spec"),
      score: entry.score,
      cost: cost !== null && cost >= 0 ? cost : null,
      isFrontier: false,
      isLeader: entry.score === leaderScore,
      x: 0,
      y: 0,
    };
  }

  // FEATURE: OME-923 Part C — one model feeds every visual element in the chart.
  //
  // INVARIANT: membership is never recomputed here. The table mark is a whole-board server
  // decision, so the chart consumes the exact same strict field. Recomputing over the bounded
  // page would let a row hidden below `top` dominate a visible point while the chart still drew
  // that point as efficient.
  function buildChartModel(entries) {
    var valid = (entries || []).filter(finiteScore);
    if (!valid.length) return null;

    var leaderScore = Math.max.apply(null, valid.map(function (entry) { return entry.score; }));
    var sources = valid.map(function (entry) { return sourcePoint(entry, leaderScore); });
    var pricedSources = sources.filter(function (point) { return point.cost !== null; });
    if (!pricedSources.length) return null;
    if (!pricedSources.some(function (point) { return L.isParetoMarked(point.entry); })) return null;

    var costs = pricedSources.map(function (point) { return point.cost; });
    var scores = sources.map(function (point) { return point.score; });
    var costMin = Math.min.apply(null, costs);
    var costMax = Math.max.apply(null, costs);
    var scoreMin = Math.min.apply(null, scores);
    var scoreMax = Math.max.apply(null, scores);
    var logarithmic = costMin > 0 && costMax / costMin > 8;

    var priced = pricedSources.map(function (point) {
      return {
        entry: point.entry,
        specId: point.specId,
        score: point.score,
        cost: point.cost,
        isFrontier: L.isParetoMarked(point.entry),
        isLeader: point.isLeader,
        x: normalize(point.cost, costMin, costMax, logarithmic),
        y: normalize(point.score, scoreMin, scoreMax, false),
      };
    });
    var unpriced = sources
      .filter(function (point) { return point.cost === null; })
      .map(function (point) {
        point.y = normalize(point.score, scoreMin, scoreMax, false);
        return point;
      });
    var frontier = priced
      .filter(function (point) { return point.isFrontier; })
      .slice()
      .sort(function (a, b) { return a.cost - b.cost || a.score - b.score; });

    return {
      priced: priced,
      unpriced: unpriced,
      frontier: frontier,
      costScale: logarithmic ? "log" : "linear",
      costDomain: [costMin, costMax],
      scoreDomain: [scoreMin, scoreMax],
      leaderScore: leaderScore,
    };
  }

  function svgElement(tag, className, attrs, text) {
    var node = document.createElementNS(SVG_NS, tag);
    if (className) node.setAttribute("class", className);
    Object.keys(attrs || {}).forEach(function (key) { node.setAttribute(key, attrs[key]); });
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function clear(node) {
    while (node && node.firstChild) node.removeChild(node.firstChild);
  }

  function atScale(t, domain, scale) {
    if (domain[0] === domain[1]) return domain[0];
    if (scale === "log") {
      return Math.exp(Math.log(domain[0]) + t * (Math.log(domain[1]) - Math.log(domain[0])));
    }
    return domain[0] + t * (domain[1] - domain[0]);
  }

  function tickPositions(domain) {
    return domain[0] === domain[1] ? [0.5] : [0, 0.25, 0.5, 0.75, 1];
  }

  function allUnique(values) {
    return values.every(function (value, index) { return values.indexOf(value) === index; });
  }

  function fixedCost(value, places) {
    var parts = value.toFixed(places).split(".");
    parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ",");
    return "$" + parts.join(".");
  }

  // WHY the table formatter is only the first choice: it deliberately rounds ordinary costs to
  // cents. That is right for a compact cell, but on a narrow chart domain ($1.001–$1.004) it
  // labels every tick "$1.00" while spreading the points across the full axis. Increase precision
  // only when needed, capped at the wire contract's six decimal places. If four interpolated
  // intervals cannot all be named distinctly at that precision, retain the exact endpoints rather
  // than publish duplicate labels.
  function buildCostTicks(domain, scale, formatCost) {
    var positions = tickPositions(domain);
    var values = positions.map(function (t) { return atScale(t, domain, scale); });
    var labels = values.map(function (value) {
      return formatCost({ run_cost_usd: String(value) });
    });
    var places;

    if (!allUnique(labels)) {
      for (places = 2; places <= 6; places += 1) {
        labels = values.map(function (value) { return fixedCost(value, places); });
        if (allUnique(labels)) break;
      }
      if (!allUnique(labels)) {
        positions = [0, 1];
        values = positions.map(function (t) { return atScale(t, domain, scale); });
        labels = values.map(function (value) { return fixedCost(value, 6); });
      }
    }

    return positions.map(function (t, index) {
      return { position: t, value: values[index], label: labels[index] };
    });
  }

  function describePoint(point, formatCost, formatScore) {
    var cost = point.cost === null
      ? "cost not reported"
      : "cost $" + point.entry.run_cost_usd + " (shown as " + formatCost(point.entry) + ")";
    var states = [];
    if (point.isFrontier) states.push("on the Pareto frontier");
    if (point.isLeader) states.push("highest score");
    if (point.cost === null) states.push("excluded from Pareto comparison");
    return point.specId + ": score " + formatScore(point.score) + ", " + cost +
      (states.length ? "; " + states.join("; ") : "; dominated");
  }

  function renderMarker(svg, point, x, y, kind, formatScore, formatCost) {
    var group = svgElement("g", "pareto-chart__point");
    group.appendChild(svgElement("title", null, null, describePoint(point, formatCost, formatScore)));
    if (point.isLeader) {
      group.appendChild(svgElement("circle", "pareto-chart__leader-ring", { cx: x, cy: y, r: 10 }));
    }
    if (kind === "frontier") {
      group.appendChild(svgElement("polygon", "pareto-chart__frontier-point", {
        points: [x + "," + (y - 6), (x + 6) + "," + y, x + "," + (y + 6), (x - 6) + "," + y].join(" "),
      }));
    } else {
      group.appendChild(svgElement("circle", "pareto-chart__" + kind + "-point", {
        cx: x,
        cy: y,
        r: kind === "unpriced" ? 5.5 : 5,
      }));
    }
    svg.appendChild(group);
  }

  function renderAxes(svg, model, box, formatScore, formatCost) {
    tickPositions(model.scoreDomain).forEach(function (t) {
      var y = box.top + (1 - t) * box.height;
      var value = atScale(t, model.scoreDomain, "linear");
      svg.appendChild(svgElement("line", "pareto-chart__grid", {
        x1: box.left,
        y1: y,
        x2: box.right,
        y2: y,
      }));
      svg.appendChild(svgElement("text", "pareto-chart__tick pareto-chart__tick--y", {
        x: box.left - 12,
        y: y + 4,
        "text-anchor": "end",
      }, formatScore(value)));
    });
    buildCostTicks(model.costDomain, model.costScale, formatCost).forEach(function (tick) {
      var x = box.left + tick.position * box.width;
      svg.appendChild(svgElement("line", "pareto-chart__tick-mark", {
        x1: x,
        y1: box.bottom,
        x2: x,
        y2: box.bottom + 6,
      }));
      svg.appendChild(svgElement("text", "pareto-chart__tick", {
        x: x,
        y: box.bottom + 24,
        "text-anchor": "middle",
      }, tick.label));
    });
    svg.appendChild(svgElement("line", "pareto-chart__axis", {
      x1: box.left,
      y1: box.bottom,
      x2: box.right,
      y2: box.bottom,
    }));
    svg.appendChild(svgElement("line", "pareto-chart__axis", {
      x1: box.left,
      y1: box.top,
      x2: box.left,
      y2: box.bottom,
    }));
    svg.appendChild(svgElement("text", "pareto-chart__axis-label", {
      x: box.left + box.width / 2,
      y: 412,
      "text-anchor": "middle",
    }, "Run cost USD" + (model.costScale === "log" ? " · log scale" : "")));
    svg.appendChild(svgElement("text", "pareto-chart__axis-label", {
      x: 18,
      y: box.top + box.height / 2,
      transform: "rotate(-90 18 " + (box.top + box.height / 2) + ")",
      "text-anchor": "middle",
    }, "Score"));
  }

  function renderChart(options, model) {
    var hasGutter = model.unpriced.length > 0;
    var box = {
      left: 76,
      right: hasGutter ? 770 : 924,
      top: 28,
      bottom: 350,
    };
    box.width = box.right - box.left;
    box.height = box.bottom - box.top;

    var svg = svgElement("svg", "pareto-chart__svg", {
      viewBox: "0 0 960 430",
      preserveAspectRatio: "xMidYMid meet",
      focusable: "false",
    });
    renderAxes(svg, model, box, options.formatScore, options.formatCost);

    if (model.frontier.length > 1) {
      var vertices = model.frontier.map(function (point) {
        return (box.left + point.x * box.width).toFixed(2) + "," +
          (box.top + (1 - point.y) * box.height).toFixed(2);
      });
      svg.appendChild(svgElement("polyline", "pareto-chart__frontier-line", {
        points: vertices.join(" "),
      }));
    }

    model.priced.forEach(function (point) {
      renderMarker(
        svg,
        point,
        box.left + point.x * box.width,
        box.top + (1 - point.y) * box.height,
        point.isFrontier ? "frontier" : "dominated",
        options.formatScore,
        options.formatCost
      );
    });

    if (hasGutter) {
      var divider = 820;
      var gutterX = 875;
      svg.appendChild(svgElement("line", "pareto-chart__gutter-line", {
        x1: divider,
        y1: box.top,
        x2: divider,
        y2: box.bottom,
      }));
      svg.appendChild(svgElement("text", "pareto-chart__gutter-label", {
        x: gutterX,
        y: box.bottom + 24,
        "text-anchor": "middle",
      }, "Cost n/a"));
      model.unpriced.forEach(function (point) {
        renderMarker(
          svg,
          point,
          gutterX,
          box.top + (1 - point.y) * box.height,
          "unpriced",
          options.formatScore,
          options.formatCost
        );
      });
    }
    return svg;
  }

  function render(options) {
    var model = buildChartModel(options.entries);
    clear(options.container);
    if (!model) {
      options.section.hidden = true;
      if (options.meta) options.meta.textContent = "";
      return null;
    }
    options.container.appendChild(renderChart(options, model));
    if (options.meta) {
      options.meta.textContent = model.priced.length + " priced · " + model.unpriced.length +
        " cost n/a · " + model.costScale + " cost scale.";
    }
    options.section.hidden = false;
    return model;
  }

  return {
    buildChartModel: buildChartModel,
    buildCostTicks: buildCostTicks,
    describePoint: describePoint,
    render: render,
  };
});
