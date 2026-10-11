# Report pagination screenshots

The same synthetic 60-Case report is rendered before and after. Each Case has a short contract-clause prompt, a retained answer and a $0.10 generation observation; the run totals $6.00. This fixture derives from `tests/test_report_browser.py::large_report`, with short text for visual review.

Before: main `4fbdfdce2d4ace85b5fb8411f3cbb69a921fa9d1`, static notebook HTML with all 60 result panes. After: the real `ReportBrowser.widget`, rendered with ipywidgets' HTML embedding at its initial 25-result page. Later-page captures come from setting its actual Case-ID field to `59`, producing the 51–60 page and selecting Case 59.

Headless Chrome, 1200 × 1060 viewport, identical report width. The standalone capture harness loads the notebook icon font. Light and dark output were inspected. DOM interaction verified selection of Case 6 and its $0.1000 Cost view. Kernel-side paging, filtering, exact IDs and async/error behavior are covered by the 42 pagination regressions; screenshots do not replace those checks.
