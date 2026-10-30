"""Run the 12 evaluation questions and write docs/evaluation.md.

Local mode calls app.agent.answer with the real LLM. With --base-url it calls a running server's /api/ask.
Exits 0 only if the score is at least 10/12 and no answer has unverified numbers.
"""
import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.verifier import extract_numbers  # noqa: E402

REFUSAL = re.compile(r"(not (available|covered|included|in the|part of)|do(es)? not (cover|have|include|contain|provide|report|show|give)|"
                     r"cannot|can't|can not|out of scope|outside|no (data|table)|unable|isn't|is not|don't have|"
                     r"not able|does not predict|not something)", re.I)


def ask_local(question):
    from app.agent import answer
    return answer(question)


def ask_remote(base_url, question):
    import httpx
    response = httpx.post(base_url.rstrip("/") + "/api/ask", json={"question": question}, timeout=90)
    return response.json()


def value_present(expected, text):
    for number in extract_numbers(text):
        tolerance = 0.5 * 10 ** (-number["decimals"]) * number["scale"] + 1e-9
        if abs(number["value"] - expected) <= tolerance or (expected >= 1000 and abs(number["value"] - expected) <= 0.005 * expected):
            return True
    return False


def score(item, result):
    reasons = []
    if "error" in result and "answer_text" not in result:
        return False, [f"error: {result['error']}"]
    text = result.get("answer_text", "")
    haystack = (text + " " + json.dumps(result.get("table_rows") or {})).casefold()
    for needle in item.get("expect_contains") or []:
        if needle.casefold() not in haystack:
            reasons.append(f"missing '{needle}'")
    for value in item.get("expect_values") or []:
        if not value_present(value, text):
            reasons.append(f"value {value} not in answer")
    cited = [c["table_id"] for c in result.get("citations", [])]
    for key in ["expect_tables", "expect_tables_also"]:
        wanted = item.get(key) or []
        if wanted and not any(w in t for w in wanted for t in cited):
            reasons.append(f"no citation matching {wanted}")
    if item["type"] == "refusal":
        if not REFUSAL.search(text):
            reasons.append("does not say the data is not available")
    if result.get("verification", {}).get("status") != "verified":
        reasons.append("unverified numbers: " + ", ".join(result.get("verification", {}).get("unmatched", [])))
    return not reasons, reasons


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", help="evaluate a running server instead of the local agent")
    parser.add_argument("--only", type=int, nargs="*", help="question ids to run")
    args = parser.parse_args()
    items = yaml.safe_load((ROOT / "tests/eval_questions.yaml").read_text())
    if args.only:
        items = [i for i in items if i["id"] in args.only]
    rows, passed, unverified = [], 0, 0
    for item in items:
        started = time.time()
        try:
            result = ask_remote(args.base_url, item["question"]) if args.base_url else ask_local(item["question"])
        except Exception as error:  # report and keep going
            result = {"error": f"{type(error).__name__}: {error}"}
        latency = round(time.time() - started, 1)
        ok, reasons = score(item, result)
        status = result.get("verification", {}).get("status", "n/a")
        passed += ok
        unverified += status == "unverified"
        rows.append({"id": item["id"], "question": item["question"], "type": item["type"], "result": "PASS" if ok else "FAIL",
                     "reasons": reasons, "verifier": status, "latency_s": latency,
                     "tables": [c["table_id"] for c in result.get("citations", [])],
                     "answer": result.get("answer_text", result.get("error", ""))})
        print(f"[{'PASS' if ok else 'FAIL'}] {item['id']}. {item['question']} ({latency}s) {'; '.join(reasons)}", flush=True)
    write_report(rows, passed, len(items), args.base_url)
    print(f"Score: {passed}/{len(items)}, unverified answers: {unverified}")
    full_run = not args.only
    sys.exit(0 if full_run and passed >= 10 and unverified == 0 else (0 if not full_run and passed == len(items) else 1))


def write_report(rows, passed, total, base_url):
    target = "live server " + base_url if base_url else "local agent"
    lines = ["# Evaluation results", "",
             f"Run on {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M %Z')} against the {target}.",
             "Questions come from `tests/eval_questions.yaml` (brief section 8). Scoring is automatic: expected district names and values",
             "must appear in the answer, the right NISR table must be cited, refusals must say the data is not available, and the verifier",
             "must pass. Expected values were read from the raw NISR tables, not typed into the app.", "",
             f"**Score: {passed}/{total}**", "",
             "| # | Question | Result | Verifier | Latency (s) | Tables cited | Answer |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        answer = r["answer"].replace("|", "/").replace("\n", " ")
        note = f" ({'; '.join(r['reasons'])})" if r["reasons"] else ""
        lines.append(f"| {r['id']} | {r['question']} | {r['result']}{note} | {r['verifier']} | {r['latency_s']} | "
                     f"{', '.join(r['tables']) or 'none'} | {answer} |")
    (ROOT / "docs/evaluation.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    update_readme(rows, passed, total, target)
    (ROOT / "docs/evaluation.json").write_text(json.dumps({"score": passed, "total": total, "rows": rows}, indent=2) + "\n", encoding="utf-8")


def update_readme(rows, passed, total, target):
    """Replace the block between the EVAL markers in README.md with the latest results."""
    readme = ROOT / "README.md"
    if not readme.exists():
        return
    text = readme.read_text(encoding="utf-8")
    start, end = "<!-- EVAL:START -->", "<!-- EVAL:END -->"
    if start not in text or end not in text:
        return
    lines = [start, "", f"**Score: {passed}/{total}** on the {target}, {datetime.now().astimezone().strftime('%Y-%m-%d')}. "
             "Full answers: [docs/evaluation.json](docs/evaluation.json).", "",
             "| # | Question | Result | Verifier | Latency (s) | Tables cited |", "|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['id']} | {r['question']} | {r['result']} | {r['verifier']} | {r['latency_s']} | {', '.join(r['tables']) or 'none (refusal)'} |")
    lines += ["", end]
    before, rest = text.split(start, 1)
    after = rest.split(end, 1)[1]
    readme.write_text(before + "\n".join(lines) + after, encoding="utf-8")


if __name__ == "__main__":
    main()
