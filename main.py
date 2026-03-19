import os
import json
import aiohttp
import asyncio
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from bs4 import BeautifulSoup
from fastapi import Response

app = FastAPI()

SEARCH_URL = "https://www.crefia.or.kr/portal/store/cardTerminal/cardTerminalList.xx"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_FILE = os.path.join(BASE_DIR, "models.json")

# 🔥 Dooray Incoming Webhook
DOORAY_WEBHOOK_URL = "https://nhnent.dooray.com/services/3624879285692785039/4138653286819109563/u2TMOHzHRkufJM_GmEkKsQ"


# ------------------------------
# JSON 유틸
# ------------------------------
def load_models():
    if not os.path.exists(MODEL_FILE):
        return []
    with open(MODEL_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_models(models):
    with open(MODEL_FILE, "w", encoding="utf-8") as f:
        json.dump(models, f, ensure_ascii=False, indent=2)


def add_model_entry(entry: dict):
    models = load_models()

    # 🔹 중복 방지
    if not any(m.get("model") == entry.get("model") for m in models):
        models.append(entry)

    save_models(models)


def remove_model_entry(model_name: str):
    models = load_models()
    models = [m for m in models if m.get("model") != model_name]
    save_models(models)


# ------------------------------
# 크레피아 조회
# ------------------------------
async def fetch_model_info(model_name: str):
    async with aiohttp.ClientSession() as client:
        payload = {
            "searchKey": "03",
            "searchValue": model_name,
            "currentPage": "1"
        }

        async with client.post(SEARCH_URL, data=payload) as response:
            text = await response.text()
            soup = BeautifulSoup(text, "html.parser")

            rows = soup.select("table tbody tr")

            if not rows:
                return []

            results = []
            for row in rows:
                cols = row.find_all("td")
                if len(cols) >= 8:
                    cert_no = cols[2].text.strip()
                    identifier = cols[3].text.strip().split()[0]
                    model = cols[5].text.strip().split()[0]

                    date_parts = cols[6].text.strip().split()
                    cert_date = date_parts[0]
                    exp_date = date_parts[1] if len(date_parts) > 1 else ""

                    results.append({
                        "cert_no": cert_no,
                        "identifier": identifier,
                        "model": model,
                        "cert_date": cert_date,
                        "exp_date": exp_date
                    })

            return results


# ------------------------------
# Dooray 메시지 전송
# ------------------------------
async def send_dooray_message(text: str):
    try:
        async with aiohttp.ClientSession() as session:
            res = await session.post(DOORAY_WEBHOOK_URL, json={"text": text})
            print("✅ Dooray 응답:", res.status)
    except Exception as e:
        print("❌ 전송 실패:", e)


# ------------------------------
# 버튼 생성
# ------------------------------
async def send_model_buttons(models: list[str]):
    actions = []

    for m in models[:10]:
        actions.append({
            "name": m,
            "text": m,
            "type": "button",
            "value": m
        })

    payload = {
        "text": "어떤 모델을 등록할까요?",
        "attachments": [
            {
                "text": "모델 선택",
                "actions": actions
            }
        ]
    }

    async with aiohttp.ClientSession() as session:
        await session.post(DOORAY_WEBHOOK_URL, json=payload)


# ------------------------------
# 지연 메시지
# ------------------------------
async def send_delayed_message(sec: int):
    await asyncio.sleep(sec)
    await send_dooray_message(f"{sec}초 후 알림입니다!")


# ------------------------------
# 슬래시 커맨드
# ------------------------------
@app.post("/kselnoti")
async def kselnoti(request: Request):
    text = ""

    # form / json 대응
    try:
        form = await request.form()
        text = form.get("text")
    except:
        pass

    if not text:
        try:
            data = await request.json()
            text = data.get("text")
        except:
            pass

    text = (text or "").strip()
    print("DEBUG text:", text)

    if not text:
        return JSONResponse({"text": "⚠ 모델명을 입력해주세요."})

    # ------------------------------
    # 숫자 → 타이머
    # ------------------------------
    if text.isdigit():
        sec = int(text)
        asyncio.create_task(send_delayed_message(sec))

        return JSONResponse({
            "text": f"{sec}초 뒤에 알림을 보낼게요!"
        })

    # ------------------------------
    # 리스트 조회
    # ------------------------------
    if text.lower() == "list":
        models = load_models()
        if not models:
            return JSONResponse({"text": "등록된 모델이 없습니다."})

        names = [m["model"] for m in models]
        return JSONResponse({"text": "등록된 모델:\n" + "\n".join(names)})

    # ------------------------------
    # 모델 조회
    # ------------------------------
    results = await fetch_model_info(text)

    if not results:
        return JSONResponse({
            "text": f"❌ [{text}] 조회 결과 없음"
        })

    # 🔥 여러 모델이면 버튼
    model_names = list(set([r["model"] for r in results]))

    if len(model_names) > 1:
        asyncio.create_task(send_model_buttons(model_names))

        return JSONResponse({
            "text": "🔍 여러 모델이 발견되었습니다. 버튼에서 선택해주세요."
        })

    # 단일 결과
    r = results[0]

    return JSONResponse({
        "text": f"[{r['cert_no']}] {r['model']}\n"
                f"- 식별번호: {r['identifier']}\n"
                f"- 인증일자: {r['cert_date']}\n"
                f"- 만료일자: {r['exp_date']}"
    })


# ------------------------------
# 버튼 클릭 처리
# ------------------------------
@app.post("/kselnoti_action")
async def kselnoti_action(request: Request):
    data = await request.json()

    print("DEBUG action:", data)

    action_value = data.get("actionValue")

    if not action_value:
        return JSONResponse({"text": "❌ 선택값 없음"})

    # 다시 조회 후 저장
    results = await fetch_model_info(action_value)

    if not results:
        return JSONResponse({
            "text": f"❌ [{action_value}] 조회 실패"
        })

    r = results[0]

    add_model_entry(r)

    return JSONResponse({
        "text": f"✅ [{r['model']}] 등록 완료!",
        "deleteOriginal": True
    })


# ------------------------------
# 헬스체크
# ------------------------------
@app.api_route("/", methods=["GET", "HEAD"])
async def health_check():
    return {"status": "running"}