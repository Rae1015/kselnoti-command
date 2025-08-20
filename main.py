import json
import os
import asyncio
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
import httpx
from bs4 import BeautifulSoup
import uvicorn

app = FastAPI()

# JSON 파일 경로
ALERT_LIST_FILE = "kselnoti_list.json"

# 최대 저장 모델 수
MAX_ALERTS = 20

# 도움말 메시지
HELP_MESSAGE = (
    "**/(노트모양)kselnoti 커맨드 사용법**\n"
    "`/kselnoti +모델명` : 알림 리스트에 모델 추가\n"
    "`/kselnoti -모델명` : 알림 리스트에서 모델 제거\n"
    "`/kselnoti list` : 현재 알림 리스트 확인\n"
    "`/kselnoti help` : 도움말"
)

# JSON 파일에서 리스트 불러오기
def load_alert_list():
    if not os.path.exists(ALERT_LIST_FILE):
        return []
    with open(ALERT_LIST_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return []

# JSON 파일에 리스트 저장
def save_alert_list(alert_list):
    with open(ALERT_LIST_FILE, "w", encoding="utf-8") as f:
        json.dump(alert_list[:MAX_ALERTS], f, ensure_ascii=False, indent=2)

@app.post("/kselnoti")
async def kselnoti_command(request: Request):
    data = await request.json()
    text = data.get("text", "").strip()

    # 도움말
    if not text or text.lower() == "help":
        return {"text": HELP_MESSAGE}

    alert_list = load_alert_list()

    # 리스트 확인
    if text.lower() == "list":
        if not alert_list:
            return {"text": "알림 리스트가 비어 있습니다."}
        return {"text": "현재 알림 리스트:\n" + "\n".join(alert_list)}

    # 모델 추가
    if text.startswith("+"):
        model_name = text[1:].strip()
        if model_name in alert_list:
            return {"text": f"모델 [{model_name}]는 이미 알림 리스트에 존재합니다."}
        alert_list.append(model_name)
        save_alert_list(alert_list)
        return {"text": f"모델 [{model_name}]를 알림 리스트에 추가했습니다."}

    # 모델 제거
    if text.startswith("-"):
        model_name = text[1:].strip()
        if model_name not in alert_list:
            return {"text": f"모델 [{model_name}]는 알림 리스트에 존재하지 않습니다."}
        alert_list.remove(model_name)
        save_alert_list(alert_list)
        return {"text": f"모델 [{model_name}]를 알림 리스트에서 제거했습니다."}

    # 알 수 없는 명령어
    return {"text": "알 수 없는 명령어입니다. `/kselnoti help`를 참고해주세요."}

# ------------------------------
# 서버 실행
# ------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
