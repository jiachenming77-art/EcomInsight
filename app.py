from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from ecominsight.models import PlanStep, SemanticContract
from ecominsight.pipeline import EcomInsightPipeline

ROOT = Path(__file__).resolve().parent
st.set_page_config(page_title="EcomInsight", page_icon="📊", layout="wide")
st.title("EcomInsight")
st.caption("面向电商场景的证据驱动 AI 商业分析 Copilot")


@st.cache_resource
def pipeline() -> EcomInsightPipeline:
    return EcomInsightPipeline(ROOT)


uploaded = st.file_uploader("上传 CSV 或 XLSX", type=["csv", "xlsx"])
if uploaded is None:
    st.info("请上传订单或行为数据。原始文件不会写入版本库。")
    st.stop()

if uploaded.name.lower().endswith(".csv"):
    try:
        raw = pd.read_csv(uploaded)
    except UnicodeDecodeError:
        uploaded.seek(0)
        raw = pd.read_csv(uploaded, encoding="gb18030")
else:
    book = pd.ExcelFile(uploaded)
    sheet = st.selectbox("选择 Sheet", book.sheet_names)
    raw = pd.read_excel(uploaded, sheet_name=sheet)

st.subheader("1. 数据预览")
st.write(f"{len(raw):,} 行 × {len(raw.columns)} 列")
st.dataframe(raw.head(50), use_container_width=True)

pipe = pipeline()
inferred = pipe.mapper.infer(raw)
st.subheader("2. 字段语义确认")
confirmed = []
for mapping in inferred.mappings:
    checked = st.checkbox(
        f"{mapping.semantic} ← {mapping.source}（置信度 {mapping.confidence:.0%}）",
        value=mapping.confirmed,
        key=f"mapping_{mapping.semantic}",
    )
    confirmed.append(mapping.model_copy(update={"confirmed": checked}))
contract = SemanticContract(mappings=confirmed)
frame, _, quality = pipe.prepare(raw, contract)

st.subheader("3. 数据质量")
columns = st.columns(4)
columns[0].metric("Data Health Score", quality["score"])
for index, (key, value) in enumerate(quality["dimensions"].items(), start=1):
    columns[index].metric(key.title(), value)
if quality["issues"]:
    st.dataframe(pd.DataFrame(quality["issues"]), use_container_width=True)
else:
    st.success("未发现规则覆盖范围内的数据质量问题。")

st.subheader("4. 分析问题与计划")
question = st.text_input("业务问题", "为什么 8 月 GMV 比 7 月下降？")
col1, col2 = st.columns(2)
current_start = col1.date_input("当前期开始")
current_end = col1.date_input("当前期结束")
baseline_start = col2.date_input("基准期开始")
baseline_end = col2.date_input("基准期结束")
plan = pipe.build_plan(
    question,
    [current_start.isoformat(), current_end.isoformat()],
    [baseline_start.isoformat(), baseline_end.isoformat()],
)
available_modules = st.multiselect(
    "附加专题分析",
    ["RFM 用户分层", "Cohort 留存", "复购分析", "商品表现", "行为漏斗"],
)
module_steps = {
    "RFM 用户分层": PlanStep(id="module_rfm", op="rfm"),
    "Cohort 留存": PlanStep(id="module_cohort", op="cohort"),
    "复购分析": PlanStep(id="module_repurchase", op="repurchase"),
    "商品表现": PlanStep(id="module_product", op="product_performance", dimensions=["product_id"]),
}
for module in available_modules:
    if module in module_steps:
        plan.steps.append(module_steps[module])
if "行为漏斗" in available_modules:
    stage_text = st.text_input("漏斗阶段（按顺序，以英文逗号分隔）", "view,cart,pay")
    plan.steps.append(PlanStep(id="module_funnel", op="funnel", dimensions=[item.strip() for item in stage_text.split(",") if item.strip()]))
st.json(plan.model_dump(mode="json"))

if st.button("执行分析", type="primary", disabled=quality["blocking"]):
    with st.spinner("正在执行确定性分析并生成证据……"):
        output = pipe.execute(raw, plan, contract)
    st.success(f"运行完成：{output['run_id']}")
    st.json(output["results"])
    report = Path(output["report"])
    st.download_button("下载离线 HTML 报告", report.read_bytes(), file_name=f"{output['run_id']}.html", mime="text/html")
