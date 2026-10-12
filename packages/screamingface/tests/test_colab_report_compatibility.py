"""Colab preserves supported widgets and receives complete, retryable report downloads."""

import builtins
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from test_report_browser import large_report


def colab_host(monkeypatch, download):

    shell = type("Shell", (), {"__module__": "google.colab._shell"})()
    monkeypatch.setattr("IPython.core.getipython.get_ipython", lambda: shell)
    enabled = []
    google = ModuleType("google")
    google.__path__ = []
    colab = ModuleType("google.colab")
    files = SimpleNamespace(download=download)
    setattr(colab, "files", files)
    output = SimpleNamespace(enable_custom_widget_manager=lambda: enabled.append(True))
    output.register_callback = lambda name, callback: None
    output.unregister_callback = lambda name: None
    setattr(colab, "output", output)
    setattr(google, "colab", colab)
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.colab", colab)
    monkeypatch.setitem(sys.modules, "google.colab.files", files)
    monkeypatch.setitem(sys.modules, "google.colab.output", output)
    return enabled


@pytest.mark.parametrize(
    ("module", "expected"),
    [
        ("google.colab._shell", True),
        ("IPython.core.interactiveshell", False),
        ("google.colab_fake", False),
        (None, False),
    ],
)
def test_active_shell_identifies_colab_without_package_presence(monkeypatch, module, expected):
    from screamingface._ui.notebook_host import in_colab

    shell = None if module is None else type("Shell", (), {"__module__": module})()
    monkeypatch.setattr("IPython.core.getipython.get_ipython", lambda: shell)
    assert in_colab() is expected


def test_no_ipython_is_an_ordinary_python_host(monkeypatch):
    from screamingface._ui.notebook_host import in_colab

    original = builtins.__import__

    def without_ipython(name, *args, **kwargs):
        if name.startswith("IPython"):
            raise ImportError("no notebook runtime")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_ipython)
    assert not in_colab()


def test_non_colab_never_imports_google_helpers(monkeypatch, tmp_path):
    from screamingface._ui.notebook_host import download_in_colab, prepare_widgets

    monkeypatch.setattr("IPython.core.getipython.get_ipython", lambda: None)
    original = builtins.__import__

    def without_google(name, *args, **kwargs):
        if name.startswith("google.colab"):
            raise AssertionError("Colab helpers do not belong in other hosts")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_google)
    prepare_widgets()
    assert not download_in_colab(tmp_path / "report.json")


def test_colab_prepares_widgets_and_downloads_a_saved_path(monkeypatch, tmp_path):
    from screamingface._ui.notebook_host import download_in_colab, prepare_widgets

    delivered = []
    enabled = colab_host(monkeypatch, delivered.append)
    path = tmp_path / "a report.json"
    path.write_text("{}")
    prepare_widgets()
    assert enabled == [True]
    assert download_in_colab(path)
    assert delivered == [str(path)]


def test_colab_never_advertises_a_jupyter_file_url(monkeypatch, tmp_path):
    from screamingface._ui.report_files import download_link

    colab_host(monkeypatch, lambda path: None)

    def unexpected_server_discovery():
        raise AssertionError("Colab browser cannot reach the kernel's localhost")

    monkeypatch.setattr(
        "jupyter_server.serverapp.list_running_servers", unexpected_server_discovery
    )
    link = download_link(tmp_path / "report.json", "Download")
    assert "saved to" in link and "/files/" not in link


def test_colab_download_button_reuses_complete_snapshot(monkeypatch, tmp_path):
    from screamingface._ui.report_browser import ReportBrowser

    delivered = []
    enabled = colab_host(monkeypatch, delivered.append)
    monkeypatch.chdir(tmp_path)
    source = large_report(60)
    browser = ReportBrowser(source)
    assert enabled == [True]
    browser.export.click()
    assert json.loads(browser.snapshot.read_text()) == source.to_dict()
    assert delivered == [str(browser.snapshot)]
    assert browser.export_slot.children == (browser.export,)
    assert browser.export.description == "Download" and not browser.export.disabled

    def reject_rewrite(*args, **kwargs):
        raise AssertionError("the snapshot is already complete")

    monkeypatch.setattr(type(source), "export", reject_rewrite)
    browser.export.click()
    assert delivered == [str(browser.snapshot)] * 2
    assert not browser._exporting


def test_colab_delivery_failure_retries_without_reexport(monkeypatch, tmp_path):
    from screamingface._ui.report_browser import ReportBrowser

    attempts = []

    def deliver(path):
        attempts.append(path)
        if len(attempts) == 1:
            raise OSError("download unavailable")

    colab_host(monkeypatch, deliver)
    monkeypatch.chdir(tmp_path)
    browser = ReportBrowser(large_report(1))
    browser.export.click()
    assert browser.snapshot.exists()
    assert "download unavailable" in browser.notice.value
    assert not browser.export.disabled and not browser._exporting

    def reject_rewrite(*args, **kwargs):
        raise AssertionError("delivery retry must reuse the exported JSON")

    monkeypatch.setattr(type(browser.report), "export", reject_rewrite)
    browser.export.click()
    assert attempts == [str(browser.snapshot)] * 2
    assert not browser.notice.value


@pytest.mark.asyncio
async def test_colab_kernel_publishes_download_inside_callback_without_duplicate_export(
    monkeypatch, tmp_path
):
    import threading

    from screamingface._ui.report_browser import ReportBrowser

    thread = threading.get_ident()
    deliveries = []
    writes = []

    def deliver(path):
        assert threading.get_ident() == thread
        deliveries.append(json.loads(Path(path).read_text()))

    colab_host(monkeypatch, deliver)
    monkeypatch.chdir(tmp_path)
    source = large_report(60)
    browser = ReportBrowser(source)
    original = type(source).export

    def export(report, path):
        writes.append(path)
        browser.export.click()  # queued duplicate during preparation must do no work
        return original(report, path)

    monkeypatch.setattr(type(source), "export", export)
    browser.export.click()
    # INVARIANT: Colab's comm transport must receive delivery before the callback returns.
    assert deliveries == [source.to_dict()]
    assert len(writes) == 1 and browser._export_task is None
    assert not browser.export.disabled and not browser._exporting
    browser.export.click()
    assert deliveries == [source.to_dict(), source.to_dict()]
    assert len(writes) == 1


@pytest.mark.asyncio
async def test_colab_kernel_publishes_bounded_page_within_callback(monkeypatch, tmp_path):
    from screamingface._ui.report_browser import ReportBrowser

    colab_host(monkeypatch, lambda path: None)
    monkeypatch.chdir(tmp_path)
    browser = ReportBrowser(large_report(60))
    browser.next.click()
    assert browser.count.value == "26–50 of 60"
    assert browser._page_task is None and not browser._paging
    assert "answer 25" in browser.cases.value
    browser.go_to.value = "59"
    assert browser.count.value == "51–60 of 60"
    assert "answer 59" in browser.cases.value


@pytest.mark.asyncio
async def test_colab_page_failure_remains_retryable_inside_callback(monkeypatch, tmp_path):
    from screamingface._ui.report_browser import ReportBrowser

    colab_host(monkeypatch, lambda path: None)
    monkeypatch.chdir(tmp_path)
    browser = ReportBrowser(large_report(60))
    render = browser._page_html

    def unavailable(page):
        raise OSError("page unavailable")

    monkeypatch.setattr(browser, "_page_html", unavailable)
    browser.next.click()
    assert browser.page == 0 and browser.count.value == "1–25 of 60"
    assert "page unavailable" in browser.notice.value and not browser._paging
    monkeypatch.setattr(browser, "_page_html", render)
    browser.next.click()
    assert browser.count.value == "26–50 of 60"
    assert not browser.notice.value


def test_notebook_extra_preserves_colab_seven_and_accepts_jupyter_eight():
    import tomllib

    from packaging.requirements import Requirement

    project = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())
    widgets = next(
        Requirement(value)
        for value in project["project"]["optional-dependencies"]["notebook"]
        if Requirement(value).name == "ipywidgets"
    )
    assert widgets.specifier.contains("7.7.1")
    assert widgets.specifier.contains("8.1.9")
    assert not widgets.specifier.contains("7.6.0")
    assert not widgets.specifier.contains("9.0.0")


def test_report_controls_only_pass_supported_widget_traits(monkeypatch, tmp_path):
    import warnings

    from screamingface._ui.report_browser import ReportBrowser

    monkeypatch.chdir(tmp_path)
    with warnings.catch_warnings():
        # INVARIANT: widget 7 must not rely on permissive treatment of unknown constructor args.
        warnings.filterwarnings("error", message="Passing unrecognized arguments to super")
        browser = ReportBrowser(large_report(1))
    assert browser.candidate.options == (("All Candidates", -1), ("model", 0))


def test_colab_case_click_bridge_tracks_selection_across_filters(monkeypatch, tmp_path):
    import gc
    import weakref

    from screamingface._ui.report_browser import ReportBrowser

    colab_host(monkeypatch, lambda path: None)
    output = sys.modules["google.colab.output"]
    registered = {}
    setattr(
        output, "register_callback", lambda name, callback: registered.__setitem__(name, callback)
    )
    setattr(output, "unregister_callback", registered.pop)
    monkeypatch.chdir(tmp_path)
    browser = ReportBrowser(large_report(60))
    assert len(registered) == 1
    name, select = next(iter(registered.items()))
    assert (
        name in browser.cases.value and "google.colab.kernel.invokeFunction" in browser.cases.value
    )
    browser.go_to.value = "59"
    import re

    row_ids = re.findall(r"id='([^']+)-row'", browser.cases.value)
    select({"target": {"id": row_ids[6] + "-row"}})
    assert browser._focus_id == 56 and browser.go_to.value == "56"
    browser.candidate.value = 0
    assert browser._focus_id == 56 and browser.count.value == "51–60 of 60"
    # INVARIANT: Colab's callback registry cannot keep the Report alive after its view is gone.
    reference = weakref.ref(browser)
    browser.w.Widget.close_all()
    del browser
    gc.collect()
    assert reference() is None and not registered
    select({"target": {"id": row_ids[0] + "-row"}})  # a late browser event is harmless


def test_ordinary_notebooks_use_widget_events_without_colab_script(monkeypatch, tmp_path):
    from screamingface._ui.report_browser import ReportBrowser

    monkeypatch.setattr("IPython.core.getipython.get_ipython", lambda: None)
    monkeypatch.chdir(tmp_path)
    browser = ReportBrowser(large_report(1))
    assert "invokeFunction" not in browser.cases.value
    assert browser._case_events.source is browser.cases
