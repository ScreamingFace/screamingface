/* Score/cost Pareto chart for the public benchmark board.
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
    var range = high - low;
    if (isFinite(range)) return (value - low) / range;
    // WHY halves: two finite extremes (-1e308 and 1e308) overflow their difference to Infinity.
    // Halving every term first keeps each subtraction finite and gives the same ratio.
    return (value / 2 - low / 2) / (high / 2 - low / 2);
  }

  function sourcePoint(entry, leaderScore) {
    var cost = L.costNumber(entry);
    return {
      entry: entry,
      specId: String(entry.spec_id || "Unnamed submission"),
      score: entry.score,
      cost: cost !== null && cost >= 0 ? cost : null,
      isFrontier: false,
      isLeader: entry.score === leaderScore,
      x: 0,
      y: 0,
    };
  }

  var NICE_MANTISSAS = [1, 2, 2.5, 5];
  var MAX_SCORE_TICKS = 6;
  // A round label sits anywhere up the axis, including level with the vertically centred
  // "Score" title, and past six characters it reaches that title. Longer names go to the
  // endpoint fallback, whose two labels sit at the top and bottom, clear of the title.
  var MAX_TICK_LABEL = 6;
  // Past this many decimals a round label is longer than MAX_TICK_LABEL anyway, and toFixed
  // throws beyond 100, so the search stops here instead of computing it.
  var MAX_TICK_DECIMALS = 20;

  // WHY round ticks: quarter positions over the raw data range produced labels like
  // "0.515175" (which ran into the rotated "Score" title) and, once rounded, labels that could
  // repeat on a low-scoring board. The axis instead climbs in a 1/2/2.5/5 x 10^k step, picks the
  // smallest such step that needs at most six ticks, and extends the top to the next multiple of
  // it. Each label carries exactly the decimals the step needs, so every label is exact and none
  // repeat. The floor stays where the data puts it (0, or the lowest negative score); only
  // multiples of the step inside the axis are labelled.
  // Returns null when no round step fits; buildScoreTicks then falls back to the endpoints.
  function niceStep(low, high) {
    var range = high - low;
    if (!isFinite(range) || range <= 0) return null;
    var start = Math.floor(Math.log10(range)) - 2;
    for (var exponent = start; exponent <= start + 4; exponent += 1) {
      for (var i = 0; i < NICE_MANTISSAS.length; i += 1) {
        var mantissa = NICE_MANTISSAS[i];
        var decimals = Math.max(0, -exponent + (mantissa === 2.5 ? 1 : 0));
        if (decimals > MAX_TICK_DECIMALS) return null;
        var step = Number((mantissa * Math.pow(10, exponent)).toFixed(decimals));
        if (!(step > 0) || !isFinite(step)) continue;
        var first = Math.ceil(Number((low / step).toFixed(9)));
        var last = Math.ceil(Number((high / step).toFixed(9)));
        // WHY: the axis top must cover the highest score. Rounding high/step to nine decimals
        // can land one step short (0.6000000001 / 0.2 -> 3), so step up once when it does.
        if (Number((last * step).toFixed(decimals)) < high) last += 1;
        if (last - first + 1 <= MAX_SCORE_TICKS) {
          return { step: step, decimals: decimals, first: first, last: last };
        }
      }
    }
    return null;
  }

  function niceAxis(low, high) {
    var nice = niceStep(low, high);
    if (!nice) return null;
    var top = Number((nice.last * nice.step).toFixed(nice.decimals));
    var ticks = [];
    for (var k = nice.first; k <= nice.last; k += 1) {
      var value = Number((k * nice.step).toFixed(nice.decimals));
      ticks.push({
        position: normalize(value, low, top, false),
        value: value,
        // `+ 0` folds a computed -0 into 0 so the zero tick never reads "-0.0".
        label: (value + 0).toFixed(nice.decimals),
      });
    }
    return { domain: [low, top], ticks: ticks };
  }

  function axisIsSafe(axis, high) {
    var top = axis.domain[1];
    if (!isFinite(axis.domain[0]) || !isFinite(top) || top < high) return false;
    var labels = axis.ticks.map(function (tick) { return tick.label; });
    return axis.ticks.length >= 2 && allUnique(labels) && axis.ticks.every(function (tick) {
      return isFinite(tick.value) && isFinite(Number(tick.label)) &&
        tick.label.length <= MAX_TICK_LABEL &&
        isFinite(tick.position) && tick.position >= 0 && tick.position <= 1;
    });
  }

  // Scientific form with `digits` significant figures and no "+" in the exponent, so the label
  // stays short: 1e-101 -> "1.0e-101", 1e308 -> "1.0e308".
  function shortNumber(value, digits) {
    if (value === 0) return "0";
    var parts = value.toExponential(digits - 1).split("e");
    var label = parts[0] + "e" + Number(parts[1]);
    if (isFinite(Number(label))) return label;
    // Rounding up past the largest double (1.797e308 -> "1.8e308") would read back as
    // Infinity, so truncate the mantissa toward zero instead ("1.7e308").
    var unit = Math.pow(10, digits - 1);
    var full = Number(value.toExponential(16).split("e")[0]);
    var mantissa = Math.trunc(full * unit) / unit;
    return mantissa.toFixed(digits - 1) + "e" + Number(parts[1]);
  }

  // WHY a fallback: scores are any finite float, and for tiny or extreme ranges no round step
  // gives short, finite labels (toFixed throws past 100 decimals; 1e308 - -1e308 overflows). The
  // axis then names just its two ends, the floor and the highest score, in short scientific
  // form, adding significant figures only until the two labels differ.
  function endpointAxis(low, high) {
    var labels;
    for (var digits = 2; digits <= 17; digits += 1) {
      labels = [shortNumber(low, digits), shortNumber(high, digits)];
      if (labels[0] !== labels[1]) break;
    }
    return {
      domain: [low, high],
      ticks: [
        { position: 0, value: low, label: labels[0] },
        { position: 1, value: high, label: labels[1] },
      ],
    };
  }

  // A single-value board has one mid-axis tick, so its label is kept brief too.
  function briefLabel(value) {
    var plain = String(value);
    if (plain.length <= MAX_TICK_LABEL) return plain;
    var rounded = value.toPrecision(3);
    if (rounded.length <= MAX_TICK_LABEL && isFinite(Number(rounded))) return rounded;
    return shortNumber(value, 2);
  }

  function buildScoreTicks(low, high) {
    if (low === high) {
      return { domain: [low, high], ticks: [{ position: 0.5, value: low, label: briefLabel(low) }] };
    }
    var axis = niceAxis(low, high);
    return axis && axisIsSafe(axis, high) ? axis : endpointAxis(low, high);
  }

  // One model feeds every visual element in the chart. Membership is never recomputed here:
  // the table mark is a whole-board server
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

    // Anchor the axes at the origin so each point reads against a true zero, not a zoomed-in
    // window of the data (a board scoring [0.4, 0.8] framed its own floor at 0.4). Score floor is
    // min(0, lowest) so a board whose scores go negative (HealthBench worst-30) still shows every
    // point instead of being cropped at 0. Cost is never negative, so a linear axis floors at 0; a
    // log axis keeps its own positive minimum, because zero has no logarithm — and that scale only
    // engages when costMin > 0, so the two never collide.
    var scoreFloor = Math.min(0, scoreMin);
    var costFloor = logarithmic ? costMin : 0;
    var scoreAxis = buildScoreTicks(scoreFloor, scoreMax);
    var scoreTop = scoreAxis.domain[1];

    var priced = pricedSources.map(function (point) {
      return {
        entry: point.entry,
        specId: point.specId,
        score: point.score,
        cost: point.cost,
        isFrontier: L.isParetoMarked(point.entry),
        isLeader: point.isLeader,
        x: normalize(point.cost, costFloor, costMax, logarithmic),
        y: normalize(point.score, scoreFloor, scoreTop, false),
      };
    });
    var unpriced = sources
      .filter(function (point) { return point.cost === null; })
      .map(function (point) {
        point.y = normalize(point.score, scoreFloor, scoreTop, false);
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
      costDomain: [costFloor, costMax],
      scoreDomain: scoreAxis.domain,
      scoreTicks: scoreAxis.ticks,
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
      (states.length ? "; " + states.join("; ") : "; not on the Pareto frontier");
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

  function renderAxes(svg, model, box, formatCost) {
    model.scoreTicks.forEach(function (tick) {
      var y = box.top + (1 - tick.position) * box.height;
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
      }, tick.label));
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
    renderAxes(svg, model, box, options.formatCost);

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
    buildScoreTicks: buildScoreTicks,
    render: render,
  };
});
