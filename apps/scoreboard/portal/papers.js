"use strict";
/* About-page evidence carousel: shows one paper at a time beside the intro prose, auto-switching
 * every 3 seconds. Pauses while hovered or keyboard-focused so the image links stay clickable, and
 * never auto-advances under prefers-reduced-motion. Progressive enhancement: without it the strip
 * shows its first paper. (The 1s fade-in on load is pure CSS.)
 */
(function () {
  if (typeof document === "undefined") return;
  var strip = document.querySelector(".about-evidence .papers");
  var track = strip && strip.querySelector(".papers-track");
  var cards = track ? Array.prototype.slice.call(track.children) : [];
  if (cards.length < 2) return;

  var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var idx = 0;
  var timer = 0;

  // Show one paper at a time: slide the track, mark the rest hidden, and keep only the active
  // card's link in the tab order so keyboard users never land on an off-screen paper.
  function show(n) {
    idx = (n % cards.length + cards.length) % cards.length;
    track.style.transform = "translateX(" + -idx * 100 + "%)";
    for (var k = 0; k < cards.length; k++) {
      var off = k !== idx;
      cards[k].setAttribute("aria-hidden", off ? "true" : "false");
      var link = cards[k].querySelector(".paper-card__link");
      if (link) link.tabIndex = off ? -1 : 0;
    }
  }
  function start() {
    if (!reduce && !timer) timer = setInterval(function () { show(idx + 1); }, 3000);
  }
  function stop() {
    if (timer) { clearInterval(timer); timer = 0; }
  }

  show(0);
  start();
  strip.addEventListener("mouseenter", stop);
  strip.addEventListener("mouseleave", start);
  strip.addEventListener("focusin", stop);
  strip.addEventListener("focusout", start);
  cards.forEach(function (card, n) {
    var link = card.querySelector(".paper-card__link");
    if (link) link.addEventListener("focus", function () { show(n); });
  });
})();
