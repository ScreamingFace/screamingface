# Colab report compatibility (OME-1571, draft #1347)

The completed-report browser must work in Colab as well as Jupyter. Fresh Colab showed the default custom widget manager cannot load ipywidgets 8 HTML/Label/Text style models. Main's static report works, but this draft exposes the existing widget mismatch. Its new Jupyter file URL also resolves to browser localhost in Colab.

Preserve Colab's preinstalled ipywidgets 7.7.1 by accepting it in the optional notebook extra, subject to verification of all completed-report interactions. Keep ipywidgets 8 supported in Jupyter; do not force a package downgrade at runtime. Detect active Colab through the active IPython shell rather than package presence. Enable Colab's supported custom widget manager before display before the widget browser renders.

Export complete immutable JSON atomically once, then invoke google.colab.files.download in Colab from the kernel thread inside the click callback. Colab's comm transport requires bounded page state and native download display to publish within that callback; use synchronous page rendering and streaming export on this host while preserving Jupyter's async behavior. Keep the Download button repeatable and retry delivery errors without re-exporting a prepared snapshot. Concurrent preparation clicks must coalesce. In ordinary Jupyter retain file links honoring server root and base URL; unserved files retain their saved path. Never emit a Jupyter localhost file link in Colab.

All inherited tests remain unchanged. Verify widget 7 and 8 locally, all SDK gates, and actual live Colab paging, filtering, exact Case navigation, CSS rail selection synchronized through native Colab callbacks, with ipyevents retained for Jupyter, and browser file delivery with complete exported fields.

Colab lazily loads displayed widget models and does not instantiate the standalone ipyevents model. Register a uniquely named native output callback carrying the clicked row ID into the existing selection path. Keep the callback weak and unregister it when its browser is collected. Do not claim older-widget compatibility for unrelated live progress: those tests have existing failures on unchanged main.
