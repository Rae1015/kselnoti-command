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
    limits=httpx.Limits(max_connections=10, max_keepalive_connections=5, keepalive_expiry=30.0)
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

    no_result_text = soup.get_text(strip=True)
    if "검색된 건이 없습니다." in no_result_text or not rows:
        return []

    results = []
    for row in rows[:20]:  # 20개까지 파싱
        cols = row.find_all("td")
        if len(cols) >= 8:
            model = cols[5].text.strip().split()[0]
            results.append(model)
    return results


@app.post("/kselnoti")
async def kselnoti_command(request: Request):
    data = await request.json()
    model_name = data.get("text", "").strip()

    if not model_name:
        return {
            "deleteOriginal": True,
            "text": "모델명을 입력해주세요. 예: `/kselnoti ktc-k501`"
        }

    try:
        models = await asyncio.wait_for(fetch_model_info(model_name), timeout=3.0)

        # 결과 0개
        if not models:
            return {
                "deleteOriginal": True,
                "text": f"🔍 [{model_name}] 검색 결과가 없습니다.",
                "attachments": [
                    {
                        "text": "선택하세요",
                        "actions": [
                            {"type": "button", "text": "신규등록", "value": f"register:{model_name}"},
                            {"type": "button", "text": "종료", "value": "close"}
                        ]
                    }
                ]
            }

        # 입력값과 길이까지 일치하는 모델만 필터링
        exact_models = [m for m in models if m.strip().lower() == model_name.strip().lower()]

        # 결과 1개
        if len(exact_models) == 1:
            return {
                "deleteOriginal": True,
                "text": f"✅ [{exact_models[0]}] 검색 결과를 찾았습니다.",
                "attachments": [
                    {
                        "text": "선택하세요",
                        "actions": [
                            {"type": "button", "text": "등록", "value": f"register:{exact_models[0]}"},
                            {"type": "button", "text": "종료", "value": "close"}
                        ]
                    }
                ]
            }

        # 결과 다수 (최대 10개 버튼)
        buttons = [{"type": "button", "text": m, "value": f"model:{m}"} for m in models[:10]]
        return {
            "deleteOriginal": True,
            "text": f"🔍 [{model_name}] 검색 결과 다수 발견 ({len(models)}건)",
            "attachments": [
                {
                    "text": "모델명을 선택하세요",
                    "actions": buttons
                }
            ]
        }

    except asyncio.TimeoutError:
        return {"deleteOriginal": True, "text": f"⚠️ [{model_name}] 조회 중 응답이 지연되었습니다. 잠시 후 다시 시도해주세요."}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
