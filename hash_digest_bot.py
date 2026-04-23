import os
import re
import json
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from openai import OpenAI

JST = timezone(timedelta(hours=9))
BASE_DIR = Path(__file__).resolve().parent
STATE_PATH = BASE_DIR / "state.json"
DOWNLOAD_DIR = BASE_DIR / "downloads"
DOWNLOAD_DIR.mkdir(exist_ok=True)

HASH_BASE_URL = "https://hash.jichitai.works"
SEARCH_URL = "https://hash.jichitai.works/search?sort=new"
LOGIN_URL = "https://hash.jichitai.works/login"

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

HASH_EMAIL = os.getenv("HASH_EMAIL", "")
HASH_PASSWORD = os.getenv("HASH_PASSWORD", "")

LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_USER_ID = os.getenv("LINE_USER_ID", "")

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def now_jst() -> datetime:
    return datetime.now(JST)


def iso_now_jst() -> str:
    return now_jst().isoformat()


def stable_id(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def load_state() -> Dict[str, Any]:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {
        "known_ids": [],
        "queue": [],
        "last_collect_at": None,
        "last_send_at": None,
    }


def save_state(state: Dict[str, Any]) -> None:
    STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def build_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    return s


def fetch_new_services() -> List[Dict[str, str]]:
    session = build_session()
    res = session.get(SEARCH_URL, timeout=30)
    res.raise_for_status()
    soup = BeautifulSoup(res.text, "html.parser")

    items: List[Dict[str, str]] = []
    seen = set()

    for a in soup.select('a[href^="/service/"]'):
        href = (a.get("href") or "").strip()
        if not href:
            continue

        url = href if href.startswith("http") else f"{HASH_BASE_URL}{href}"
        sid = stable_id(url)
        if sid in seen:
            continue
        seen.add(sid)

        title = normalize_whitespace(a.get_text(" ", strip=True))
        if not title:
            title = f"サービス {sid}"

        items.append(
            {
                "id": sid,
                "title": title,
                "url": url,
                "discovered_at": iso_now_jst(),
            }
        )

    return items


def collect_new_items() -> int:
    state = load_state()
    known_ids = set(state.get("known_ids", []))
    queued_ids = {item["id"] for item in state.get("queue", [])}

    fetched = fetch_new_services()
    new_items = [
        item for item in fetched
        if item["id"] not in known_ids and item["id"] not in queued_ids
    ]

    if new_items:
        state.setdefault("queue", []).extend(new_items)
        state["known_ids"] = list(known_ids.union(item["id"] for item in new_items))

    state["last_collect_at"] = iso_now_jst()
    save_state(state)
    return len(new_items)


def login_hash(page) -> None:
    if not HASH_EMAIL or not HASH_PASSWORD:
        raise RuntimeError("HASH_EMAIL / HASH_PASSWORD が未設定です")

    print("① ログインページへ移動", flush=True)
    page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)

    page.screenshot(path="debug_1.png", full_page=True)

    print("② ログインボタン待機", flush=True)
    page.wait_for_selector('a:has-text("ログイン")', timeout=10000)

    print("③ ログインボタンクリック", flush=True)
    page.locator('a:has-text("ログイン")').first.click(force=True)
    page.wait_for_timeout(3000)

    print("④ メール入力画面確認", flush=True)
    print("現在URL:", page.url)
    page.screenshot(path="debug_after_login_click.png", full_page=True)
    print("スクショ保存完了")
    page.wait_for_selector('input[type="email"], input[name="email"], input[type="text"]', timeout=15000)
    page.fill('input[type="email"]', HASH_EMAIL)
    print("⑤ メール入力完了", flush=True)

    page.locator('button:has-text("次へ"), button:has-text("Next"), button[type="submit"]').first.click()
    page.wait_for_timeout(3000)
    print("⑥ 次へクリック完了", flush=True)

    page.screenshot(path="debug_after_email_submit.png", full_page=True)

    page.wait_for_selector('input[type="password"]', timeout=15000)
    print("⑦ パスワード欄見つかった", flush=True)

    page.fill('input[type="password"]', HASH_PASSWORD)
    print("⑧ パスワード入力完了", flush=True)

    page.screenshot(path="debug_password_filled.png", full_page=True)
    email_selectors = [
        'input[type="email"]',
        'input[name="email"]',
        'input[name="mail"]',
        'input[placeholder*="メール"]',
        'input[autocomplete="username"]',
        'input[type="text"]',
        'input[name="login"]',
    ]

    password_selectors = [
        'input[type="password"]',
        'input[name="password"]',
        'input[name="passwd"]',
        'input[name="passwd"]',
        'input[name="pass"]',
        'input[id*="password"]',
        'input[placeholder*="パスワード"]',
        'input[autocomplete="current-password"]',
    ]

    email_filled = False
    for sel in email_selectors:
        try:
            page.locator(sel).first.wait_for(timeout=5000)
            page.locator(sel).first.fill(HASH_EMAIL)
            email_filled = True
            break
        except Exception:
            pass

    if not email_filled:
        page.screenshot(path="login_error.png", full_page=True)
        raise RuntimeError(
            "メール入力欄が見つかりませんでした。login_error.png を確認してください。"
        )

    next_button_selectors = [
        'button[type="submit"]',
        'input[type="submit"]',
        'button:has-text("次へ")',
        'button:has-text("続行")',
        'button:has-text("ログイン")',
        'text=次へ',
        'text=続行',
    ]

    for sel in next_button_selectors:
        try:
            page.locator(sel).first.click(timeout=3000)
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass

            try:
                page.wait_for_selector('input[type="password"]', timeout=10000)
            except Exception:
                pass

            page.wait_for_timeout(3000)
            break
        except Exception:
            pass

    password_filled = False
    for sel in password_selectors:
        try:
            page.locator(sel).first.wait_for(timeout=5000)
            page.locator(sel).first.fill(HASH_PASSWORD)
            password_filled = True
            break
        except Exception:
            pass

    if not password_filled:
        page.screenshot(path="login_error.png", full_page=True)
        raise RuntimeError(
            "パスワード入力欄が見つかりませんでした。login_error.png を確認してください。"
        )

    login_clicked = False
    button_selectors = [
        'button[type="submit"]',
        'input[type="submit"]',
        'button:has-text("ログイン")',
        'button:has-text("Sign in")',
        'text=ログイン',
    ]

    for sel in button_selectors:
        try:
            page.locator(sel).first.click(timeout=5000)
            login_clicked = True
            break
        except Exception:
            pass

    if not login_clicked:
        page.screenshot(path="login_error.png", full_page=True)
        raise RuntimeError(
            "ログインボタンが見つかりませんでした。login_error.png を確認してください。"
        )

    page.wait_for_load_state("networkidle", timeout=60000)
    page.wait_for_timeout(5000)


def try_download_by_locator(page, locator, service_id: str) -> Optional[Path]:
    try:
        with page.expect_download(timeout=15000) as download_info:
            locator.click()
        download = download_info.value
        filename = download.suggested_filename or f"{service_id}.pdf"
        if not filename.lower().endswith(".pdf"):
            filename = f"{filename}.pdf"
        target = DOWNLOAD_DIR / filename
        download.save_as(str(target))
        return target
    except PlaywrightTimeoutError:
        return None
    except Exception:
        return None


def download_pdf_for_service(page, service_url: str, service_id: str) -> Optional[Path]:
    page.goto(service_url, wait_until="networkidle")

    text_candidates = ["資料ダウンロード", "ダウンロード", "PDF", "資料請求"]
    for text in text_candidates:
        try:
            locator = page.get_by_text(text, exact=False).first
            path = try_download_by_locator(page, locator, service_id)
            if path:
                return path
        except Exception:
            pass

    for selector in ['a[href$=".pdf"]', 'a[href*="pdf"]', 'button', 'a']:
        for i in range(min(page.locator(selector).count(), 20)):
            try:
                locator = page.locator(selector).nth(i)
                label = normalize_whitespace(locator.inner_text(timeout=1000) or "")
                href = (
                    locator.get_attribute("href") or ""
                    if selector.startswith("a")
                    else ""
                )
                if (
                    "pdf" in label.lower()
                    or "ダウンロード" in label
                    or href.lower().endswith(".pdf")
                    or "pdf" in href.lower()
                ):
                    path = try_download_by_locator(page, locator, service_id)
                    if path:
                        return path
            except Exception:
                continue

    return None


def summarize_pdf(pdf_path: Path, title: str, url: str) -> str:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY が未設定です。")

    client = OpenAI(api_key=OPENAI_API_KEY)
    with pdf_path.open("rb") as f:
        uploaded = client.files.create(file=f, purpose="user_data")

    response = client.responses.create(
        model=OPENAI_MODEL,
        input=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            "以下の自治体向けPDF資料を日本語で簡潔に整理してください。\n"
                            "出力形式:\n"
                            "【何の資料か】1〜2文\n"
                            "【要点】3点\n"
                            "【自治体で確認したい点】3点\n"
                            "【議会・担当課ヒアリング論点】2点\n\n"
                            f"対象サービス名: {title}\n"
                            f"掲載URL: {url}"
                        ),
                    },
                    {
                        "type": "input_file",
                        "file_id": uploaded.id,
                    },
                ],
            }
        ],
    )
    return response.output_text.strip()


def push_line_message(text: str) -> None:
    if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_USER_ID:
        raise RuntimeError("LINE_CHANNEL_ACCESS_TOKEN / LINE_USER_ID が未設定です。")

    api_url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "to": LINE_USER_ID,
        "messages": [{"type": "text", "text": text[:5000]}],
    }
    res = requests.post(api_url, headers=headers, json=payload, timeout=30)
    res.raise_for_status()


def chunk_messages(blocks: List[str], header: str = "【HA×SH 新着資料要約】\n") -> List[str]:
    messages: List[str] = []
    current = header

    for block in blocks:
        candidate = f"{block}\n\n"
        if len(current) + len(candidate) > 4500:
            messages.append(current.rstrip())
            current = header + candidate
        else:
            current += candidate

    if current.strip():
        messages.append(current.rstrip())

    return messages


def send_digest() -> int:
    state = load_state()
    queue = state.get("queue", [])
    if not queue:
        return 0

    results: List[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()

        login_hash(page)

        for item in queue:
            pdf_path = download_pdf_for_service(page, item["url"], item["id"])
            if not pdf_path:
                results.append(
                    f"■ {item['title']}\n掲載URL: {item['url']}\n資料PDFの取得に失敗しました。"
                )
                continue

            try:
                summary = summarize_pdf(pdf_path, item["title"], item["url"])
                results.append(
                    f"■ {item['title']}\n掲載URL: {item['url']}\n\n{summary}"
                )
            except Exception as e:
                results.append(
                    f"■ {item['title']}\n掲載URL: {item['url']}\n要約処理に失敗しました: {e}"
                )

        browser.close()

    for msg in chunk_messages(results):
        push_line_message(msg)

    state["queue"] = []
    state["last_send_at"] = iso_now_jst()
    save_state(state)
    return len(results)


def main() -> None:
    print("send_digest開始", flush=True)
    mode = os.getenv("RUN_MODE", "collect_and_send")

    if mode == "collect":
        count = collect_new_items()
        print(f"Collected {count} new items.")
    elif mode == "send":
        count = send_digest()
        print(f"Sent {count} digest items.")
    elif mode == "collect_and_send":
        new_count = collect_new_items()
        sent_count = send_digest()
        print(f"Collected {new_count} new items, sent {sent_count} digest items.")
    else:
        raise ValueError(f"Unknown RUN_MODE: {mode}")


if __name__ == "__main__":
    main()
