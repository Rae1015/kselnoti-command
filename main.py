import os
import asyncio
from datetime import datetime
from fastapi import FastAPI, Request
import httpx
from bs4 import BeautifulSoup
import uvicorn

app = FastAPI()

# ------------------------------
# 두레이 Webhook
# ------------------------------
DOORAY_WEBHOOK_URL = os.environ.get("DOORAY_WEBHOOK_URL")

async def send_dooray_message(message: str):
    """
    두레이 Webhook으로 메시지 전송
    """
    if not DOORAY_WEBHOOK_URL:
        print("⚠️ DOORAY_WEBHOOK_URL 환경변수가 설정되지 않았습니다.")
        return

    payload = {"text": message}
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(DOORAY_WEBHOOK_URL, json=payload)
            if resp.status_code == 200:
                print(f"✅ 메시지 전송 성공: {message}")
            else:
                print(f"⚠️ 메시지 전송 실패: {resp.status_code}")
        except Exception as e:
            print(f"❌ 메시지 전송 중 오류: {e}")

# ------------------------------
# 전역 AsyncClient (연결 풀)
# ------------------------------
client = httpx.AsyncClient(
    timeout=5.0,
    limits=httpx.Limits(
        max_connections=10,
        max_keepalive_connections=5,
        keepalive_expiry=30.0
    )
)

SEARCH_URL = "https://www.crefia.or.kr/portal/store/cardTerminal/cardTerminalList.xx"

# ------------------------------
# 알림용 모델 리스트
# ------------------------------
noti_models = set()  # 최대 20개

# ------------------------------
# 헬스체크 루트
# ------------------------------
@app.api_route("/", methods=["GET", "HEAD"])
async def health_check(request: Request):
    if request.method == "HEAD":
        return {"status": "ok"}  # UptimeRobot HEAD 대응
    return {"status": "✅ KSELNOTI bot is running"}

# ------------------------------
# 모델 정보 조회 함수
# ------------------------------
async def fetch_model_info(model_name: str):
    payload = {"searchKey": "03", "searchValue": model_name, "currentPage": "1"}
    response = await client.post(SEARCH_URL, data=payload)
    soup = BeautifulSoup(response.text, "html.parser")
    rows = soup.select("table tbody tr")

    # 검색 결과 확인
    no_result_text = soup.get_text(strip=True)
    if "검색된 건이 없습니다." in no_result_text or not rows:
        return None

    for row in rows[:10]:
        cols = row.find_all("td")
        if len(cols) >= 8:
            model = cols[5].text.strip().split()[0]
            if model == model_name:
                cert_no = cols[2].text.strip()
                identifier = cols[3].text.strip().split()[0]
                date_parts = cols[6].text.strip().split()
                cert_date = date_parts[0]
                exp_date = date_parts[1] if len(date_parts) > 1 else ""
                return (
                    f"[{cert_no}] {model}\n"
                    f" - 식별번호 : {identifier}\n"
                    f" - 인증일자 : {cert_date}\n"
                    f" - 만료일자 : {exp_date}"
                )
    return None

# ------------------------------
# /kselnoti 슬래시 커맨드
# ------------------------------
@app.post("/kselnoti")
async def kselnoti(request: Request):
    data = await request.json()
    text = data.get("text", "").strip()

    if not text:
        return {"text": "모델명 또는 명령어를 입력해주세요. 예: /kselnoti +KTC-K501"}

    # help
    if text.lower() == "help":
        help_msg = (
            "📝 KSEL Notify 사용법:\n"
            "/kselnoti 모델명 → 모델 등록\n"
            "/kselnoti remove 모델명 → 모델 제거\n"
            "/kselnoti list → 등록된 모델 확인\n"
            "/kselnoti help → 도움말 보기"
        )
        return {"text": help_msg}

    # list
    if text.lower() == "list":
        if not noti_models:
            return {"text": "알림 리스트가 비어 있습니다."}
        return {"text": "현재 알림 리스트:\n" + "\n".join(noti_models)}

    # +모델 추가
    if text.startswith("+"):
        model = text[1:].strip()
        if len(noti_models) >= 20:
            return {"text": "⚠️ 알림 리스트는 최대 20개까지 등록 가능합니다."}
        noti_models.add(model)
        return {"text": f"✅ [{model}] 모델이 알림 리스트에 추가되었습니다."}

    # -모델 제거
    if text.startswith("-"):
        model = text[1:].strip()
        noti_models.discard(model)
        return {"text": f"✅ [{model}] 모델이 알림 리스트에서 제거되었습니다."}

    return {"text": "⚠️ 알 수 없는 명령입니다. `/kselnoti help`를 참고하세요."}

# ------------------------------
# 모델 변경 체크 주기 (08~20시 1시간마다)
# ------------------------------
async def monitor_changes():
    last_info = dict()
    while True:
        now = datetime.now()
        if 8 <= now.hour <= 20 and noti_models:
            for model in list(noti_models):
                info = await fetch_model_info(model)
                # 변경 감지
                if info is None and last_info.get(model) is not None:
                    await send_dooray_message(f"⚠️ 단말기 인증정보가 업데이트 되었습니다.\n[{model}] 검색 결과가 더 이상 없습니다.")
                    noti_models.discard(model)
                    last_info.pop(model, None)
                elif info is not None:
                    if last_info.get(model) != info:
                        await send_dooray_message(f"⚡ 단말기 인증정보가 업데이트 되었습니다.\n{info}")
                        noti_models.discard(model)
                        last_info[model] = info
        await asyncio.sleep(3600)  # 1시간마다 체크

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(monitor_changes())

# ------------------------------
# 서버 실행
# ------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
