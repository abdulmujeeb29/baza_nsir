"""Agent loop: the model calls tools over NISR tables, then the verifier checks every number."""
import json
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
import time

from app import nisr_catalog, tools
from pipeline.geo import DISTRICTS
from app.llm import LLMError, get_llm, model_name
from app.prompts import build_system_prompt
from app.verifier import numbers_in_strings, verify

_POOL = ThreadPoolExecutor(max_workers=8, thread_name_prefix="baza-tool")
MAX_TOOL_STEPS = 8
MAX_INVESTIGATION_STEPS = 18
INVESTIGATION_RULES = """INVESTIGATION MODE. The user wants a short evidence brief, not a one-line answer.
1. First call plan(steps) with 3 to 6 sub-questions you will answer from the tables (for example: poverty level,
   access to electricity and water, health insurance, internet, jobs). Then work through them.
2. Compare the place with its province and with Rwanda when possible (query the province and national rows too).
   Prefer few, wide queries: one query can return several indicators by joining tables on district.
3. Use both Census 2022 and EICV7 2023/24 where useful, and name the source of each number.
4. final_answer.answer_text: one plain sentence summary, then 4 to 7 lines starting with "- ", each one finding with
   its number and source, for example "- Poverty: 51.4% (EICV7 2023/24), national 27.4%." Then one line starting
   with "Where to act:" that states what the data points to, without giving policy advice as fact.
Every number must come from a query result."""
MAX_SQL_ERRORS = 2
MAX_ROWS_TO_MODEL = 40

TOOL_SPECS = [
    {"name": "search_catalog", "description": "Search the catalogue of loaded NISR tables. Returns the best 5 matches.",
     "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    {"name": "describe_table", "description": "Columns, types, sample rows, distinct breakdown values and citation for one table.",
     "parameters": {"type": "object", "properties": {"table_id": {"type": "string"}}, "required": ["table_id"]}},
    {"name": "run_sql", "description": "Run one read-only DuckDB SELECT query. Max 500 rows.",
     "parameters": {"type": "object", "properties": {"sql": {"type": "string"}}, "required": ["sql"]}},
    {"name": "search_nisr_catalog", "description": "Search NISR's official microdata catalogue (all surveys and documents). "
     "Use it when the loaded tables cannot answer, to tell the user which NISR survey covers the topic. Returns titles, years and links, not numbers.",
     "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    {"name": "make_chart", "description": "Build a chart from the last run_sql result.",
     "parameters": {"type": "object", "properties": {
         "chart_type": {"type": "string", "enum": ["barh", "bar", "line", "table"]},
         "x": {"type": "string", "description": "category column (for example district)"},
         "y": {"type": "string", "description": "numeric column"},
         "title": {"type": "string"}}, "required": ["chart_type", "x", "y"]}},
    {"name": "plan", "description": "Investigation mode only: state the sub-questions you will answer, before querying.",
     "parameters": {"type": "object", "properties": {"steps": {"type": "array", "items": {"type": "string"}}}, "required": ["steps"]}},
    {"name": "final_answer", "description": "Give the final answer. Call once, at the end.",
     "parameters": {"type": "object", "properties": {
         "answer_text": {"type": "string", "description": "2 to 4 plain sentences. Every number must come from a query result."},
         "caveats": {"type": "array", "items": {"type": "string"}}}, "required": ["answer_text"]}},
]


def _for_model(result):
    """Compact, rounded copy of a tool result for the model. Full precision is kept for the verifier."""
    if "rows" in result:
        rows = [[round(v, 2) if isinstance(v, float) else v for v in r] for r in result["rows"][:MAX_ROWS_TO_MODEL]]
        extra = {"note": f"showing {MAX_ROWS_TO_MODEL} of {result['row_count']} rows"} if result["row_count"] > MAX_ROWS_TO_MODEL else {}
        return {"columns": result["columns"], "rows": rows, "row_count": result["row_count"], **extra}
    return result


def _auto_chart(result):
    """Draw a ranked bar chart when a result has one label column and a numeric column."""
    if not result or result["row_count"] < 2 or result["row_count"] > 60:
        return None
    columns, first = result["columns"], result["rows"][0]
    text_cols = [c for c, v in zip(columns, first) if isinstance(v, str)]
    num_cols = [c for c, v in zip(columns, first) if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if not text_cols or not num_cols:
        return None
    x = "district" if "district" in text_cols else text_cols[0]
    return tools.make_chart(result, "barh", x, num_cols[0], num_cols[0].replace("_", " "))


def _district_map(result, chart):
    """Map data for the choropleth when the result has district rows and a numeric column."""
    if not result or "district" not in result["columns"]:
        return None
    di = result["columns"].index("district")
    names = {d["district"] for d in DISTRICTS}
    rows = [r for r in result["rows"] if r[di] in names]
    if len(rows) < 2:
        return None
    numeric = [c for i, c in enumerate(result["columns"])
               if all(isinstance(r[i], (int, float)) and not isinstance(r[i], bool) for r in rows if r[i] is not None)
               and any(r[i] is not None for r in rows) and c != "district"]
    if not numeric:
        return None
    y = chart["spec"]["encoding"]["x" if chart["type"] == "barh" else "y"]["field"] if chart and chart.get("spec") else numeric[0]
    y = y if y in numeric else numeric[0]
    yi = result["columns"].index(y)
    return {"district_field": "district", "value_field": y, "title": y.replace("_", " "),
            "values": [{"district": r[di], y: r[yi]} for r in rows]}


def _short_ref(ref):
    """'Table A9.23' -> 'A9.23', 'Table 25' -> 'T25', 'LFIndicatorsRw' stays as is."""
    ref = ref.replace("Table ", "")
    return "T" + ref if ref[:1].isdigit() else ref


def tag_numbers(tags, results):
    """Attach the NISR table reference to each checked number, for the 'scan' frames in the UI."""
    refs = {r["table_id"]: r["nisr_table_ref"] for r in tools.catalog_rows()}
    out = []
    for tag in tags:
        ref = None
        if tag["result"] is not None and tag["result"] < len(results):
            used = results[tag["result"]]["tables_used"]
            # One table: name it. A join: point to the query (Q1, Q2...) shown under "How I got this".
            ref = _short_ref(refs.get(used[0], used[0])) if len(used) == 1 else f"Q{tag['result'] + 1}"
        out.append({"text": tag["text"], "match": tag["match"], "ref": ref})
    return out


def emit(callback, kind, **data):
    """Send a progress event to the caller (used for the live trace). Never lets a callback break the agent."""
    if callback:
        try:
            callback({"type": kind, **data})
        except Exception:  # noqa: BLE001
            pass


class Session:
    def __init__(self, on_event=None):
        self.on_event = on_event
        self.lock = threading.Lock()
        self.results = []
        self.last_result = None
        self.chart = None
        self.sql = []
        self.steps = []
        self.sql_errors = 0
        self.final = None
        self.pointers = []
        self.plan = []

    def step(self, tool, detail):
        with self.lock:
            self.steps.append({"tool": tool, "detail": detail})
        emit(self.on_event, "step", tool=tool, detail=detail)

    # Tools that only read (no shared state) can run in parallel; the rest run in order after them.
    PARALLEL = {"search_catalog", "describe_table", "run_sql", "search_nisr_catalog"}

    def fetch(self, name, args):
        """The slow, side-effect-free part of a tool. Safe to run concurrently."""
        if name == "search_catalog":
            return tools.search_catalog(str(args.get("query", "")))
        if name == "describe_table":
            return tools.describe_table(str(args.get("table_id", "")))
        if name == "run_sql":
            return tools.run_sql(str(args.get("sql", "")))
        if name == "search_nisr_catalog":
            try:
                return nisr_catalog.search(str(args.get("query", "")))
            except nisr_catalog.CatalogError as error:
                return {"error": str(error)}
        return None

    def call(self, name, args, fetched=None):
        """Record a tool's result in the session (in call order) and return what the model sees."""
        if name == "run_sql" and self.sql_errors >= MAX_SQL_ERRORS:
            return {"error": "SQL retry limit reached. Answer with what you have or explain the data is not available."}
        out = fetched if fetched is not None else self.fetch(name, args)
        if name == "search_catalog":
            self.step(name, f"Searching catalogue: {args.get('query', '')}")
            return out
        if name == "describe_table":
            self.step(name, f"Reading table {args.get('table_id', '')}")
            return out
        if name == "run_sql":
            self.step(name, "Running query" + (f" (error: {out['error']})" if "error" in out else f": {out['row_count']} rows"))
            if "error" in out:
                self.sql_errors += 1
                return {"error": out["error"], "hint": "Fix the query and try once more. Check column names with describe_table."}
            self.results.append(out)
            self.last_result = out
            self.sql.append(out["sql"])
            return _for_model(out)
        if name == "search_nisr_catalog":
            self.step(name, f"Searching NISR's microdata catalogue: {args.get('query', '')}")
            if isinstance(out, dict) and "error" in out:
                return out
            for item in out:
                if item["idno"] not in {p["idno"] for p in self.pointers}:
                    self.pointers.append(item)
            return out
        if name == "make_chart":
            out = tools.make_chart(self.last_result, args.get("chart_type", "barh"), args.get("x"), args.get("y"), args.get("title", ""))
            if "error" not in out:
                self.chart = out
                self.step(name, f"Drawing {out['type']} chart")
                return {"ok": True, "chart_type": out["type"]}
            return out
        if name == "plan":
            self.plan = [str(x)[:160] for x in (args.get("steps") or [])][:8]
            with self.lock:
                self.steps.append({"tool": "plan", "detail": "Plan: " + " | ".join(self.plan)})
            emit(self.on_event, "plan", steps=self.plan)
            return {"ok": True}
        if name == "final_answer":
            self.final = {"answer_text": str(args.get("answer_text", "")).strip(),
                          "caveats": [str(c) for c in (args.get("caveats") or [])]}
            return {"ok": True}
        return {"error": f"Unknown tool {name}"}

    def run_calls(self, calls):
        """Fetch read-only tools concurrently, then record every call in the order the model made them."""
        slow = [c for c in calls if c.name in self.PARALLEL]
        fetched = {}
        if len(slow) > 1:
            for call, out in zip(slow, _POOL.map(lambda c: self.fetch(c.name, c.arguments), slow)):
                fetched[call.id] = out
        return [self.call(c.name, c.arguments, fetched.get(c.id)) for c in calls]

    def citations(self):
        used = []
        for result in self.results:
            for table_id in result["tables_used"]:
                if table_id not in used:
                    used.append(table_id)
        rows = {r["table_id"]: r for r in tools.catalog_rows()}
        return [tools.citation(rows[t]) for t in used if t in rows]


def _run_turns(llm, messages, session, budget):
    """Let the model call tools until it calls final_answer or the budget runs out."""
    session.final = None
    nudged = False
    for _ in range(budget):
        response = llm.chat_with_tools(messages, TOOL_SPECS)
        if not response.tool_calls:
            if not response.text.strip() and not nudged:
                nudged = True
                messages.append({"role": "user", "content": "Please call final_answer now with your answer."})
                continue
            session.final = {"answer_text": response.text.strip(), "caveats": []}
            messages.append({"role": "assistant", "content": response.text})
            return
        messages.append({"role": "assistant", "content": response.text or None, "tool_calls": [
            {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": json.dumps(c.arguments)}}
            for c in response.tool_calls]})
        calls = response.tool_calls
        for call, out in zip(calls, session.run_calls(calls)):
            messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(out, default=str)[:12000]})
        if session.final is not None:
            return
    if session.final is None:
        session.final = {"answer_text": "", "caveats": ["The assistant ran out of steps before finishing."]}


KINYARWANDA_GLOSSARY = (
    "Use these standard Kinyarwanda statistics terms: unemployment rate = igipimo cy'ubushomeri; poverty = ubukene; "
    "poverty rate = igipimo cy'ubukene; district = akarere; province = intara; household = urugo; population = abaturage; "
    "electricity = amashanyarazi; health insurance = ubwishingizi bw'indwara; internet = interineti; "
    "drinking water = amazi meza yo kunywa; confidence interval = intera y'icyizere; survey = ubushakashatsi; "
    "census = ibarura rusange; National Institute of Statistics of Rwanda = Ikigo cy'Igihugu cy'Ibarurishamibare (NISR). ")


def translate(text, target, llm):
    """Plain translation with no tools. Numbers, district names and table references must not change."""
    prompt = (f"Translate the text below into {target}. Keep every number exactly as written (same digits, decimals and % signs), "
              "keep district and province names, survey names (Census, EICV7, LFS) and table references unchanged. "
              + (KINYARWANDA_GLOSSARY if target == "Kinyarwanda" else "")
              + "Reply with the translation only.\n\n" + text)
    return llm.chat_with_tools([{"role": "user", "content": prompt}], []).text.strip()


def same_numbers(a, b):
    """True when both texts contain exactly the same numbers (every digit group, including years and table refs)."""
    def raw(text):
        return sorted(float(n.replace(",", "")) for n in re.findall(r"\d+(?:[.,]\d+)*", text or "")
                      if re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?", n))
    return raw(a) == raw(b)


LANGUAGE_NAMES = {"en": "English", "rw": "Kinyarwanda"}


def translate_answer(text_en, target, llm):
    """Translate a verified English answer. Keep the translation only if every number is unchanged."""
    if target == "en":
        return {"answer_text": text_en, "language": "en"}
    translated = translate(text_en, LANGUAGE_NAMES[target], llm)
    if translated and same_numbers(text_en, translated):
        return {"answer_text": translated, "language": target}
    return {"answer_text": text_en, "language": "en",
            "note": "The translation changed a number, so the English answer is shown."}


def answer(question, llm=None, lang="en", on_event=None, mode="ask"):
    """Answer a question. lang='rw' translates the question to English, answers, then translates back."""
    started = time.time()
    question = (question or "").strip()
    llm = llm or get_llm()
    if lang not in LANGUAGE_NAMES or lang == "en":
        result, _ = _answer_english(question, llm, on_event, mode)
    else:
        # The model reads Kinyarwanda directly, so no separate translation call is needed for the question.
        english_question = question + "\n(The question may be in Kinyarwanda. Write final_answer in English; it is translated afterwards.)"
        result, results = _answer_english(english_question, llm, on_event, mode)
        emit(on_event, "step", tool="translate", detail="Translating the checked answer to Kinyarwanda")
        result.update(question=question)
        translated = translate_answer(result["answer_text_en"], lang, llm)
        result["answer_text"], result["language"] = translated["answer_text"], translated["language"]
        if "note" in translated:
            result["caveats"].append(translated["note"])
        else:
            context = numbers_in_strings([c["title"] for c in result["citations"]])
            result["verification"] = {**verify(result["answer_text"], results, context),
                                      "self_corrected": result["verification"]["self_corrected"]}
    result["latency_s"] = round(time.time() - started, 2)
    return result


# Core district indicators an investigation should always consider (one per topic, newest survey first).
CORE_DISTRICT_TABLES = ["eicv7_a9_23_poverty_rate", "eicv7_a5_14_electricity_lighting", "eicv7_a5_16_improved_water",
                        "eicv7_a5_17_improved_sanitation", "eicv7_a3_7_health_insurance", "eicv7_a5_15_internet_at_home",
                        "eicv7_a5_19_smartphone", "census_t79_agricultural_households", "census_t1_population"]


def prefetch_context(question, limit=4, core=False):
    """Look up the most likely tables locally (no model call) so the model can usually go straight to SQL."""
    found = [r["table_id"] for r in tools.search_catalog(question, limit=limit)]
    if core:
        found = list(dict.fromkeys(CORE_DISTRICT_TABLES + found))
    found = [{"table_id": t} for t in found]
    infos = list(_POOL.map(lambda r: tools.describe_table(r["table_id"]), found))
    lines = ["Likely relevant tables, already looked up for you (use describe_table only if you need more detail):"]
    for info in infos:
        if "error" in info:
            continue
        columns = ", ".join(c["name"] for c in info["columns"])
        extra = ""
        for key, values in info.get("distinct_values", {}).items():
            extra += f" Distinct {key}: {', '.join(map(str, values[:12]))}."
        lines.append(f"- {info['table_id']} ({info['citation']['survey']} {info['citation']['year']}, {info['unit']}): "
                     f"{info['title'][:120]}. Columns: {columns}.{extra}")
    return "\n".join(lines), [r["table_id"] for r in found]


def _answer_english(question, llm, on_event=None, mode="ask"):
    session = Session(on_event)
    emit(on_event, "step", tool="plan", detail="Reading the question and planning which NISR tables to use")
    investigate = mode == "investigate"
    system = build_system_prompt() + ("\n\n" + INVESTIGATION_RULES if investigate else "")
    context, likely = prefetch_context(question, core=investigate)
    session.step("search_catalog", "Pre-selected likely tables: " + ", ".join(likely))
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": f"{question}\n\n---\n{context}"}]
    _run_turns(llm, messages, session, MAX_INVESTIGATION_STEPS if investigate else MAX_TOOL_STEPS)

    context = numbers_in_strings([c["title"] for c in session.citations()])
    session.step("verify", "Checking every number in the answer against the query results")
    verification = verify(session.final["answer_text"], session.results, context)
    corrected = False
    if verification["status"] == "unverified":
        messages.append({"role": "user", "content":
                         "Verification failed. These numbers are not in your query results: "
                         + ", ".join(verification["unmatched"])
                         + ". Call final_answer again using only numbers that appear in the query results "
                           "(you may run one more query if needed)."})
        session.step("verify", "Some numbers did not match. Asking the model to correct them: " + ", ".join(verification["unmatched"]))
        _run_turns(llm, messages, session, 3)
        verification = verify(session.final["answer_text"], session.results, context)
        corrected = True

    answer_text = session.final["answer_text"].replace(" \u2014 ", ", ").replace("\u2014", ", ")
    if answer_text != session.final["answer_text"]:
        verification = {**verify(answer_text, session.results, context), "self_corrected": corrected}
    if not answer_text and session.pointers and not session.results:
        titles = "; ".join(f"{p['title']} ({p['years']})" for p in session.pointers[:3])
        answer_text = ("The NISR tables loaded here do not cover this question. NISR's microdata catalogue lists these "
                       f"related sources: {titles}.")
    answer_text = answer_text or "Sorry, I could not produce an answer. Please try rephrasing the question."
    chart = session.chart or _auto_chart(session.last_result)
    table = {"columns": session.last_result["columns"], "rows": session.last_result["rows"]} if session.last_result else None
    return {
        "question": question,
        "answer_text": answer_text,
        "answer_text_en": answer_text,
        "chart": chart,
        "map": _district_map(session.last_result, chart),
        "table_rows": table,
        "citations": session.citations(),
        "sql": session.sql,
        "caveats": session.final["caveats"],
        "steps": session.steps,
        "verification": {**verification, "self_corrected": corrected},
        "number_tags": tag_numbers(verification.get("tags", []), session.results),
        "answered_from_data": bool(session.results),
        "catalog_pointers": session.pointers[:5],
        "mode": mode,
        "plan": session.plan,
        "queries": [{"sql": r["sql"], "columns": r["columns"], "rows": r["rows"][:60]} for r in session.results],
        "model": getattr(llm, "model", model_name()),
        "language": "en",
    }, session.results


if __name__ == "__main__":
    text = " ".join(sys.argv[1:]) or "Which district has the highest poverty rate?"
    try:
        print(json.dumps(answer(text), indent=2, ensure_ascii=False, default=str))
    except LLMError as error:
        print(json.dumps({"error": str(error)}))
        sys.exit(1)
