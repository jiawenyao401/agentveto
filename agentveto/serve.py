"""Optional local viewer. Kept in its own module so the core stays dependency-free."""

from __future__ import annotations

from .report import build_report_data, render_html
from .store import Store

INDEX = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>agentveto</title>
<style>
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",sans-serif;
background:#FAFAF8;color:#1F1E1D;margin:0;padding:40px 32px;font-size:14px}
.wrap{max-width:820px;margin:0 auto}
h1{font-size:20px;font-weight:600;margin-bottom:2px}
p.sub{color:#5F5E5A;margin-bottom:24px}
table{width:100%;border-collapse:collapse;background:#fff;border:1px solid #E5E3DC;border-radius:10px;overflow:hidden}
th{text-align:left;font-size:12px;color:#5F5E5A;background:#FBFAF7;padding:10px 14px;border-bottom:1px solid #E5E3DC}
td{padding:11px 14px;border-bottom:1px solid #F2F0EA}
tr:last-child td{border-bottom:none}
a{color:#0F6E56;text-decoration:none;font-weight:500}
.n{font-variant-numeric:tabular-nums;color:#5F5E5A}
.empty{padding:36px;text-align:center;color:#8A8880}
</style></head><body><div class="wrap">
<h1>agentveto</h1><p class="sub">Recorded runs in __DB__</p>
__BODY__
</div></body></html>"""


def build_app(db: str | None = None):
    try:
        from fastapi import FastAPI
        from fastapi.responses import HTMLResponse
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "serve() needs the optional extras. Install them with:\n\n    pip install 'agentveto[serve]'\n"
        ) from exc

    store = Store(db)
    app = FastAPI(title="agentveto", docs_url=None, redoc_url=None)

    @app.get("/", response_class=HTMLResponse)
    def index():
        runs = store.list_runs(limit=200)
        if not runs:
            body = '<div class="empty">No runs yet. Run your agent with <code>agentveto.init()</code>.</div>'
        else:
            rows = []
            for r in runs:
                rows.append(
                    "<tr>"
                    f'<td><a href="/run/{r["id"]}">{r["name"]}</a></td>'
                    f"<td>{r['status']}</td>"
                    f'<td class="n">{r["span_count"]}</td>'
                    f'<td class="n">${r["total_cost"]:.5f}</td>'
                    f'<td class="n">{r["tokens_in"]} / {r["tokens_out"]}</td>'
                    "</tr>"
                )
            body = (
                "<table><tr><th>Run</th><th>Status</th><th>Steps</th>"
                "<th>Cost</th><th>Tokens in/out</th></tr>" + "".join(rows) + "</table>"
            )
        return INDEX.replace("__BODY__", body).replace("__DB__", store.path)

    @app.get("/run/{run_id}", response_class=HTMLResponse)
    def view(run_id: str):
        data = build_report_data(store, run_id)
        if data is None:
            return HTMLResponse("<h1>Not found</h1>", status_code=404)
        return render_html(data)

    return app


def serve(db: str | None = None, host: str = "127.0.0.1", port: int = 8420, open: bool = False) -> None:
    try:
        import uvicorn
    except ImportError:  # pragma: no cover
        raise SystemExit("serve() needs uvicorn. Install with: pip install 'agentveto[serve]'")

    app = build_app(db)
    if open:
        import threading
        import webbrowser

        threading.Timer(1.0, lambda: webbrowser.open(f"http://{host}:{port}")).start()
    uvicorn.run(app, host=host, port=port, log_level="warning")
