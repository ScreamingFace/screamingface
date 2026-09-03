"""SFDS widget styling for public Leaderboard notebook surfaces."""

from screamingface._ui.style import FUSION_GRADIENT_FLOW, _theme_rules

_LIGHT = (
    "--sf-lb-bg:#fcfdff;--sf-lb-surface:#f4f6f9;--sf-lb-surface-2:#eceef0;"
    "--sf-lb-ink:#3b3c3e;--sf-lb-ink-2:#828386;--sf-lb-ink-3:#b4b6b8;"
    "--sf-lb-line:#cdcfd2;--sf-lb-line-2:#b4b6b8;"
    "--sf-lb-accent:#4b91f0;--sf-lb-accent-hover:#4185de;"
    "--sf-lb-accent-text:#4e85ca;--sf-lb-accent-contrast:#fff"
)
_DARK = (
    "--sf-lb-bg:#05070b;--sf-lb-surface:#0c0f13;--sf-lb-surface-2:#15181c;"
    "--sf-lb-ink:#e0e5eb;--sf-lb-ink-2:#aeb2b8;--sf-lb-ink-3:#585c61;"
    "--sf-lb-line:#35383d;--sf-lb-line-2:#585c61;"
    "--sf-lb-accent:#5a93e0;--sf-lb-accent-hover:#68a0e9;"
    "--sf-lb-accent-text:#87b4f0;--sf-lb-accent-contrast:#fff"
)

# This surface follows the product register in screamingface-brand:
# product-demos/widgets-view/widgets.css and components/style.css. Tokens are
# repeated here so rich notebook output is self-contained and theme-aware.
LEADERBOARD_STYLE = (
    """<style>
.sf-lb{
  __LIGHT__;
  --sf-lb-fusion:__FUSION__;
  max-width:920px;color:var(--sf-lb-ink);background:var(--sf-lb-bg);
  font-family:"IBM Plex Sans",system-ui,-apple-system,"Segoe UI",sans-serif;
  font-size:13px;line-height:1.38;
}
__THEME_RULES__
.sf-lb,.sf-lb *{box-sizing:border-box}
.sf-lb__head{display:flex;flex-direction:column;align-items:flex-start;gap:4px;
  margin-bottom:16px}
.sf-lb__title{margin:0;font-family:"IBM Plex Sans",system-ui,sans-serif;
  font-size:20px;font-weight:600;line-height:1.16;letter-spacing:-.01em;color:var(--sf-lb-ink)}
.sf-lb__controls{display:flex;align-items:baseline;gap:16px;align-self:stretch;margin-top:8px}
.sf-lb__field{display:inline-flex;align-items:baseline;gap:4px;
  border-bottom:1px solid var(--sf-lb-line-2);padding:0 4px 8px}
.sf-lb__field-label{color:var(--sf-lb-ink-2);white-space:nowrap}
.sf-lb__field-value{font-weight:500;color:var(--sf-lb-ink)}
/* OME-832: .sf-lb__checkbox is unused. Its control was removed (OME-820) and
   returns with OME-821, so the rules are kept rather than re-added. This comment
   ships to the reader in page source, hence the brevity. */
.sf-lb__checkbox{display:inline-flex;align-items:center;gap:8px;margin-left:auto;
  color:var(--sf-lb-ink-2);cursor:pointer}
.sf-lb__checkbox input{position:absolute;opacity:0;width:1px;height:1px}
.sf-lb__checkbox-box{width:14px;height:14px;display:inline-flex;align-items:center;
  justify-content:center;border:1px solid var(--sf-lb-line-2);border-radius:0}
.sf-lb__checkbox input:checked+.sf-lb__checkbox-box{background:var(--sf-lb-accent);
  border-color:var(--sf-lb-accent)}
.sf-lb__checkbox input:checked+.sf-lb__checkbox-box::after{content:"✓";
  color:var(--sf-lb-accent-contrast);font:600 10px/1 "IBM Plex Mono",monospace}
.sf-lb__checkbox input:focus-visible+.sf-lb__checkbox-box{outline:1px solid var(--sf-lb-accent);
  outline-offset:1px}
.sf-lb__table{border:1px solid var(--sf-lb-line);border-left:0;
  box-shadow:inset 1px 0 0 var(--sf-lb-line)}
.sf-lb__row{display:grid;grid-template-columns:24px minmax(0,1fr) 72px
  minmax(176px,1.1fr) 72px 64px;gap:12px;align-items:center;padding:8px 12px;
  border-bottom:1px solid var(--sf-lb-line);box-shadow:inset 1px 0 0 var(--sf-lb-line)}
.sf-lb__row:last-child{border-bottom:0}
.sf-lb__row--head{background:var(--sf-lb-surface);font-family:"IBM Plex Mono",
  ui-monospace,monospace;font-size:11px;font-weight:500;text-transform:uppercase;
  letter-spacing:.1em;color:var(--sf-lb-ink-2)}
.sf-lb__sort{color:var(--sf-lb-accent-text)}
.sf-lb__row--winner{box-shadow:inset 2px 0 0 var(--sf-lb-accent)}
.sf-lb__rank,.sf-lb__kind,.sf-lb__questions{color:var(--sf-lb-ink-2)}
.sf-lb__rank,.sf-lb__score-number,.sf-lb__questions{font-family:"IBM Plex Mono",
  ui-monospace,monospace;font-variant-numeric:tabular-nums}
.sf-lb__entry{display:flex;align-items:center;gap:8px;min-width:0}
.sf-lb__icon{flex:0 0 auto;width:18px;text-align:center;color:var(--sf-lb-ink-2);
  filter:grayscale(1);opacity:.8}
.sf-lb__row--winner .sf-lb__icon{color:var(--sf-lb-ink);filter:none;opacity:1}
.sf-lb__entry-name{font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sf-lb__chip{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:12px;
  line-height:1.3;color:var(--sf-lb-ink-2);border:1px solid var(--sf-lb-line-2);
  padding:0 8px;text-transform:lowercase;white-space:nowrap}
.sf-lb__score{display:flex;align-items:center;gap:8px}
.sf-lb__score-number{flex:0 0 36px}
.sf-lb__score-track{flex:1 1 auto;height:6px;background:var(--sf-lb-line);overflow:hidden}
.sf-lb__score-fill{display:block;height:100%;background:var(--sf-lb-ink-2)}
.sf-lb__score-fill--gradient{background:var(--sf-lb-fusion) 0 0/200% 100%;
  animation:sf-lb-flow 14s linear infinite}
.sf-lb__score-fill--accent{background:var(--sf-lb-accent)}
@keyframes sf-lb-flow{to{background-position:200% 0}}
@media(prefers-reduced-motion:reduce){.sf-lb__score-fill--gradient{animation:none}}
.sf-lb__action{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:13px;
  font-weight:500;text-align:center}
.sf-lb__button,.sf-lb__source{display:inline-flex;align-items:center;justify-content:center;
  min-width:56px;padding:4px 8px;border:1px solid var(--sf-lb-line-2);border-radius:0;
  background:transparent;color:var(--sf-lb-ink-2);font:500 13px/1.2 "IBM Plex Mono",
  ui-monospace,monospace;text-decoration:none;cursor:pointer}
.sf-lb__button:hover,.sf-lb__source:hover{background:var(--sf-lb-surface);color:var(--sf-lb-ink)}
.sf-lb__row--winner .sf-lb__button{background:var(--sf-lb-accent);
  border-color:var(--sf-lb-accent);color:var(--sf-lb-accent-contrast)}
.sf-lb__row--winner .sf-lb__button:hover{background:var(--sf-lb-accent-hover)}
.sf-lb__foot{display:flex;align-items:center;gap:8px;margin-top:16px;padding-top:12px;
  border-top:1px solid var(--sf-lb-line);font-family:"IBM Plex Mono",ui-monospace,monospace;
  font-size:12px;color:var(--sf-lb-ink-2)}
.sf-lb__tag{border:1px solid var(--sf-lb-line-2);padding:1px 8px;white-space:nowrap}
.sf-lb__empty{padding:24px;text-align:center;color:var(--sf-lb-ink-2);
  font-family:"IBM Plex Mono",ui-monospace,monospace}
.sf-lb-list{border:1px solid var(--sf-lb-line);background:var(--sf-lb-bg)}
.sf-lb-list__head{display:flex;align-items:baseline;gap:12px;padding:16px 20px;
  border-bottom:1px solid var(--sf-lb-line)}
.sf-lb-list__count{margin-left:auto;color:var(--sf-lb-ink-2);font-family:"IBM Plex Mono",
  ui-monospace,monospace;font-size:12px}
.sf-lb-list__filter{display:flex;align-items:baseline;gap:4px;margin:12px 20px;
  border-bottom:1px solid var(--sf-lb-line-2)}
.sf-lb-list__filter-label{color:var(--sf-lb-ink-2);padding-left:4px}
.sf-lb-list__filter input{flex:1 1 auto;min-width:0;height:30px;padding:0 4px 8px;
  border:0;border-radius:0;outline:0;background:transparent;color:var(--sf-lb-ink);
  font:500 13px/1.38 "IBM Plex Sans",system-ui,sans-serif}
.sf-lb-list__filter:focus-within{border-color:var(--sf-lb-accent)}
.sf-lb-list__rows{border-top:1px solid var(--sf-lb-line)}
.sf-lb-list__row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:12px;
  align-items:start;padding:12px 20px;border-bottom:1px solid var(--sf-lb-line)}
.sf-lb-list__row:last-child{border-bottom:0}
.sf-lb-list__name{font-weight:600;color:var(--sf-lb-ink)}
.sf-lb-list__description{margin-top:4px;color:var(--sf-lb-ink-2)}
.sf-lb-list__meta{display:flex;align-items:center;justify-content:flex-end;gap:8px;
  color:var(--sf-lb-ink-2);font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:12px}
.sf-lb-list__call{margin-top:6px;color:var(--sf-lb-ink-2);font-family:"IBM Plex Mono",
  ui-monospace,monospace;font-size:12px}
.sf-lb-list>.sf-lb__foot{margin:0 20px 16px}
@media(max-width:680px){
  .sf-lb__row{grid-template-columns:24px minmax(0,1fr) minmax(112px,1fr) 64px}
  .sf-lb__kind,.sf-lb__questions{display:none}
  .sf-lb__controls{flex-wrap:wrap}.sf-lb__checkbox{margin-left:0}
  .sf-lb-list__row{grid-template-columns:1fr}.sf-lb-list__meta{justify-content:flex-start}
}
</style>""".replace("__LIGHT__", _LIGHT)
    .replace("__THEME_RULES__", _theme_rules(".sf-lb", _LIGHT, _DARK))
    .replace("__FUSION__", FUSION_GRADIENT_FLOW)
)

__all__: list[str] = []
