from __future__ import annotations

import html
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Dict

from .models import AnalysisPlan, Claim, Evidence, RunManifest


def _json(value: Any) -> str:
    return html.escape(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def render_report(
    target: str | Path,
    manifest: RunManifest,
    plan: AnalysisPlan,
    quality: Dict[str, Any],
    results: Dict[str, Any],
    evidence: Iterable[Evidence],
    claims: Iterable[Claim],
    verification: Dict[str, Any],
) -> Path:
    evidence = list(evidence)
    claims = list(claims)
    status_class = "ok" if verification["status"] == "pass" and not quality.get("blocking") else "bad"
    document = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>EcomInsight · {html.escape(plan.objective)}</title>
<style>
:root{{--ink:#172033;--muted:#667085;--paper:#f4f7fb;--card:#fff;--blue:#2563eb;--line:#dbe4f0;--bad:#b42318}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}
main{{max-width:1120px;margin:auto;padding:42px 24px 80px}} header{{background:linear-gradient(135deg,#102a56,#2563eb);color:white;padding:38px;border-radius:24px;box-shadow:0 18px 50px #102a5622}}
h1{{margin:0 0 8px;font-size:34px}} h2{{margin-top:40px}} .meta{{opacity:.82}} .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px}} .card{{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:20px;box-shadow:0 6px 22px #102a560a}}
.pill{{display:inline-block;padding:5px 10px;border-radius:999px;background:#e8efff;color:#174ea6;font-weight:700}} .pill.bad{{background:#fee4e2;color:var(--bad)}} pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#101828;color:#e4e7ec;padding:18px;border-radius:12px;font-size:12px}}
table{{width:100%;border-collapse:collapse;background:white}} th,td{{border-bottom:1px solid var(--line);padding:10px;text-align:left;vertical-align:top}} .muted{{color:var(--muted)}}
</style></head><body><main>
<header><div class="pill {status_class}">{html.escape(verification['status'].upper())}</div><h1>{html.escape(plan.objective)}</h1><div>{html.escape(plan.question)}</div><div class="meta">Run {manifest.run_id} · {manifest.created_at.isoformat()} · {manifest.code_version}</div></header>
<h2>1. 分析目标与计划</h2><div class="card"><pre>{_json(plan.model_dump(mode='json'))}</pre></div>
<h2>2. 数据质量与语义边界</h2><div class="grid"><div class="card"><b>Data Health Score</b><div style="font-size:36px">{quality.get('score', 0)}</div></div><div class="card"><b>问题数</b><div style="font-size:36px">{len(quality.get('issues', []))}</div></div><div class="card"><b>运行状态</b><div style="font-size:24px">{manifest.status.value}</div></div></div><div class="card"><pre>{_json(quality)}</pre></div>
<h2>3. 核心指标与比较</h2><div class="card"><pre>{_json(results.get('summary', results))}</pre></div>
<h2>4. 驱动拆解与下钻</h2><div class="card"><pre>{_json({k:v for k,v in results.items() if 'driver' in k or 'contribution' in k or 'drilldown' in k})}</pre></div>
<h2>5. 专题分析与结论</h2><div class="card"><table><thead><tr><th>等级</th><th>结论</th><th>证据</th></tr></thead><tbody>{''.join(f'<tr><td>{html.escape(c.level)}</td><td>{html.escape(c.text)}</td><td>{html.escape(", ".join(c.evidence_ids))}</td></tr>' for c in claims) or '<tr><td colspan="3">本次未生成正式结论</td></tr>'}</tbody></table></div>
<h2>6. 限制、验证与后续建议</h2><div class="card"><pre>{_json(verification)}</pre><p>数学贡献仅表示可观测指标分解，不自动构成因果关系。补充实验、准实验或可比对照后，才能升级因果结论。</p></div>
<h2>证据附录</h2><div class="card"><pre>{_json([item.model_dump(mode='json') for item in evidence])}</pre></div>
</main></body></html>"""
    output = Path(target)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(document, encoding="utf-8")
    return output
