import os
import json
import aiohttp
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from bs4 import BeautifulSoup

# ------------------------------
# 설정
# ------------------------------
SEARCH_URL = "https://www.crefia.or.kr/portal/store/cardTerminal/cardTerminalList.xx"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_FILE = os.path.join(BASE_DIR, "models.json")

DOORAY_WEBHOOK_URL = "https://nhnent.dooray.com/services/3624879285692785039/4138653286819109563/u2TMOHzHRkufJM_GmEkKsQ"

# 슬래시 커맨드 응답 URL (두레이가 요청 시 보내주는 responseUrl 사용 권장, 없으면 webhook fallback)
# 버튼 클릭 콜백을 받을 서버 주소 (본인 서버 URL로 변경)
SERVER_BASE_URL = os.environ.get("SERVER_BASE_URL", "https://your-server.example.com")

CHECK_INTERVAL_SECONDS = 3600  # 1시간


# ------------------------------
# 수명주기: 앱 시작 시 스케줄러 실행
# ------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(monitor_loop())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(lifespan=lifespan)


# ------------------------------
# JSON 유틸
# ------------------------------
def load_models() -> list[dict]:
    if not os.path.exists(MODEL_FILE):
        return []
    with open(MODEL_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_models(models: list[dict]):
    with open(MODEL_FILE, "w", encoding="utf-8") as f:
        json.dump(models, f, ensure_ascii=False, indent=2)


def add_model_entry(entry: dict):
    """모델 등록. 중복 시 기존 데이터 유지."""
    models = load_models()
    if not any(m.get("model") == entry.get("model") for m in models):
        models.append(entry)
        save_models(models)
        return True
    return False  # 이미 등록됨


def remove_model_entry(model_name: str) -> bool:
    models = load_models()
    new_models = [m for m in models if m.get("model") != model_name]
    if len(new_models) == len(models):
        return False  # 없던 모델
    save_models(new_models)
    return True


def update_model_snapshot(model_name: str, new_data: dict):
    """저장된 모델의 스냅샷을 최신 데이터로 갱신."""
    models = load_models()
    for m in models:
        if m.get("model") == model_name:
            m.update(new_data)
            break
    save_models(models)


# ------------------------------
# 크레피아 조회
# ------------------------------
async def fetch_model_info(model_name: str) -> list[dict]:
    try:
        async with aiohttp.ClientSession() as client:
            payload = {
                "searchKey": "03",
                "searchValue": model_name,
                "currentPage": "1"
            }
            async with client.post(SEARCH_URL, data=payload, timeout=aiohttp.ClientTimeout(total=15)) as response:
                text = await response.text()
                soup = BeautifulSoup(text, "html.parser")

                rows = soup.select("table tbody tr")
                if not rows:
                    return []

                results = []
                for row in rows:
                    cols = row.find_all("td")
                    if len(cols) >= 8:
                        cert_no   = cols[2].text.strip()
                        identifier = cols[3].text.strip().split()[0]
                        model     = cols[5].text.strip().split()[0]

                        date_parts = cols[6].text.strip().split()
                        cert_date  = date_parts[0]
                        exp_date   = date_parts[1] if len(date_parts) > 1 else ""

                        # 인증 상태 (승인 / 취소 등) - 컬럼 수에 따라 조정
                        status = cols[7].text.strip() if len(cols) > 7 else ""

                        results.append({
                            "cert_no":    cert_no,
                            "identifier": identifier,
                            "model":      model,
                            "cert_date":  cert_date,
                            "exp_date":   exp_date,
                            "status":     status,
                        })
                return results
    except Exception as e:
        print(f"❌ fetch_model_info 오류: {e}")
        return []


# ------------------------------
# 두레이 메시지 전송
# ------------------------------
async def send_dooray_message(text: str):
    try:
        async with aiohttp.ClientSession() as session:
            res = await session.post(DOORAY_WEBHOOK_URL, json={"text": text})
            print("✅ Dooray 응답:", res.status)
    except Exception as e:
        print(f"❌ Dooray 전송 실패: {e}")


# ------------------------------
# 등록 확인 버튼 전송 (Interactive Message)
# 단일 모델 → "등록할까요?" Yes/No 버튼
# 복수 모델 → 모델 선택 버튼
# ------------------------------
async def send_confirm_buttons(model_name: str, info: dict):
    """단일 모델 발견 시 등록 여부를 묻는 버튼."""
    payload = {
        "text": (
            f"🔍 *{model_name}* 조회 결과\n"
            f"- 인증번호: {info['cert_no']}\n"
            f"- 식별번호: {info['identifier']}\n"
            f"- 인증일자: {info['cert_date']}\n"
            f"- 만료일자: {info['exp_date']}\n"
            f"- 상태: {info.get('status', '-')}\n\n"
            "이 모델을 알림 등록할까요?"
        ),
        "attachments": [
            {
                "callbackId": "register_confirm",
                "actions": [
                    {
                        "name":  "register",
                        "text":  "✅ 등록",
                        "type":  "button",
                        "value": f"register:{model_name}",
                        "style": "primary",
                    },
                    {
                        "name":  "cancel",
                        "text":  "❌ 취소",
                        "type":  "button",
                        "value": f"cancel:{model_name}",
                        "style": "danger",
                    },
                ],
            }
        ],
    }
    async with aiohttp.ClientSession() as session:
        await session.post(DOORAY_WEBHOOK_URL, json=payload)


async def send_model_select_buttons(model_names: list[str]):
    """복수 모델 발견 시 선택 버튼."""
    actions = [
        {
            "name":  m,
            "text":  m,
            "type":  "button",
            "value": f"select:{m}",
        }
        for m in model_names[:10]
    ]
    payload = {
        "text": f"🔍 {len(model_names)}개 모델이 검색됐습니다. 알림 등록할 모델을 선택하세요.",
        "attachments": [
            {
                "callbackId": "model_select",
                "text": "모델 선택",
                "actions": actions,
            }
        ],
    }
    async with aiohttp.ClientSession() as session:
        await session.post(DOORAY_WEBHOOK_URL, json=payload)


# ------------------------------
# 1시간 주기 모니터링
# ------------------------------
async def monitor_loop():
    """서버 시작 후 1시간마다 등록된 모든 모델의 정보를 확인하고 변경 시 알림."""
    print("✅ 모니터링 스케줄러 시작")
    while True:
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)
        await check_all_models()


async def check_all_models():
    models = load_models()
    if not models:
        return

    print(f"🔄 {len(models)}개 모델 모니터링 중...")

    for saved in models:
        model_name = saved.get("model")
        if not model_name:
            continue

        results = await fetch_model_info(model_name)
        if not results:
            print(f"  ⚠ {model_name}: 조회 실패 (사이트 미응답 또는 삭제됨)")
            continue

        # 정확히 일치하는 모델 행만 추출
        matched = [r for r in results if r["model"] == model_name]
        if not matched:
            continue

        latest = matched[0]
        changed_fields = detect_changes(saved, latest)

        if changed_fields:
            await notify_change(model_name, saved, latest, changed_fields)
            update_model_snapshot(model_name, latest)


def detect_changes(old: dict, new: dict) -> list[str]:
    """변경된 필드 목록 반환."""
    watch_fields = ["cert_no", "cert_date", "exp_date", "status", "identifier"]
    return [f for f in watch_fields if old.get(f) != new.get(f)]


async def notify_change(model_name: str, old: dict, new: dict, changed_fields: list[str]):
    lines = [f"🔔 *{model_name}* 정보가 업데이트됐습니다!\n"]
    label_map = {
        "cert_no":    "인증번호",
        "identifier": "식별번호",
        "cert_date":  "인증일자",
        "exp_date":   "만료일자",
        "status":     "상태",
    }
    for field in changed_fields:
        label = label_map.get(field, field)
        lines.append(f"- {label}: {old.get(field, '-')} → {new.get(field, '-')}")

    await send_dooray_message("\n".join(lines))


# ------------------------------
# /kselnoti  슬래시 커맨드
# 사용법:
#   /kselnoti <모델명>    → 조회 후 등록 여부 확인
#   /kselnoti list        → 등록된 모델 목록
#   /kselnoti remove <모델명> → 등록 해제
# ------------------------------
@app.post("/kselnoti")
async def kselnoti(request: Request):
    # form-data (두레이 슬래시 커맨드) 또는 JSON 모두 지원
    text = ""
    try:
        form = await request.form()
        text = form.get("text", "")
    except Exception:
        pass

    if not text:
        try:
            body = await request.json()
            text = body.get("text", "")
        except Exception:
            pass

    text = (text or "").strip()
    print("DEBUG text:", text)

    if not text:
        return JSONResponse({
            "text": (
                "⚠ 사용법:\n"
                "- `/kselnoti <모델명>` : 조회 후 알림 등록\n"
                "- `/kselnoti list` : 등록 목록 보기\n"
                "- `/kselnoti remove <모델명>` : 등록 해제"
            )
        })

    # ── remove 커맨드 ──────────────────────────────
    if text.lower().startswith("remove "):
        target = text[7:].strip()
        if remove_model_entry(target):
            return JSONResponse({"text": f"🗑 [{target}] 알림 해제됐습니다."})
        else:
            return JSONResponse({"text": f"⚠ [{target}] 등록된 모델이 아닙니다."})

    # ── list 커맨드 ────────────────────────────────
    if text.lower() == "list":
        models = load_models()
        if not models:
            return JSONResponse({"text": "📋 등록된 모델이 없습니다."})
        lines = ["📋 *등록된 알림 모델 목록*"]
        for m in models:
            lines.append(
                f"- {m['model']} | 인증일: {m.get('cert_date','-')} | "
                f"만료일: {m.get('exp_date','-')} | 상태: {m.get('status','-')}"
            )
        return JSONResponse({"text": "\n".join(lines)})

    # ── 모델 조회 ──────────────────────────────────
    results = await fetch_model_info(text)

    if not results:
        return JSONResponse({"text": f"❌ [{text}] 크레피아에서 조회 결과가 없습니다."})

    model_names = list(dict.fromkeys(r["model"] for r in results))  # 순서 유지 중복 제거

    if len(model_names) == 1:
        # 단일 → 등록 확인 버튼 (webhook으로 별도 전송)
        asyncio.create_task(send_confirm_buttons(model_names[0], results[0]))
        return JSONResponse({"text": f"🔍 [{model_names[0]}] 조회 완료. 두레이 채널을 확인해주세요."})
    else:
        # 복수 → 선택 버튼
        asyncio.create_task(send_model_select_buttons(model_names))
        return JSONResponse({"text": f"🔍 {len(model_names)}개 모델 발견. 두레이 채널에서 선택해주세요."})


# ------------------------------
# /kselnoti_action  버튼 클릭 콜백
# 두레이가 버튼 클릭 시 POST로 호출
# ------------------------------
@app.post("/kselnoti_action")
async def kselnoti_action(request: Request):
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"text": "❌ 잘못된 요청"})

    print("DEBUG action:", data)

    # 두레이 Interactive Message 콜백 구조:
    # { "callbackId": "...", "actionValue": "register:MODEL_NAME", ... }
    action_value: str = data.get("actionValue", "")

    if not action_value:
        return JSONResponse({"text": "❌ 액션 값이 없습니다."})

    # ── select: (복수 모델 선택) ───────────────────
    if action_value.startswith("select:"):
        model_name = action_value[7:]
        results = await fetch_model_info(model_name)
        matched = [r for r in results if r["model"] == model_name]
        if not matched:
            return JSONResponse({"text": f"❌ [{model_name}] 재조회 실패"})

        asyncio.create_task(send_confirm_buttons(model_name, matched[0]))
        return JSONResponse({
            "text": f"🔍 [{model_name}] 상세 정보를 확인하세요.",
            "deleteOriginal": True,
        })

    # ── register: (등록 확인) ──────────────────────
    if action_value.startswith("register:"):
        model_name = action_value[9:]
        results = await fetch_model_info(model_name)
        matched = [r for r in results if r["model"] == model_name]
        if not matched:
            return JSONResponse({"text": f"❌ [{model_name}] 조회 실패"})

        r = matched[0]
        added = add_model_entry(r)

        if added:
            return JSONResponse({
                "text": f"✅ [{model_name}] 알림 등록 완료! 1시간마다 변경 여부를 모니터링합니다.",
                "deleteOriginal": True,
            })
        else:
            return JSONResponse({
                "text": f"ℹ [{model_name}] 이미 등록된 모델입니다.",
                "deleteOriginal": True,
            })

    # ── cancel: (등록 취소) ────────────────────────
    if action_value.startswith("cancel:"):
        model_name = action_value[7:]
        return JSONResponse({
            "text": f"↩ [{model_name}] 등록을 취소했습니다.",
            "deleteOriginal": True,
        })

    return JSONResponse({"text": f"❓ 알 수 없는 액션: {action_value}"})


# ------------------------------
# 헬스체크
# ------------------------------
@app.api_route("/", methods=["GET", "HEAD"])
async def health_check():
    return {"status": "running"}
