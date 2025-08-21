import logging
from fastapi import FastAPI, Request
import httpx
import os

app = FastAPI()
logging.basicConfig(level=logging.INFO)

# ✅ 임시 DB (실제 서비스에서는 DB 연결 필요)
registered_models = set()

# 🔑 Dooray App Token (환경변수 사용 권장)
DOORAY_APP_TOKEN = os.getenv("DOORAY_APP_TOKEN", "your-app-token")

DOORAY_API_URL = "https://nhnent.dooray.com/messenger/api/commands/v1/send"

# ========================
# 🔹 Dooray 메시지 전송 함수
# ========================
async def send_dooray_message(channel_id: str, text: str, buttons=None):
    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "Authorization": f"dooray-api {DOORAY_APP_TOKEN}"
    }

    payload = {
        "botName": "TerminalBot",
        "botIconImage": "https://static.thenounproject.com/png/740742-200.png",
        "channelId": channel_id,
        "text": text,
    }

    if buttons:
        payload["attachments"] = [
            {
                "text": "선택하세요",
                "actions": buttons
            }
        ]

    logging.info(f"📤 Dooray Send Payload: {payload}")

    async with httpx.AsyncClient() as client:
        resp = await client.post(DOORAY_API_URL, headers=headers, json=payload)
        logging.info(f"✅ Dooray Response: {resp.status_code} {resp.text}")
        return resp.status_code, resp.text

# ========================
# 🔹 크레피아 검색 (Dummy 예시)
# ========================
def search_model_in_crefia(model_name: str):
    # 👉 실제 크롤링/검색 로직으로 교체 필요
    if model_name == "dup-model":
        return ["KTC-K501", "KTC-K502"]  # 여러 개
    elif model_name == "exist-model":
        return ["KTC-K501"]  # 1개
    else:
        return []  # 없음

# ========================
# 🔹 Dooray Slash Command 처리
# ========================
@app.post("/kselnoti")
async def kselnoti_handler(request: Request):
    data = await request.json()
    logging.info(f"📥 Request Payload: {data}")

    channel_id = data.get("channelId")
    text = data.get("text", "").strip()
    model_name = text

    if not model_name:
        await send_dooray_message(channel_id, "❌ 모델명을 입력해주세요. 예: `/kselnoti KTC-K501`")
        return {"ok": True}

    # 1️⃣ 리스트에 존재 여부 확인
    if model_name in registered_models:
        buttons = [
            {
                "name": "remove",
                "text": "제거",
                "type": "button",
                "value": model_name
            }
        ]
        await send_dooray_message(channel_id, f"⚠️ 리스트에 [{model_name}] 모델명이 이미 존재합니다. 제거할까요?", buttons)
        return {"ok": True}

    # 2️⃣ 리스트에 없음 → 크레피아 검색
    results = search_model_in_crefia(model_name)

    if len(results) == 0:
        registered_models.add(model_name)
        await send_dooray_message(channel_id, f"✅ 신규 모델명 [{model_name}] 등록 완료")
    elif len(results) == 1:
        registered_models.add(results[0])
        await send_dooray_message(channel_id, f"✅ 모델명 [{results[0]}] 등록 완료")
    else:
        buttons = [
            {
                "name": "register",
                "text": result,
                "type": "button",
                "value": result
            } for result in results
        ]
        await send_dooray_message(channel_id, f"🔎 등록할 모델을 선택해주세요", buttons)

    return {"ok": True}

# ========================
# 🔹 버튼 클릭 Callback 처리
# ========================
@app.post("/kselnoti-action")
async def kselnoti_action_handler(request: Request):
    data = await request.json()
    logging.info(f"🖱️ Button Click Payload: {data}")

    action = data.get("actionName")
    value = data.get("value")
    channel_id = data.get("channelId")

    if action == "remove":
        if value in registered_models:
            registered_models.remove(value)
            await send_dooray_message(channel_id, f"🗑️ 모델명 [{value}] 제거 완료")
        else:
            await send_dooray_message(channel_id, f"⚠️ 모델명 [{value}] 은 리스트에 없습니다.")
    elif action == "register":
        registered_models.add(value)
        await send_dooray_message(channel_id, f"✅ 모델명 [{value}] 등록 완료")

    return {"ok": True}
