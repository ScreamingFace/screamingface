/* Email subscribe forms for the leaderboard portal.
 *
 * Two scopes share one HubSpot form:
 *   - "board": updates for one leaderboard (a board page, `benchmark.html?id=<id>`).
 *   - "all":   updates about ScreamingFace as a whole.
 * Each submission records which board it is for, where on the page the form sat, the page it was
 * sent from and the UTM tags on the URL, so the list can be split by any of them later.
 *
 * The browser posts straight to HubSpot's public form endpoint. While FORM_ID is empty the form
 * runs dry: it validates and shows its states, and sends nothing.
 *
 * Loaded as a plain <script> in the browser (exposing window.SFSubscribe) and via require() in
 * tests, the same shape as leaderboard-logic.js. No build step.
 */
(function (root, factory) {
  "use strict";
  var api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else {
    root.SFSubscribe = api;
    api.install(root);
  }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  var PORTAL_ID = "6487402";
  var FORM_ID = "ae29bac7-8744-4874-ba34-3ff6ed3cd7f4"; // empty = dry run
  var SUBSCRIPTION_ALL = 3829230650; // HubSpot subscription type id: ScreamingFace updates
  var SUBSCRIPTION_BOARD = 3829230898; // HubSpot subscription type id: leaderboard alerts
  var CONTACT = "0-1";
  var UTM_KEYS = ["utm_source", "utm_medium", "utm_campaign", "utm_content"];
  var SCOPE_ALL = "all";
  var STORE_KEY = "sf_subscribed";
  var EVENT_SUBSCRIBE = "Subscribe";

  function isValidEmail(value) {
    return /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(String(value || "").trim());
  }

  // The words a form shows. `boardName` is only used for the "board" scope.
  function copyFor(scope, boardName) {
    if (scope === SCOPE_ALL) {
      return {
        heading: "ScreamingFace updates",
        body: "New results and news, about once a week.",
        button: "Subscribe",
        done: "You're subscribed to ScreamingFace updates.",
      };
    }
    return {
      heading: "Follow " + boardName,
      body: "We'll email you when the top of this board changes.",
      button: "Follow this board",
      done: "You're following " + boardName + ".",
    };
  }

  function field(name, value) {
    return { objectTypeId: CONTACT, name: name, value: value };
  }

  function communication(id, text) {
    return { value: true, subscriptionTypeId: id, text: text };
  }

  // Which lists this submission opts into. A board form opts into the general list only when the
  // "also send me news" box is ticked.
  function communications(scope, alsoAll, ids) {
    var out = [];
    if (scope !== SCOPE_ALL && ids.board) out.push(communication(ids.board, "Leaderboard alerts"));
    if ((scope === SCOPE_ALL || alsoAll) && ids.all) out.push(communication(ids.all, "ScreamingFace updates"));
    return out;
  }

  // The HubSpot Forms v3 body for one submission.
  function buildSubmission(input, ids) {
    var scope = input.board ? input.board : SCOPE_ALL;
    var params = new URLSearchParams(input.search || "");
    var fields = [
      field("email", String(input.email || "").trim()),
      field("sf_subscribe_board", scope),
      field("sf_subscribe_placement", input.placement || "unknown"),
    ];
    if (scope !== SCOPE_ALL) fields.push(field("sf_subscribe_all", input.alsoAll ? "true" : "false"));
    UTM_KEYS.forEach(function (key) {
      var value = params.get(key);
      if (value) fields.push(field(key, value));
    });
    var context = {
      pageUri: input.pageUri || "",
      pageName: scope === SCOPE_ALL ? "leaderboard: all" : "leaderboard: " + scope,
    };
    if (input.hutk) context.hutk = input.hutk;
    return {
      fields: fields,
      context: context,
      legalConsentOptions: {
        consent: {
          consentToProcess: true,
          text: "I agree to receive these emails from ScreamingFace.",
          communications: communications(scope, !!input.alsoAll, ids || {}),
        },
      },
    };
  }

  /* ---- browser ---------------------------------------------------------- */

  function el(doc, tag, className, text) {
    var node = doc.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function cookie(doc, name) {
    var match = new RegExp("(?:^|; )" + name + "=([^;]*)").exec(doc.cookie || "");
    return match ? decodeURIComponent(match[1]) : "";
  }

  function remembered(root) {
    try {
      return JSON.parse(root.localStorage.getItem(STORE_KEY) || "[]");
    } catch (e) {
      return [];
    }
  }

  function remember(root, scope) {
    try {
      var seen = remembered(root);
      if (seen.indexOf(scope) === -1) seen.push(scope);
      root.localStorage.setItem(STORE_KEY, JSON.stringify(seen));
    } catch (e) {
      /* storage unavailable, ignore */
    }
  }

  function send(root, body) {
    if (!FORM_ID) return Promise.resolve();
    var url = "https://api.hsforms.com/submissions/v3/integration/submit/" + PORTAL_ID + "/" + FORM_ID;
    return root
      .fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
      .then(function (response) {
        if (!response.ok) throw new Error("subscribe failed: " + response.status);
      });
  }

  function track(root, scope, placement) {
    try {
      if (typeof root.plausible !== "function") return;
      root.plausible(EVENT_SUBSCRIBE, { props: { scope: scope === SCOPE_ALL ? SCOPE_ALL : "board", placement: placement } });
    } catch (e) {
      /* analytics unavailable, ignore */
    }
  }

  // One form. `opts`: scope ("all" or a board id), boardName, placement.
  function renderForm(root, mount, opts) {
    var doc = root.document;
    var copy = copyFor(opts.scope, opts.boardName);
    var isBoard = opts.scope !== SCOPE_ALL;
    var uid = "subscribe-" + opts.placement;

    while (mount.firstChild) mount.removeChild(mount.firstChild);
    mount.className = "subscribe";
    mount.id = mount.id || uid;

    var text = el(doc, "div", "subscribe-text");
    text.appendChild(el(doc, "h2", "subscribe-heading", copy.heading));
    text.appendChild(el(doc, "p", "subscribe-body", copy.body));
    mount.appendChild(text);

    var status = el(doc, "p", "subscribe-status");
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");

    if (remembered(root).indexOf(opts.scope) !== -1) {
      status.textContent = copy.done;
      status.classList.add("is-done");
      mount.appendChild(status);
      return;
    }

    var form = el(doc, "form", "subscribe-form");
    form.noValidate = true;

    var row = el(doc, "div", "signup subscribe-row");
    var label = el(doc, "label", "sr-only", "Email address");
    label.setAttribute("for", uid + "-email");
    var input = el(doc, "input");
    input.type = "email";
    input.id = uid + "-email";
    input.name = "email";
    input.autocomplete = "email";
    input.placeholder = "you@lab.org";
    input.required = true;
    var button = el(doc, "button", "btn--primary", copy.button);
    button.type = "submit";
    row.appendChild(label);
    row.appendChild(input);
    row.appendChild(button);
    form.appendChild(row);

    // Bots fill every field; people never see this one.
    var trap = el(doc, "input", "subscribe-trap");
    trap.type = "text";
    trap.name = "company";
    trap.tabIndex = -1;
    trap.autocomplete = "off";
    trap.setAttribute("aria-hidden", "true");
    form.appendChild(trap);

    var also = null;
    if (isBoard) {
      var check = el(doc, "label", "checkbox subscribe-also");
      also = el(doc, "input");
      also.type = "checkbox";
      also.name = "also_all";
      check.appendChild(also);
      check.appendChild(el(doc, "span", "checkbox-box"));
      check.appendChild(el(doc, "span", "subscribe-also-label", "Also send me ScreamingFace news"));
      form.appendChild(check);
    }

    form.appendChild(status);
    form.appendChild(el(doc, "p", "subscribe-fine", "Unsubscribe any time."));
    mount.appendChild(form);

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      status.classList.remove("is-error");
      if (!isValidEmail(input.value)) {
        status.textContent = "Enter a valid email address.";
        status.classList.add("is-error");
        input.classList.add("err");
        input.focus();
        return;
      }
      input.classList.remove("err");
      if (trap.value) return;
      button.disabled = true;
      status.textContent = "Sending…";
      var body = buildSubmission(
        {
          email: input.value,
          board: isBoard ? opts.scope : null,
          placement: opts.placement,
          alsoAll: !!(also && also.checked),
          search: root.location.search,
          pageUri: root.location.href,
          hutk: cookie(doc, "hubspotutk"),
        },
        { all: SUBSCRIPTION_ALL, board: SUBSCRIPTION_BOARD }
      );
      send(root, body).then(
        function () {
          remember(root, opts.scope);
          if (also && also.checked) remember(root, SCOPE_ALL);
          track(root, opts.scope, opts.placement);
          form.hidden = true;
          mount.appendChild(status);
          status.textContent = also && also.checked ? copy.done + " You will get ScreamingFace news too." : copy.done;
          status.classList.add("is-done");
        },
        function () {
          button.disabled = false;
          status.textContent = "That didn't go through. Try again in a moment.";
          status.classList.add("is-error");
        }
      );
    });
  }

  function boardId(root) {
    return new URLSearchParams(root.location.search || "").get("id") || null;
  }

  // The board form lives under the title: a "Follow this board" button opens it in place.
  function mountBoard(root, id, name) {
    var doc = root.document;
    var masthead = doc.querySelector(".masthead");
    if (!masthead) return;

    var old = doc.getElementById("subscribe-follow");
    if (old) old.parentNode.removeChild(old);
    var follow = el(doc, "button", "btn--primary sm subscribe-follow", "Follow this board");
    follow.type = "button";
    follow.id = "subscribe-follow";
    masthead.appendChild(follow);

    var panel = doc.getElementById("subscribe-panel") || el(doc, "div");
    panel.id = "subscribe-panel";
    panel.setAttribute("data-section", "subscribe");
    masthead.parentNode.insertBefore(panel, masthead.nextSibling);
    renderForm(root, panel, { scope: id, boardName: name, placement: "board-header" });
    panel.hidden = true;
    follow.setAttribute("aria-expanded", "false");
    follow.setAttribute("aria-controls", panel.id);
    follow.onclick = function () {
      panel.hidden = !panel.hidden;
      follow.setAttribute("aria-expanded", String(!panel.hidden));
      var field = panel.querySelector("input[type=email]");
      if (!panel.hidden && field) field.focus();
    };
  }

  function install(root) {
    try {
      var doc = root.document;
      var start = function () {
        var id = boardId(root);
        var band = doc.querySelector('[data-subscribe="all"]');
        if (band) renderForm(root, band, { scope: SCOPE_ALL, placement: "site-band" });

        var title = doc.getElementById("benchmark-name");
        if (!id || !title) return;
        var shown = "";
        var named = function () {
          var name = (title.textContent || "").trim();
          if (!name || name === "Leaderboard" || name === shown) return;
          shown = name;
          mountBoard(root, id, name);
        };
        named();
        new root.MutationObserver(named).observe(title, { childList: true, characterData: true, subtree: true });
      };
      if (doc.readyState === "loading") doc.addEventListener("DOMContentLoaded", start);
      else start();
    } catch (e) {
      /* subscribe unavailable, ignore */
    }
  }

  return {
    EVENT_SUBSCRIBE: EVENT_SUBSCRIBE,
    isValidEmail: isValidEmail,
    copyFor: copyFor,
    buildSubmission: buildSubmission,
    install: install,
  };
});
