import os
import asyncio
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
import httpx
from bs4 import BeautifulSoup
import uvicorn

app = FastAPI()

# ------------------------------
# 전역 AsyncClient
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
# 헬스체크
# ------------------------------
@app.api_route("/", methods=["GET", "HEAD"])
async def health_check(request: Request):
    if request.method == "HEAD":
        return Response(status_code=200)
    return JSONResponse({"status": "✅ KSEL bot is running"})

# ------------------------------
# 크레피아 모델 정보 조회
# ------------------------------
async def fetch_model_info(model_name: str) -> list[str]:
    """
    모델명을 검색하고 결과를 리스트로 반환
    """
    payload = {"searchKey": "03", "searchValue": model_name, "currentPage": "1"}
    response = await client.post(SEARCH_URL, data=payload)
    soup = BeautifulSoup(response.text, "html.parser")
    rows = soup.select("table tbody tr")

    # 검색 결과 없음
    if "검색된 건이 없습니다." in soup.get_text(strip=True) or not rows:
        return []

    results = []
    for row in rows[:10]:  # 최대 10개
        cols = row.find_all("td")
        if len(cols) >= 8:
            model = cols[5].text.strip().split()[0]
            results.append(model)

    return results

# ------------------------------
# /kselnoti 슬래시 커맨드
# ------------------------------
@app.post("/kselnoti")
async def kselnoti_command(request: Request):
    data = await request.json()
    model_name = data.get("text", "").strip()

    if not model_name:
        return {"deleteOriginal": True, "text": "모델명을 입력해주세요. 예: /kselnoti ktc-k501"}

    try:
        search_result = await asyncio.wait_for(fetch_model_info(model_name), timeout=3.0)

        # 검색 결과 없음
        if len(search_result) == 0:
            return {
                "deleteOriginal": True,
                "text": f"🔍 [{model_name}] 검색 결과가 없습니다.",
                "attachments": [
                    {
                        "actions": [
                            {"type": "button", "text": "신규등록", "name": "new", "value": model_name},
                            {"type": "button", "text": "종료", "name": "close", "value": model_name},
                        ]
                    }
                ]
            }

        # 검색 결과 1개
        elif len(search_result) == 1:
            model = search_result[0]
            return {
                "deleteOriginal": True,
                "text": f"✅ [{model}] 검색 결과 1개",
                "attachments": [
                    {
                        "actions": [
                            {"type": "button", "text": "등록", "name": "add", "value": model},
                            {"type": "button", "text": "종료", "name": "close", "value": model},
                        ]
                    }
                ]
            }

        # 검색 결과 여러개 (최대 10개)
        else:
            buttons = [{"type": "button", "text": m, "name": "select", "value": m} for m in search_result[:10]]
            return {
                "deleteOriginal": True,
                "text": f"🔍 [{model_name}] 검색 결과 {len(search_result)}개",
                "attachments": [{"actions": buttons}]
            }

    except asyncio.TimeoutError:
        return {"deleteOriginal": True, "text": f"⚠️ [{model_name}] 조회 중 응답 지연. 잠시 후 다시 시도해주세요."}

# ------------------------------
# 서버 실행
# ------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
