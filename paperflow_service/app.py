from __future__ import annotations

import html
import os
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

from .core import PaperFlowStore

DATA_DIR = Path(os.getenv("PAPERFLOW_DATA_DIR", "/data"))
DB_PATH = os.getenv("PAPERFLOW_DB_PATH", str(DATA_DIR / "paperflow.sqlite3"))
def _public_base_url() -> str:
    explicit = os.getenv("PAPERFLOW_PUBLIC_BASE_URL", "").strip()
    if explicit:
        return explicit.rstrip("/")
    railway_domain = os.getenv("RAILWAY_PUBLIC_DOMAIN", "").strip()
    if railway_domain:
        return f"https://{railway_domain}".rstrip("/")
    return "http://localhost:8000"

PUBLIC_BASE_URL = _public_base_url()
HOST = os.getenv("PAPERFLOW_HOST", "0.0.0.0")
LINT_SCRIPT = Path(__file__).parent / "vendor" / "paper_lint.py"
store = PaperFlowStore(DB_PATH)

SERVER_INSTRUCTIONS = """
PaperFlow Gate is the authoritative state machine for the Academic Paper Writer plugin.
Never treat chat text alone as proof that a gate is approved. Approval state changes only
when the user opens a one-time confirmation URL and clicks Confirm. Before drafting any
formal paper prose, call the relevant begin tool and proceed only if it returns allowed=true.
After manuscript changes, submit the new manuscript before lint/review/delivery. Delivery is
valid only when paperflow_deliver returns delivered=true.
""".strip()

mcp = FastMCP("PaperFlow Gate", instructions=SERVER_INSTRUCTIONS)

def ok(value: Any) -> dict[str, Any]:
    return {"ok": True, "result": value}

def err(e: Exception) -> dict[str, Any]:
    return {"ok": False, "error": str(e), "gate": getattr(e, "gate", None)}

def confirm_result(conf) -> dict[str, Any]:
    return {
        "paper_id": conf.paper_id, "kind": conf.kind, "summary": conf.summary,
        "expires_at": conf.expires_at,
        "confirmation_url": f"{PUBLIC_BASE_URL}/confirm/{conf.token}",
        "instruction": "把 confirmation_url 交给用户。只有用户在页面点击确认后，服务端门禁才会解锁。",
    }

@mcp.tool()
def paperflow_create_project(title: str = "") -> dict[str, Any]:
    """Create a persistent paper project and return its paper_id. Use before any gated writing workflow."""
    try: return ok(store.create_project(title))
    except Exception as e: return err(e)

@mcp.tool()
def paperflow_list_projects(limit: int = 20) -> dict[str, Any]:
    """List recently updated PaperFlow projects so a new chat can resume an existing paper."""
    try: return ok(store.list_projects(limit))
    except Exception as e: return err(e)

@mcp.tool()
def paperflow_status(paper_id: str) -> dict[str, Any]:
    """Read authoritative gate/section/quality state for one paper project."""
    try: return ok(store.status(paper_id))
    except Exception as e: return err(e)

@mcp.tool()
def paperflow_set_thesis(paper_id: str, claim: str, evidence: str, boundary: str, selling_point: str) -> dict[str, Any]:
    """Store the Gate 1 thesis anchor."""
    try: return ok(store.set_thesis(paper_id, claim, evidence, boundary, selling_point))
    except Exception as e: return err(e)

@mcp.tool()
def paperflow_set_angles(paper_id: str, angles: list[dict[str, str]]) -> dict[str, Any]:
    """Store exactly 2-3 narrative-angle candidates."""
    try: return ok(store.set_angles(paper_id, angles))
    except Exception as e: return err(e)

@mcp.tool()
def paperflow_request_gate1_confirmation(paper_id: str, angle: str) -> dict[str, Any]:
    """Create a one-time user confirmation link for Gate 1."""
    try: return ok(confirm_result(store.request_gate1(paper_id, angle)))
    except Exception as e: return err(e)

@mcp.tool()
def paperflow_set_intro_map(paper_id: str, challenges: list[str], contributions: list[dict[str, Any]], mapping: list[str]) -> dict[str, Any]:
    """Store Gate 2 challenge/contribution map."""
    try: return ok(store.set_intro_map(paper_id, challenges, contributions, mapping))
    except Exception as e: return err(e)

@mcp.tool()
def paperflow_request_gate2_confirmation(paper_id: str) -> dict[str, Any]:
    """Create a one-time user confirmation link for Gate 2."""
    try: return ok(confirm_result(store.request_gate2(paper_id)))
    except Exception as e: return err(e)

@mcp.tool()
def paperflow_set_intro_paragraph_plan(paper_id: str, n: int, opening_challenge: str, support: str, closing_problem: str) -> dict[str, Any]:
    """Store the plan for intro challenge paragraph N."""
    try: return ok(store.set_intro_paragraph_plan(paper_id, n, opening_challenge, support, closing_problem))
    except Exception as e: return err(e)

@mcp.tool()
def paperflow_request_intro_paragraph_confirmation(paper_id: str, n: int) -> dict[str, Any]:
    """Create a one-time confirmation link for intro paragraph N."""
    try: return ok(confirm_result(store.request_intro_para(paper_id, n)))
    except Exception as e: return err(e)

@mcp.tool()
def paperflow_begin_intro_paragraph(paper_id: str, n: int) -> dict[str, Any]:
    """Authorize drafting intro paragraph N."""
    try: return ok(store.begin_intro_paragraph(paper_id, n))
    except Exception as e: return err(e)

@mcp.tool()
def paperflow_finish_intro_paragraph(paper_id: str, n: int) -> dict[str, Any]:
    """Mark intro paragraph N complete."""
    try: return ok(store.finish_intro_paragraph(paper_id, n))
    except Exception as e: return err(e)

@mcp.tool()
def paperflow_set_method_core(paper_id: str, innovation: str, not_simple_combination: str, evidence: str, modules: list[dict[str, str]]) -> dict[str, Any]:
    """Store Gate 3 core innovation."""
    try: return ok(store.set_method_core(paper_id, innovation, not_simple_combination, evidence, modules))
    except Exception as e: return err(e)

@mcp.tool()
def paperflow_request_gate3_confirmation(paper_id: str) -> dict[str, Any]:
    """Create a one-time user confirmation link for Gate 3."""
    try: return ok(confirm_result(store.request_gate3(paper_id)))
    except Exception as e: return err(e)

@mcp.tool()
def paperflow_set_abstract_plan(paper_id: str, s1: str, s2_items: list[str], s3: str, mapping: str) -> dict[str, Any]:
    """Store abstract plan. Requires confirmed Gate 2 and Gate 3."""
    try: return ok(store.set_abstract_plan(paper_id, s1, s2_items, s3, mapping))
    except Exception as e: return err(e)

@mcp.tool()
def paperflow_request_abstract_plan_confirmation(paper_id: str) -> dict[str, Any]:
    """Create a one-time confirmation link for abstract plan."""
    try: return ok(confirm_result(store.request_abstract_plan(paper_id)))
    except Exception as e: return err(e)

@mcp.tool()
def paperflow_begin_section(paper_id: str, section: str) -> dict[str, Any]:
    """Hard gate for formal drafting."""
    try: return ok(store.begin_section(paper_id, section))
    except Exception as e: return err(e)

@mcp.tool()
def paperflow_finish_section(paper_id: str, section: str) -> dict[str, Any]:
    """Mark a formal section completed."""
    try: return ok(store.finish_section(paper_id, section))
    except Exception as e: return err(e)

@mcp.tool()
def paperflow_submit_manuscript(paper_id: str, manuscript_text: str, method_acronym: str = "") -> dict[str, Any]:
    """Submit the current manuscript; new submission invalidates lint/review."""
    try: return ok(store.submit_manuscript(paper_id, manuscript_text, method_acronym))
    except Exception as e: return err(e)

@mcp.tool()
def paperflow_record_selfcheck(paper_id: str, notes: str) -> dict[str, Any]:
    """Record reviewer-style self-check notes."""
    try: return ok(store.record_selfcheck(paper_id, notes))
    except Exception as e: return err(e)

@mcp.tool()
def paperflow_run_lint(paper_id: str) -> dict[str, Any]:
    """Run bundled paper_lint.py against stored manuscript."""
    try: return ok(store.run_lint(paper_id, LINT_SCRIPT))
    except Exception as e: return err(e)

@mcp.tool()
def paperflow_record_review(paper_id: str, notes: str) -> dict[str, Any]:
    """Record Gate 4 cross-section review."""
    try: return ok(store.record_review(paper_id, notes))
    except Exception as e: return err(e)

@mcp.tool()
def paperflow_deliver(paper_id: str) -> dict[str, Any]:
    """Final Gate 4."""
    try: return ok(store.deliver(paper_id))
    except Exception as e: return err(e)

async def health(_: Request) -> JSONResponse:
    return JSONResponse({"ok": True, "service": "paperflow-gate", "db": DB_PATH})

def page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title><style>
body{{font-family:system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:760px;margin:48px auto;padding:0 20px;line-height:1.65;color:#17212b}} .card{{border:1px solid #d9e2ea;border-radius:16px;padding:24px;box-shadow:0 6px 24px rgba(0,0,0,.05)}} h1{{font-size:24px}} .meta{{color:#637282;font-size:14px}} .summary{{white-space:pre-wrap;background:#f5f8fa;padding:16px;border-radius:10px}} form{{display:inline-block;margin-right:10px;margin-top:18px}} button{{border:0;border-radius:10px;padding:11px 18px;font-size:16px;cursor:pointer}} .yes{{background:#24527A;color:white}} .no{{background:#e8edf1;color:#17212b}}
</style></head><body><div class="card">{body}</div></body></html>""")

async def confirm_page(request: Request) -> HTMLResponse:
    token = request.path_params["token"]
    try: conf = store.get_confirmation(token)
    except Exception as e: return page("确认链接无效", f"<h1>确认链接无效</h1><p>{html.escape(str(e))}</p>")
    if conf.status != "pending":
        return page("已处理", f"<h1>该请求已处理</h1><p>状态：{html.escape(conf.status)}</p>")
    body = f"""<h1>PaperFlow 门禁确认</h1><p class="meta">项目：{html.escape(conf.paper_id)} · 类型：{html.escape(conf.kind)} · 过期：{html.escape(conf.expires_at)}</p><div class="summary">{html.escape(conf.summary)}</div><p>点击“确认”会永久写入该项目的服务端状态；聊天模型本身无法执行这个批准动作。</p><form method="post"><input type="hidden" name="decision" value="approve"><button class="yes" type="submit">确认并解锁</button></form><form method="post"><input type="hidden" name="decision" value="reject"><button class="no" type="submit">不确认</button></form>"""
    return page("PaperFlow 门禁确认", body)

async def confirm_submit(request: Request) -> HTMLResponse:
    token = request.path_params["token"]
    form = await request.form()
    approve = form.get("decision") == "approve"
    try:
        st = store.decide_confirmation(token, approve)
        if approve:
            return page("已确认", f"<h1>已确认并写入服务端</h1><p>项目 {html.escape(st['id'])} 当前阶段：{html.escape(st['stage'])}</p><p>可以返回 ChatGPT 继续。</p>")
        return page("已拒绝", "<h1>未解锁</h1><p>该门禁保持关闭。可以返回 ChatGPT 修改方案后重新确认。</p>")
    except Exception as e:
        return page("处理失败", f"<h1>处理失败</h1><p>{html.escape(str(e))}</p>")

routes = [
    Route("/health", health, methods=["GET"]),
    Route("/confirm/{token}", confirm_page, methods=["GET"]),
    Route("/confirm/{token}", confirm_submit, methods=["POST"]),
]
app = mcp.streamable_http_app()
app.router.routes[:0] = routes
