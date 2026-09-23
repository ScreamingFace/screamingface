"""Styles shared by ScreamingFace notebook cards and catalogues."""

from __future__ import annotations

from screamingface._ui.style import STYLE

# WHY: the gold-to-blue signature belongs only to compositional/Fusion surfaces.
CARD_STYLE = (
    STYLE
    + """<style>
.sf-ui{--sf-gain-grad:linear-gradient(100deg,#d08511 0%,#e7a105 16%,#dbb13b 40%,
  #8e9dab 60%,#9fb8f8 80%,#346cf9 100%)}
.sf-card,.sf-catalog{border:1px solid var(--sf-line-2);background:var(--sf-bg)}
.sf-card__accent{height:3px;background:var(--sf-gain-grad)}
.sf-card__accent--solid{background:var(--sf-gain)}
.sf-card__accent--pipeline{background:var(--sf-accent)}
.sf-card__head{display:flex;align-items:baseline;gap:8px;padding:12px;
  border-bottom:1px solid var(--sf-line)}
.sf-card__title,.sf-catalog__title{font-size:15px;font-weight:600;color:var(--sf-ink);
  overflow-wrap:anywhere}
.sf-card__kicker{margin-left:auto;font-family:"IBM Plex Mono",ui-monospace,monospace;
  font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--sf-gain)}
.sf-card__kicker--pipeline{color:var(--sf-accent)}
.sf-card__grid{display:grid;grid-template-columns:1fr 1fr;gap:1px;background:var(--sf-line)}
.sf-card__field{background:var(--sf-bg);padding:8px 12px;min-width:0}
.sf-card__field.wide{grid-column:1/-1}
.sf-card__k,.sf-label{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:10px;
  letter-spacing:.08em;text-transform:uppercase;color:var(--sf-ink-3)}
.sf-card__v{margin-top:2px;overflow-wrap:anywhere}.sf-card__hint{color:var(--sf-ink-3)}
.sf-mono{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:12px}
.sf-section{border-top:1px solid var(--sf-line);padding:9px 12px}
.sf-section__title{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:10px;
  letter-spacing:.08em;text-transform:uppercase;color:var(--sf-ink-3);margin-bottom:6px}
.sf-detail__item{border-left:2px solid var(--sf-line-2);padding:2px 0 6px 10px;margin-top:6px}
.sf-detail__name{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:12px;
  font-weight:600;color:var(--sf-gain)}
.sf-detail__index{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:10px;
  letter-spacing:.08em;text-transform:uppercase;color:var(--sf-ink-3)}
.sf-detail__route,.sf-detail__params{font-family:"IBM Plex Mono",ui-monospace,monospace;
  font-size:11px;color:var(--sf-ink-2);overflow-wrap:anywhere}
.sf-more__full{margin-top:4px;white-space:pre-wrap;overflow-wrap:anywhere;
  background:var(--sf-surface);padding:6px 8px;font-size:12px;color:var(--sf-ink-2)}
.sf-summary{cursor:pointer;display:flex;align-items:center;gap:8px;list-style:none}
.sf-summary::-webkit-details-marker{display:none}.sf-summary::before{content:'▸';
  color:var(--sf-ink-3);font-size:10px}
details[open]>.sf-summary::before{content:'▾'}
.sf-chips,.sf-pills{display:flex;flex-wrap:wrap;gap:6px}
.sf-chip,.sf-pill{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:11px;
  color:var(--sf-ink-2);border:1px solid var(--sf-line-2);padding:1px 8px;
  background:transparent}
.sf-meta{display:flex;gap:18px;flex-wrap:wrap;padding:10px 12px}
.sf-meta__item{display:grid;gap:2px}
.sf-card table{border-collapse:collapse;width:100%;font-size:13px}
.sf-card th,.sf-card td{text-align:left;padding:7px 9px;border-top:1px solid var(--sf-line)}
.sf-card th{color:var(--sf-ink-2);font-weight:600}
.sf-dag{overflow-x:auto;padding:8px 12px}.sf-node{fill:var(--sf-surface);stroke:var(--sf-gain);
  stroke-width:1.5}.sf-node-title{font:600 12px "IBM Plex Sans",sans-serif;fill:var(--sf-ink)}
.sf-node-kind{font:10px "IBM Plex Mono",monospace;fill:var(--sf-ink-3)}
.sf-edge{stroke:var(--sf-line-2);stroke-width:1.4;fill:none}
.sf-catalog-widget.widget-vbox{border:0!important;box-shadow:none!important}
.sf-catalog__head{display:flex;align-items:center;gap:8px;height:44px;padding:0 12px;
  border-bottom:1px solid var(--sf-line-2)}
.sf-catalog__title{font-size:13px}.sf-catalog__count{margin-left:auto;
  font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:11px;color:var(--sf-ink-3)}
.sf-catalog__row{display:grid;grid-template-columns:minmax(0,2fr) minmax(180px,1fr);
  gap:12px;align-items:center;padding:8px 12px;border-bottom:1px solid var(--sf-line)}
.sf-catalog__row:last-child{border-bottom:0}.sf-catalog__id{font-family:"IBM Plex Mono",
  ui-monospace,monospace;font-size:12px;font-weight:600;overflow-wrap:anywhere;
  color:var(--sf-ink)}
.sf-catalog__row--case{grid-template-columns:auto minmax(0,1fr);align-items:start}
.sf-catalog__row--case .sf-catalog__tags{justify-content:flex-start}
.sf-catalog__row--case .sf-card__hint{margin:0}
.sf-catalog__sub{color:var(--sf-ink-2)}
.sf-catalog__tags{display:flex;flex-wrap:wrap;gap:4px;justify-content:flex-end}
.sf-catalog__empty{padding:16px 12px;color:var(--sf-ink-3);text-align:center;
  font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:12px}
.sf-catalog-widget .widget-text{width:auto!important;margin:8px 12px!important}
.sf-catalog-widget .widget-text input{border-radius:0!important;box-shadow:none!important;
  height:32px!important;padding:0 8px!important;border:1px solid var(--sf-line-2)!important;
  background:var(--sf-bg)!important;color:var(--sf-ink)!important;
  font:12px/1 "IBM Plex Mono",ui-monospace,monospace!important}
.sf-catalog-widget .sf-catalog__scroll{max-height:min(70vh,880px);overflow-y:auto;
  border-top:1px solid var(--sf-line)}
.sf-catalog-widget .widget-toggle-buttons{margin:0 12px 4px}
.sf-catalog-widget .widget-toggle-buttons .widget-label{width:auto!important;
  font:10px/1 "IBM Plex Mono",ui-monospace,monospace!important;letter-spacing:.08em;
  text-transform:uppercase;color:var(--sf-ink-3)!important}
.sf-catalog-widget .jupyter-button.widget-toggle-button{border-radius:0!important;
  box-shadow:none!important;height:24px!important;margin-right:-1px;
  width:auto!important;padding:0 10px!important;
  border:1px solid var(--sf-line-2)!important;background:transparent!important;
  color:var(--sf-ink-2)!important;font:11px/1 "IBM Plex Mono",ui-monospace,monospace!important}
.sf-catalog-widget .jupyter-button.widget-toggle-button.mod-active{
  color:var(--sf-bg)!important;border-color:var(--sf-accent)!important;
  background:var(--sf-accent)!important;position:relative;z-index:1}
.sf-url4{border-top:1px solid var(--sf-line);padding:8px 12px;min-width:0}
.sf-url4__copy{margin-left:auto;cursor:pointer;border-radius:0;border:1px solid var(--sf-line-2);
  background:var(--sf-bg);color:var(--sf-ink-2);padding:2px 8px;
  font:11px/1 "IBM Plex Mono",ui-monospace,monospace}
.sf-url4__pre{margin:8px 0 0;padding:8px;background:var(--sf-surface);
  border:1px solid var(--sf-line);color:var(--sf-ink);
  font:11px/1.5 "IBM Plex Mono",ui-monospace,monospace;white-space:pre-wrap;
  overflow-wrap:anywhere;tab-size:2}
@media(max-width:620px){.sf-card__grid,.sf-catalog__row{grid-template-columns:1fr}
  .sf-catalog__tags{justify-content:flex-start}}
</style>"""
)

__all__: list[str] = []
