import os
import asyncio
import logging
from datetime import datetime
from fastapi import FastAPI, Request
import httpx
from bs4 import BeautifulSoup
import uvicorn

logging.basicConfig(level=logging.INFO)

app = FastAPI()

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
# 알림용 모델 리스트 (메모리)
# ------------------------------
noti_models = []  # dict 리스트 형태로 저장

# ------------------------------
# 헬스체크 루트
# ------------------------------
@app.api_route("/", methods=["GET", "HEAD"])
async def health_check(request: Request):
    if request.method == "HEAD":
        return {"status": "ok"}
    return {"status": "✅ KSELNOTI bot is running"}

# ------------------------------
# 모델 정보 조회 함수
# ------------------------------
async def fetch_model_info(model_name: str):
    payload = {"searchKey": "03", "searchValue": model_name, "currentPage": "1"}
    response = await client.post(SEARCH_URL, data=payload)
    soup = BeautifulSoup(response.text, "html.parser")
    rows = soup.select("table tbody tr")

    # 검색 결과 없음
    no_result_text = soup.get_text(strip=True)
    if "검색된 건이 없습니다." in no_result_text or not rows:
        return []

    results = []
    for row in rows[:10]:  # 최대 10개까지만
        cols = row.find_all("td")
        if len(cols) >= 8:
            cert_no = cols[2].text.strip()
            identifier = cols[3].text.strip().split()[0]
            model = cols[5].text.strip().split()[0]
            date_parts = cols[6].text.strip().split()
            cert_date = date_parts[0]
            exp_date = date_parts[1] if len(date_parts) > 1 else ""

            results.append({
                "model": model,
                "cert_no": cert_no,
                "identifier": identifier,
                "cert_date": cert_date,
                "exp_date": exp_date
            })
    return results

# ------------------------------
# /kselnoti 슬래시 커맨드
# ------------------------------
@app.post("/kselnoti")
async def kselnoti(request: Request):
    data = await request.json()
    logging.info(f"📥 Request Payload: {data}")

    text = data.get("text", "").strip()
    response_url = data.get("responseUrl")
    channel_id = data.get("channelId")

    if not text:
        return {"text": "모델명 또는 명령어를 입력해주세요. 예: /kselnoti +KTC-K501"}

    # help
    if text.lower() == "help":
        help_msg = (
            "📝 KSEL Notify 사용법:\n"
            "/kselnoti +모델명 → 모델 등록\n"
            "/kselnoti -모델명 → 모델 제거\n"
            "/kselnoti list → 등록된 모델 확인\n"
            "/kselnoti help → 도움말 보기"
        )
        return {"text": help_msg}

    # list
    if text.lower() == "list":
        if not noti_models:
            return {"text": "알림 리스트가 비어 있습니다."}
        lines = []
        for m in noti_models:
            lines.append(m["model"])
        return {"text": "현재 알림 리스트:\n" + "\n".join(lines)}

    # +모델 추가
    if text.startswith("+"):
        model = text[1:].strip()

        # 이미 등록되어 있는 경우
        if any(m["model"] == model for m in noti_models):
            return {"text": f"⚠️ 리스트에 이미 존재하는 모델명입니다: {model}"}

        # 크레피아 사이트 조회
        results = await fetch_model_info(model)

        if len(results) > 10:
            return {"text": f"⚠️ [{model}] 검색 결과가 10건 이상입니다. 정확한 모델명을 입력하세요."}
        elif len(results) == 0:
            noti_models.append({
                "model": model,
                "response_url": response_url,
                "channel_id": channel_id
            })
            return {"text": f"🆕 신규 모델로 등록합니다: {model}"}
        elif len(results) == 1:
            info = results[0]
            noti_models.append({
                "model": info["model"],
                "response_url": response_url,
                "channel_id": channel_id,
                "identifier": info["identifier"],
                "cert_date": info["cert_date"],
                "exp_date": info["exp_date"]
            })
            return {"text": f"✅ 모델 등록이 완료되었습니다: {info['model']}"}
        else:
            return {"text": f"⚠️ [{model}] 다수 검색되었습니다. 더 정확히 입력해주세요."}

    # -모델 제거
    if text.startswith("-"):
        model = text[1:].strip()
        before_count = len(noti_models)
        noti_models[:] = [m for m in noti_models if m["model"] != model]

        if len(noti_models) < before_count:
            return {"text": f"🗑️ [{model}] 모델명을 리스트에서 삭제합니다."}
        else:
            return {"text": f"⚠️ 리스트에 존재하지 않는 모델명입니다: {model}"}

    return {"text": "⚠️ 알 수 없는 명령입니다. `/kselnoti help`를 참고하세요."}

# ------------------------------
# 모델 변경 체크 주기 (08~20시 1시간마다)
# ------------------------------
async def monitor_changes():
    last_info = dict()
    while True:
        now = datetime.now()
        if 8 <= now.hour <= 20 and noti_models:
            for m in list(noti_models):
                model = m["model"]
                info_list = await fetch_model_info(model)
                info = info_list[0] if info_list else None

                if info is None and last_info.get(model) is not None:
                    logging.info(f"⚠️ [{model}] 검색 결과 없음 → 삭제")
                    noti_models.remove(m)
                    last_info.pop(model, None)
                elif info is not None:
                    if last_info.get(model) != info:
                        logging.info(f"⚡ [{model}] 변경 감지됨")
                        last_info[model] = info
        await asyncio.sleep(3600)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(monitor_changes())

# ------------------------------
# 서버 실행
# ------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
