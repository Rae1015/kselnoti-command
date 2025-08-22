import os
import asyncio
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
import httpx
from bs4 import BeautifulSoup
import uvicorn

app = FastAPI()

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


async def fetch_model_info(model_name: str):
    payload = {"searchKey": "03", "searchValue": model_name, "currentPage": "1"}
    response = await client.post(SEARCH_URL, data=payload)
    soup = BeautifulSoup(response.text, "html.parser")
    rows = soup.select("table tbody tr")

    if "검색된 건이 없습니다." in soup.get_text(strip=True) or not rows:
        return []

    results = []
    for row in rows:
        cols = row.find_all("td")
        if len(cols) >= 8:
            model = cols[5].text.strip().split()[0]
            results.append(model)

    return results


def build_buttons(model_name: str, results: list):
    # 결과 없음
    if not results:
        return {
            "text": f"🔍 [{model_name}] 검색 결과가 없습니다.",
            "attachments": [
                {
                    "text": "신규 모델로 등록하시겠습니까?",
                    "actions": [
                        {"type": "button", "text": "신규등록", "style": "primary"},
                        {"type": "button", "text": "종료", "style": "danger"}
                    ]
                }
            ]
        }

    # 정확히 일치하는 값만 필터링
    exact_matches = [r for r in results if r == model_name]

    # 일치하는게 있으면 등록/종료 버튼
    if len(exact_matches) == 1:
        return {
            "text": f"✅ [{model_name}] 검색 결과가 확인되었습니다.",
            "attachments": [
                {
                    "text": f"모델 [{model_name}] 처리 옵션:",
                    "actions": [
                        {"type": "button", "text": "등록", "style": "primary"},
                        {"type": "button", "text": "종료", "style": "danger"}
                    ]
                }
            ]
        }

    # 일치하는게 없으면 신규등록/종료 버튼
    return {
        "text": f"❓ [{model_name}] 검색 결과와 정확히 일치하는 값이 없습니다.",
        "attachments": [
            {
                "text": "신규 모델로 등록하시겠습니까?",
                "actions": [
                    {"type": "button", "text": "신규등록", "style": "primary"},
                    {"type": "button", "text": "종료", "style": "danger"}
                ]
            }
        ]
    }


@app.post("/kselnoti")
async def kselnoti_command(request: Request):
    data = await request.json()
    model_name = data.get("text", "").strip()

    if not model_name:
        return {"deleteOriginal": True, "text": "모델명을 입력해주세요. 예: /kselnoti ktc-k501"}

    try:
        results = await asyncio.wait_for(fetch_model_info(model_name), timeout=3.0)
        message = build_buttons(model_name, results)
        return {"deleteOriginal": True, **message}

    except asyncio.TimeoutError:
        return {"deleteOriginal": True, "text": f"⚠️ [{model_name}] 조회 중 응답이 지연되었습니다."}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
