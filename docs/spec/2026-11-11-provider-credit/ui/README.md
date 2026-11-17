# Notebook credit preview

Owner-reviewed screenshots from an actual JupyterLab notebook with fixture data.
No live keys or personal balances appear in these images.

- `desktop-light.png`: 1280px desktop, light theme.
- `desktop-dark.png`: 1280px desktop, dark theme.
- `mobile-dark.png`: 390px mobile, dark theme.

Both themes were checked at both widths. Account credit is the primary amount;
key spending allowance is separate. Hosted users see one allowance. Other preview
states cover missing management credentials, stale values, and zero credit.
The visible-card five-minute refresh, hidden-tab pause, and cleanup were checked
in the browser and in `tests/credit_refresh.test.mjs`.
