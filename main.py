from fastapi import FastAPI, Form
from fastapi.responses import JSONResponse
from apscheduler.schedulers.background import BackgroundScheduler
import requests
from bs4 import BeautifulSoup
import json
import os
from datetime import datetime

app = FastAPI()

# -----------------------------
# 설정
# -----------------------------
DATA_FILE = "models.json"
WEBHOOK_URL = "여기에_두레이_웹훅_URL_입력"  # 두레이 채팅방 Webhook URL
CHECK_START = 8   # 시작시간 (08시)
CHECK_END = 20    # 종료시간 (20시)

# -----------------------------
# JSON 저장/로드
# -----------------------------
def load_models():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_models(models):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(models, f, ensure_ascii=False, indent=2)

# -----------------------------
# 두레이 메시지 전송
# -----------------------------
def send_private_message(response_url, text):
    """슬래시 명령어 입력자에게만 보이는 응답"""
    return JSONResponse(content={
        "response_type": "ephemeral",  # 개인 메시지
        "text": text
    })

def send_channel_message(text):
    """채팅방에 메시지 전송 (Webhook 이용)"""
    payload = {"text": text}
    requests.post(WEBHOOK_URL, json=payload)

# -----------------------------
# 크레피아 사이트 검색
# -----------------------------
def search_model(model_name: str):
    url = "https://www.crefia.or.kr/portal/store/cardTerminal/cardTerminalList.xx"
    res = requests.post(url, data={"searchCondition": "model", "searchKeyword": model_name})
    res.encoding = "utf-8"

    soup = BeautifulSoup(res.text, "html.parser")
    rows = soup.select("table.boardList > tbody > tr")

    results = []
    for row in rows[:10]:
        cols = row.find_all("td")
        if len(cols) >= 8:
            cert_no = cols[2].text.strip()
            identifier = cols[3].text.strip().split()[0]
            model = cols[5].text.strip().split()[0]
            date_parts = cols[6].text.strip().split()
            cert_date = date_parts[0]
            exp_date = date_parts[1] if len(date_parts) > 1 else ""

            if model == model_name:  # 정확히 일치하는 모델만
                results.append(
                    f"[{cert_no}] {model}\n"
                    f" - 식별번호 : {identifier}\n"
                    f" - 인증일자 : {cert_date}\n"
                    f" - 만료일자 : {exp_date}"
                )
    return results

# -----------------------------
# 모델 변경 체크
# -----------------------------
def check_updates():
    models = load_models()
    if not models:  # 리스트 비어있으면 스킵
        return

    now = datetime.now()
    if not (CHECK_START <= now.hour <= CHECK_END):
        return

    for model in models.copy():
        results = search_model(model)
        if results:
            message = "🔔 단말기 인증정보가 업데이트 되었습니다.\n" + "\n\n".join(results)
            send_channel_message(message)

            # 알림 후 리스트에서 제거
            models.remove(model)
            save_models(models)

# -----------------------------
# APScheduler 등록
# -----------------------------
scheduler = BackgroundScheduler()
scheduler.add_job(check_updates, "interval", hours=1)
scheduler.start()

# -----------------------------
# /kselnoti 커맨드 처리
# -----------------------------
@app.post("/kselnoti")
async def kselnoti(
    text: str = Form(""), 
    response_url: str = Form("")  # 두레이에서 넘겨주는 응답 URL
):
    models = load_models()

    if text.startswith("help"):
        return send_private_message(response_url, 
            "사용법:\n"
            "`/kselnoti +모델명` : 알림 리스트에 추가\n"
            "`/kselnoti -모델명` : 알림 리스트에서 제거\n"
            "`/kselnoti list` : 현재 알림 리스트 확인\n"
            "`/kselnoti help` : 도움말 보기"
        )

    elif text.startswith("+"):
        model = text[1:].strip()
        if model and model not in models:
            models.append(model)
            save_models(models)
            return send_private_message(response_url, f"✅ {model} 모델이 알림 리스트에 추가되었습니다.")
        else:
            return send_private_message(response_url, f"⚠️ {model} 모델은 이미 리스트에 있거나 잘못된 입력입니다.")

    elif text.startswith("-"):
        model = text[1:].strip()
        if model in models:
            models.remove(model)
            save_models(models)
            return send_private_message(response_url, f"❌ {model} 모델이 알림 리스트에서 제거되었습니다.")
        else:
            return send_private_message(response_url, f"⚠️ {model} 모델은 리스트에 없습니다.")

    elif text.strip() == "list":
        if models:
            return send_private_message(response_url, "📋 현재 알림 리스트:\n" + "\n".join(models))
        else:
            return send_private_message(response_url, "ℹ️ 현재 알림 리스트가 비어 있습니다.")

    else:
        return send_private_message(response_url, "⚠️ 잘못된 명령입니다. `/kselnoti help` 를 참고하세요.")
