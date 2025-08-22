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


@app.api_route("/", methods=["GET", "HEAD"])
async def health_check(request: Request):
    if request.method == "HEAD":
        return Response(status_code=200)
    return JSONResponse({"status": "✅ KSEL bot is running"})


# ------------------------------
# 크레피아 모델 정보 조회
# ------------------------------
async def fetch_model_info(model_name: str) -> list:
    payload = {"searchKey": "03", "searchValue": model_name, "currentPage": "1"}
    response = await client.post(SEARCH_URL, data=payload)
    soup = BeautifulSoup(response.text, "html.parser")
    rows = soup.select("table tbody tr")

    results = []
    if "검색된 건이 없습니다." in soup.get_text(strip=True) or not rows:
        return results

    for row in rows:
        cols = row.find_all("td")
        if len(cols) >= 8:
            model = cols[5].text.strip().split()[0]
            results.append(model)
    return results


# ------------------------------
# 두레이 메시지 포맷 생성
# ------------------------------
def build_message(model_name: str, results: list) -> dict:
    if not results:
        # 검색 결과 없음
        return {
            "deleteOriginal": True,
            "text": f"🔍 [{model_name}] 검색 결과가 없습니다.",
            "attachments": [
                {
                    "title": "선택해주세요",
                    "actions": [
                        {"type": "button", "text": "신규등록", "value": "new"},
                        {"type": "button", "text": "종료", "value": "exit"}
                    ]
                }
            ]
        }

    elif len(results) == 1:
        # 검색 결과 1개
        return {
            "deleteOriginal": True,
            "text": f"✅ 검색 결과: {results[0]}",
            "attachments": [
                {
                    "title": f"{results[0]} 를 선택했습니다",
                    "actions": [
                        {"type": "button", "text": "등록", "value": "register"},
                        {"type": "button", "text": "종료", "value": "exit"}
                    ]
                }
            ]
        }

    else:
        # 검색 결과 다수 → 입력한 모델명과 길이가 같은 항목만 필터링
        filtered = [r for r in results if len(r) == len(model_name)]
        if not filtered:
            filtered = results  # 없으면 전체 그대로 사용

        return {
            "deleteOriginal": True,
            "text": f"🔍 다수의 결과가 검색되었습니다. ({len(filtered)}건)",
            "attachments": [
                {
                    "title": "모델명을 선택하세요",
                    "actions": [
                        {"type": "button", "text": r, "value": r}
                        for r in filtered[:10]
                    ]
                }
            ]
        }


# ------------------------------
# 슬래시 커맨드 엔드포인트
# ------------------------------
@app.post("/kselnoti")
async def kselnoti_command(request: Request):
    data = await request.json()
    model_name = data.get("text", "").strip()

    if not model_name:
        return {"deleteOriginal": True, "text": "모델명을 입력해주세요. 예: /kselnoti ktc-k501"}

    try:
        results = await asyncio.wait_for(fetch_model_info(model_name), timeout=3.0)
        return build_message(model_name, results)

    except asyncio.TimeoutError:
        return {"deleteOriginal": True, "text": f"⚠️ [{model_name}] 조회 중 응답이 지연되었습니다. 잠시 후 다시 시도해주세요."}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
