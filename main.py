# main.py
import os
import json
import aiohttp
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from bs4 import BeautifulSoup

app = FastAPI()

SEARCH_URL = "https://www.crefia.or.kr/portal/store/cardTerminal/cardTerminalList.xx"
JSON_FILE = "models.json"

# ------------------------------
# JSON 유틸
# ------------------------------
def load_models():
    if not os.path.exists(JSON_FILE):
        return []
    with open(JSON_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_models(models):
    with open(JSON_FILE, "w", encoding="utf-8") as f:
        json.dump(models, f, ensure_ascii=False, indent=2)

def add_model_entry(entry: dict):
    models = load_models()
    # 중복 방지 (model + cert_no 기준)
    if not any(m["model"] == entry["model"] and m.get("cert_no") == entry.get("cert_no") for m in models):
        models.append(entry)
        save_models(models)

def remove_model_entry(model_name: str):
    models = load_models()
    models = [m for m in models if m["model"] != model_name]
    save_models(models)

# ------------------------------
# 크레피아 모델 정보 조회
# ------------------------------
async def fetch_model_info(model_name: str):
    async with aiohttp.ClientSession() as client:
        payload = {"searchKey": "03", "searchValue": model_name, "currentPage": "1"}
        async with client.post(SEARCH_URL, data=payload) as response:
            text = await response.text()
            soup = BeautifulSoup(text, "html.parser")
            rows = soup.select("table tbody tr")

            no_result_text = soup.get_text(strip=True)
            if "검색된 건이 없습니다." in no_result_text or not rows:
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

                    results.append(
                        {
                            "cert_no": cert_no,
                            "identifier": identifier,
                            "model": model,
                            "cert_date": cert_date,
                            "exp_date": exp_date,
                        }
                    )
            return results

# ------------------------------
# /kselnoti 엔드포인트
# ------------------------------
@app.post("/kselnoti")
async def kselnoti(request: Request):
    data = await request.json()
    text = data.get("text", "").strip()

    if not text:
        return JSONResponse({"text": "⚠ 모델명을 입력해주세요."})

    # --- 리스트 조회 기능 ---
    if text.lower() == "list":
        models = load_models()
        if not models:
            return JSONResponse({"text": "등록된 모델이 없습니다."})
        model_names = [m["model"] for m in models]
        return JSONResponse({"text": "등록된 모델 목록:\n" + "\n".join(model_names)})

    # 이미 등록된 모델 확인
    model_name = text
    registered_models = [m["model"] for m in load_models()]
    if model_name in registered_models:
        return JSONResponse(
            {
                "text": f"리스트에 [{model_name}] 모델명이 이미 존재합니다. 제거할까요?",
                "attachments": [
                    {
                        "title": "제거",
                        "actions": [
                            {"name": "remove", "text": "제거", "type": "button", "value": model_name}
                        ],
                    }
                ],
            }
        )

    # 크레피아 조회
    results = await fetch_model_info(model_name)

    # 입력 모델명과 길이까지 일치하는 결과만 필터링
    filtered_results = [r for r in results if r["model"] == model_name and len(r["model"]) == len(model_name)]

    if not filtered_results:
        # 신규등록 버튼
        return JSONResponse(
            {
                "text": f"🔍 검색 결과 없음. [{model_name}] 신규 등록하시겠습니까?",
                "attachments": [
                    {
                        "title": "신규등록",
                        "actions": [
                            {"name": "new_register", "text": "신규등록", "type": "button", "value": model_name},
                            {"name": "close", "text": "종료", "type": "button", "value": "close"}
                        ],
                    }
                ],
            }
        )

    # filtered_results가 1개 이상 → 첫 번째 항목만 사용
    r = filtered_results[0]
    return JSONResponse(
        {
            "text": f"[{r['cert_no']}] {r['model']}\n - 식별번호: {r['identifier']}\n - 인증일자: {r['cert_date']}\n - 만료일자: {r['exp_date']}\n\n✅ 모델명 등록 가능",
            "attachments": [
                {
                    "title": "등록/종료",
                    "actions": [
                        {"name": "register", "text": "등록", "type": "button", "value": json.dumps(r, ensure_ascii=False)},
                        {"name": "close", "text": "종료", "type": "button", "value": "close"}
                    ],
                }
            ],
        }
    )

# ------------------------------
# 버튼 액션 처리
# ------------------------------
@app.post("/command")
async def kselnoti_action(request: Request):
    data = await request.json()
    action = data.get("actions", [])[0]
    action_name = action.get("name")
    action_value = action.get("value")

    if action_name == "remove":
        remove_model_entry(action_value)
        return JSONResponse({"text": f"🗑 [{action_value}] 제거 완료"})

    if action_name == "new_register":
        add_model_entry({"model": action_value})
        return JSONResponse({"text": f"✅ 신규 모델명 [{action_value}] 등록 완료"})

    if action_name == "register":
        entry = json.loads(action_value)
        add_model_entry(entry)
        return JSONResponse({"text": f"✅ 모델 [{entry['model']}] 등록 완료"})

    if action_name == "close":
        return JSONResponse({"text": "🛑 작업 종료"})

    return JSONResponse({"text": "⚠ 알 수 없는 동작입니다."})
