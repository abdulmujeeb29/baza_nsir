import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
CHROME_PATHS = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "google-chrome", "chromium", "chromium-browser"]


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server():
    port = free_port()
    env = {**os.environ, "APP_ENV": "test", "PORT": str(port)}
    process = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port)], cwd=ROOT, env=env,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    for _ in range(60):
        try:
            if httpx.get(base + "/api/health", timeout=1).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.25)
    yield base
    process.terminate()
    process.wait(timeout=10)


def test_page_loads(server):
    html = httpx.get(server + "/").text
    assert "Baza NISR" in html
    assert 'id="question"' in html
    assert '<script src="/app.js"' in html
    assert "National Institute of Statistics of Rwanda" in html
    assert "—" not in html
    for asset in ["/app.js", "/styles.css"]:
        assert httpx.get(server + asset).status_code == 200


def test_static_text_has_no_em_dash():
    for name in ["index.html", "app.js", "styles.css"]:
        assert "—" not in (ROOT / "app/static" / name).read_text(encoding="utf-8")


def find_chrome():
    for path in CHROME_PATHS:
        if Path(path).exists() or shutil.which(path):
            return path
    return None


def test_headless_answer_card(server, tmp_path):
    chrome = find_chrome()
    if not chrome:
        pytest.skip("no Chrome or Chromium available for the headless check")
    url = server + "/?q=Which%20district%20has%20the%20highest%20poverty%20rate%3F"
    # Real-time waits (streaming responses do not finish under virtual time). A cold Chrome start can be slow,
    # so retry with longer waits; the assertions below are unchanged.
    for wait_ms in (10000, 20000, 30000):
        common = [chrome, "--headless=new", "--disable-gpu", "--no-first-run", f"--user-data-dir={tmp_path}", f"--timeout={wait_ms}"]
        dom = subprocess.run(common + ["--dump-dom", url], capture_output=True, text=True, timeout=120).stdout
        if "Test mode answer" in dom:
            break
    assert "Test mode answer" in dom
    assert 'class="badge mono ok"' in dom
    assert 'class="num"' in dom and 'data-ref="A9.23' in dom  # verified numbers are framed with their table
    assert "statistics.gov.rw/sites/default/files" in dom
    shot = tmp_path / "test_mode_answer.png"
    subprocess.run(common + ["--window-size=1100,1500", f"--screenshot={shot}", url], capture_output=True, timeout=90)
    assert shot.exists()


def test_embed_script_served(server):
    js = httpx.get(server + "/embed.js")
    assert js.status_code == 200
    assert "?embed=1" in js.text and "Ask NISR data" in js.text
    assert httpx.get(server + "/embed-demo.html").status_code == 200
    assert "/embed.js" in httpx.get(server + "/embed-demo.html").text
