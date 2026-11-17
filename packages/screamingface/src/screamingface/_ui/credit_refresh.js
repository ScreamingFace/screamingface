// FEATURE: credit polling exists only while this notebook card is visible.
function render({model, el}) {
  el.setAttribute("aria-hidden", "true");
  let target = null;
  let visible = false, busy = false, closed = false, timer = null;
  const cancel = () => { if (timer !== null) clearTimeout(timer); timer = null; };
  const active = () => !closed && model.get("active") && visible &&
    document.visibilityState === "visible" && target?.isConnected;
  const request = () => {
    cancel();
    if (!active() || busy) return;
    busy = true;
    model.send({type: "refresh"});
  };
  const schedule = () => {
    cancel();
    if (active() && !busy) timer = setTimeout(request, 300000);
  };
  const acknowledge = (message) => {
    if (message?.type !== "refreshed") return;
    busy = false;
    schedule();
  };
  const visibility = () => { if (active()) request(); else cancel(); };
  const observer = new IntersectionObserver((entries) => {
    visible = entries.some(entry => entry.isIntersecting);
    visibility();
  });
  // WHY: notebook managers can render children before attaching their parent card.
  const attach = () => {
    if (!el.isConnected || closed) return;
    target = el.closest(".sf-connection-widget") || el;
    observer.observe(target);
    mount.disconnect();
  };
  const mount = new MutationObserver(attach);
  mount.observe(document.documentElement, {childList: true, subtree: true});
  attach();
  document.addEventListener("visibilitychange", visibility);
  model.on("msg:custom", acknowledge);
  model.on("change:active", visibility);
  // INVARIANT: removing the view retires its timer, observer and model callbacks.
  return () => {
    closed = true;
    cancel();
    observer.disconnect();
    mount.disconnect();
    document.removeEventListener("visibilitychange", visibility);
    model.off("msg:custom", acknowledge);
    model.off("change:active", visibility);
  };
}
export default {render};
