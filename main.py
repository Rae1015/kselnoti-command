import json
import os
import httpx
from bs4 import BeautifulSoup
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

SEARCH_URL = "https://www.crefia.or.kr/portal/store/cardTerminal/cardTerminalList.xx"
JSON_FILE = "models.json"

app = FastAPI()
client = httpx.AsyncClient()

# ------------------------------
# JSON 저장/로드 유틸
# ------------------------------
def load_models():
    if not os.path.exists(JSON_FILE):
        return {"models": []}
    with open(JSON_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_models(data):
    with open(JSON_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ------------------------------
# 크레피아 모델 정보 조회
# ------------------------------
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
# Dooray Slash Command 엔드포인트
# ------------------------------
@app.post("/kselnoti")
async def kselnoti(request: Request):
    body = await request.json()
    text = body.get("text", "").strip()

    if not text:
        return JSONResponse(content={"text": "❌ 모델명을 입력해주세요."})

    models_data = load_models()
    registered_models = [m["model"] for m in models_data["models"]]

    # 이미 등록된 모델 처리
    if text in registered_models:
        return JSONResponse(content={
            "text": f"리스트에 [{text}] 모델명이 이미 존재합니다. 제거할까요?",
            "attachments": [{
                "text": "",
                "actions": [{"type": "button", "text": "제거", "name": "remove", "value": text}]
            }]
        })

    # 크레피아 조회
    results = await fetch_model_info(text)

    if not results:
        return JSONResponse(content={
            "text": f"🔍 [{text}] 신규 모델명 등록 완료",
            "attachments": [{
                "text": "",
                "actions": [{"type": "button", "text": "신규등록", "name": "new_register", "value": text}]
            }]
        })

    if len(results) == 1:
        r = results[0]
        return JSONResponse(content={
            "text": f"[{r['cert_no']}] {r['model']}\n - 식별번호: {r['identifier']}\n - 인증일자: {r['cert_date']}\n - 만료일자: {r['exp_date']}\n\n✅ 모델명 등록 완료",
            "attachments": [{
                "text": "",
                "actions": [{"type": "button", "text": "등록", "name": "register", "value": json.dumps(r, ensure_ascii=False)}]
            }]
        })

    # 결과 여러개인 경우
    return JSONResponse(content={
        "text": "🔍 등록할 모델을 선택해주세요",
        "attachments": [{
            "text": "",
            "actions": [
                {"type": "button", "text": r["model"], "name": "register", "value": json.dumps(r, ensure_ascii=False)}
                for r in results
            ]
        }]
    })

# ------------------------------
# 버튼 Callback 처리
# ------------------------------
@app.post("/kselnoti-action")
async def kselnoti_action(request: Request):
    body = await request.json()
    action = body.get("action", "")
    value = body.get("value", "")

    models_data = load_models()

    if action == "remove":
        models_data["models"] = [m for m in models_data["models"] if m["model"] != value]
        save_models(models_data)
        return JSONResponse(content={"text": f"🗑️ [{value}] 제거 완료"})

    if action == "new_register":
        models_data["models"].append({
            "model": value,
            "cert_no": "",
            "identifier": "",
            "cert_date": "",
            "exp_date": ""
        })
        save_models(models_data)
        return JSONResponse(content={"text": f"🆕 [{value}] 신규 등록 완료"})

    if action == "register":
        model_info = json.loads(value)
        models_data["models"].append(model_info)
        save_models(models_data)
        return JSONResponse(content={"text": f"✅ [{model_info['model']}] 등록 완료"})

    return JSONResponse(content={"text": "⚠️ 알 수 없는 동작"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
