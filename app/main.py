"""FastAPI app: /api/health, /api/catalog, /api/ask, and the single-page frontend."""
import asyncio
import json
import logging
import os
import time
from typing import Literal
from collections import defaultdict, deque
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import agent, question_log, tools
from app.llm import FakeLLM, LLMError, LLMResponse, ToolCall, get_llm, model_name
from pipeline.geo import DISTRICT_BY_NAME, DISTRICTS, normalise_name

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

RATE_LIMIT = int(os.getenv("RATE_LIMIT_PER_MINUTE", "20"))
ASK_TIMEOUT = float(os.getenv("ASK_TIMEOUT_SECONDS", "45"))
INVESTIGATE_TIMEOUT = float(os.getenv("INVESTIGATE_TIMEOUT_SECONDS", "150"))
log = logging.getLogger("baza")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def demo_llm():
    """Offline scripted model for APP_ENV=test. It still runs real SQL on the real tables."""
    sql = ("SELECT district, province, ROUND(value, 2) AS poverty_rate_pct FROM eicv7_a9_23_poverty_rate "
           "WHERE geo_level = 'district' ORDER BY value DESC LIMIT 5")
    return FakeLLM([
        LLMResponse("", [ToolCall("1", "search_catalog", {"query": "poverty by district"})]),
        LLMResponse("", [ToolCall("2", "run_sql", {"sql": sql})]),
        LLMResponse("", [ToolCall("3", "make_chart", {"chart_type": "barh", "x": "district", "y": "poverty_rate_pct",
                                                      "title": "Poverty rate by district (%)"})]),
        LLMResponse("", [ToolCall("4", "final_answer", {
            "answer_text": "Test mode answer: Nyamagabe has the highest poverty rate, 51.39% (EICV7 2023/24, Table A9.23).",
            "caveats": ["Test mode uses a scripted model."]})]),
    ])


def llm_factory():
    if os.getenv("APP_ENV", "").casefold() == "test":
        return demo_llm()
    return get_llm()


app = FastAPI(title="Baza NISR", docs_url="/api/docs", redoc_url=None)
app.state.llm_factory = llm_factory
app.state.hits = defaultdict(deque)


class AskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=500)
    lang: Literal["en", "rw"] = "en"
    mode: Literal["ask", "investigate"] = "ask"


def timeout_for(body):
    return INVESTIGATE_TIMEOUT if body.mode == "investigate" else ASK_TIMEOUT


def run_agent(body, llm, on_event):
    return agent.answer(body.question, llm, body.lang, on_event, mode=body.mode)


def client_key(request: Request):
    forwarded = request.headers.get("x-forwarded-for", "")
    return forwarded.split(",")[0].strip() or (request.client.host if request.client else "unknown")


def rate_limited(request: Request):
    now = time.monotonic()
    hits = app.state.hits[client_key(request)]
    while hits and now - hits[0] > 60:
        hits.popleft()
    if len(hits) >= RATE_LIMIT:
        return True
    hits.append(now)
    return False


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    return response


@app.get("/api/health")
def health():
    count = tools.connection().cursor().execute("SELECT count(*) FROM catalog").fetchone()[0]
    return {"status": "ok", "tables": count, "model": model_name()}


@app.get("/api/catalog")
def catalog():
    keep = ["table_id", "survey", "year", "nisr_table_ref", "title", "unit", "geography_levels", "notes",
            "source_file_url", "report_page_url", "row_count"]
    return [{k: row[k] for k in keep} for row in tools.catalog_rows()]


class TranslateRequest(BaseModel):
    text: str = Field(min_length=1, max_length=3000)
    target: Literal["en", "rw"]


@app.post("/api/translate")
async def translate_answer(body: TranslateRequest, request: Request):
    """Switch the language of an answer already shown. Numbers must survive the translation unchanged."""
    if rate_limited(request):
        return JSONResponse({"error": "Too many requests in one minute. Please wait a moment and try again."}, status_code=429)
    try:
        llm = app.state.llm_factory()
        return await asyncio.wait_for(run_in_threadpool(agent.translate_answer, body.text, body.target, llm), timeout=ASK_TIMEOUT)
    except asyncio.TimeoutError:
        return JSONResponse({"error": "The translation took too long. Please try again."}, status_code=503)
    except LLMError as error:
        return JSONResponse({"error": str(error)}, status_code=503)
    except Exception:
        log.exception("translate failed")
        return JSONResponse({"error": "Something went wrong while translating. Please try again."}, status_code=500)


@app.post("/api/ask")
async def ask(body: AskRequest, request: Request):
    if rate_limited(request):
        return JSONResponse({"error": "Too many questions in one minute. Please wait a moment and try again."}, status_code=429)
    started = time.time()
    try:
        llm = app.state.llm_factory()
        result = await asyncio.wait_for(run_in_threadpool(run_agent, body, llm, None), timeout=timeout_for(body))
    except asyncio.TimeoutError:
        log.info("ask timeout latency=%.1f", time.time() - started)
        return JSONResponse({"error": "The answer took too long. Please try a simpler question."}, status_code=503)
    except LLMError as error:
        log.info("ask llm_error latency=%.1f", time.time() - started)
        return JSONResponse({"error": str(error)}, status_code=503)
    except Exception:
        log.exception("ask failed")
        return JSONResponse({"error": "Something went wrong while answering. Please try again."}, status_code=500)
    finish(result, body.mode)
    return result


def finish(result, mode):
    log.info("ask ok latency=%.1f tools=%s verified=%s", result["latency_s"],
             [s["tool"] for s in result["steps"]], result["verification"]["status"])
    try:
        question_log.record(result, mode)
    except OSError:
        log.warning("could not write question log")


@app.post("/api/ask/stream")
async def ask_stream(body: AskRequest, request: Request):
    """Same as /api/ask, but streams each agent step as a server-sent event, then the final result."""
    if rate_limited(request):
        return JSONResponse({"error": "Too many questions in one minute. Please wait a moment and try again."}, status_code=429)
    return stream_answer(body)


class BriefRequest(BaseModel):
    district: str = Field(min_length=2, max_length=40)
    lang: Literal["en", "rw"] = "en"


def brief_question(district):
    row = DISTRICT_BY_NAME[normalise_name(district)]
    province = row["province"] if row["province"] == "City of Kigali" else row["province"] + " Province"
    return (f"Write an evidence brief for {row['district']} district ({province}) for district planning (Imihigo). "
            f"Compare its key indicators (poverty, electricity, drinking water, sanitation, health insurance, internet, "
            f"smartphones, agricultural households) with {province} and with Rwanda. "
            f"Say where {row['district']} is furthest behind and where it does well.")


@app.post("/api/brief/stream")
async def brief_stream(body: BriefRequest, request: Request):
    """District brief agent: an investigation of one district, streamed."""
    if normalise_name(body.district) not in DISTRICT_BY_NAME:
        return JSONResponse({"error": "Unknown district. Choose one of Rwanda's 30 districts."}, status_code=422)
    if rate_limited(request):
        return JSONResponse({"error": "Too many requests in one minute. Please wait a moment and try again."}, status_code=429)
    ask_body = AskRequest(question=brief_question(body.district), lang=body.lang, mode="investigate")
    return stream_answer(ask_body, brief_for=DISTRICT_BY_NAME[normalise_name(body.district)]["district"])


@app.get("/api/districts")
def districts():
    return DISTRICTS


def stream_answer(body, brief_for=None):
    loop = asyncio.get_running_loop()
    queue = asyncio.Queue()

    def on_event(event):
        loop.call_soon_threadsafe(queue.put_nowait, event)

    async def run():
        try:
            llm = app.state.llm_factory()
            result = await asyncio.wait_for(run_in_threadpool(run_agent, body, llm, on_event), timeout=timeout_for(body))
            if brief_for:
                result["brief_district"] = brief_for
            finish(result, "brief" if brief_for else body.mode)
            await queue.put({"type": "result", "result": result})
        except asyncio.TimeoutError:
            await queue.put({"type": "error", "error": "The answer took too long. Please try a simpler question."})
        except LLMError as error:
            await queue.put({"type": "error", "error": str(error)})
        except Exception:
            log.exception("stream failed")
            await queue.put({"type": "error", "error": "Something went wrong while answering. Please try again."})

    async def events():
        task = asyncio.create_task(run())
        try:
            while True:
                event = await queue.get()
                yield f"data: {json.dumps(event, default=str, ensure_ascii=False)}\n\n"
                if event["type"] in {"result", "error"}:
                    break
        finally:
            task.cancel()

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/gaps")
def gaps():
    return question_log.summary()


app.mount("/", StaticFiles(directory=ROOT / "app/static", html=True), name="static")
