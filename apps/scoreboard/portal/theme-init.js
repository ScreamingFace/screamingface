/* WHY: select the theme before paint on every portal entry point. The vendored
   theme.js owns the toggle and writes only an explicit visitor choice. */
(function () {
  "use strict";
  var theme;
  try { theme = localStorage.getItem("sf_theme"); } catch (_) {}
  if (theme !== "light" && theme !== "dark") {
    theme = window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  document.documentElement.setAttribute("data-theme", theme);
})();
