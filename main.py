# main.py
import os
import json
import aiohttp
import asyncio
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from bs4 import BeautifulSoup
from fastapi import Response

app = FastAPI()

SEARCH_URL = "https://www.crefia.or.kr/portal/store/cardTerminal/cardTerminalList.xx"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_FILE = os.path.join(BASE_DIR, "models.json")
DOORAY_WEBHOOK_BASE = "https://nhnent.dooray.com/messenger/api/sendMessage?appToken=YOUR_APP_TOKEN"

# ------------------------------
# JSON 유틸
# ------------------------------
def load_models():
    if not os.path.exists(MODEL_FILE):
        return []
    with open(MODEL_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_models(models):
    with open(MODEL_FILE, "w", encoding="utf-8") as f:
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
                "text": f"[{model_name}] 이미 등록되어있는 모델이에요. 리스트에서 제거해드릴까요?",
                "attachments": [
                    {
                        "actions": [
                            {"name": "remove", "text": "제거", "type": "button", "value": model_name},
                            {"name": "close", "text": "종료", "type": "button", "value": "close"}
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
                "text": f"🔍 [{model_name}] 신규 모델인가요?\n정보가 등록되면 알려드릴 수 있게, 리스트에 등록해드릴까요?",
                "attachments": [
                    {
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
            "text": f"[{r['cert_no']}] {r['model']}\n - 식별번호: {r['identifier']}\n - 인증일자: {r['cert_date']}\n - 만료일자: {r['exp_date']}\n\n✅ 정보가 변경되면 알려드릴 수 있게, 리스트에 등록해드릴까요?",
            "attachments": [
                {
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
@app.post("/kselnoti_action")
async def kselnoti_action(request: Request):
    data = await request.json()
    print("DEBUG kselnoti-action:", data)  # 실제 요청 로그 확인

    action_name = data.get("actionName")
    action_value = data.get("actionValue")

    if not action_name:
        return {"text": "⚠️ actionName이 전달되지 않았습니다."}

    if action_name == "remove":
        remove_model_entry(action_value)
        return JSONResponse({"text": f"🗑 [{action_value}] 제거 완료", "deleteOriginal": True})

    if action_name == "new_register":
        add_model_entry({"model": action_value})
        return JSONResponse({"text": f"✅ 신규 모델 [{action_value}] 등록 완료", "deleteOriginal": True})

    if action_name == "register":
        entry = json.loads(action_value)
        add_model_entry(entry)
        return JSONResponse({"text": f"✅ 모델 [{entry['model']}] 등록 완료", "deleteOriginal": True})

    if action_name == "close":
        return JSONResponse({"text": "등록 정보 알림이 필요할 때 찾아주세요🙌🏻", "deleteOriginal": True})

    return JSONResponse({"text": "⚠ 알 수 없는 동작입니다.", "deleteOriginal": True})

# ------------------------------
# 헬스체크 + 자동 모니터링
# ------------------------------
@app.api_route("/", methods=["GET", "HEAD"])
async def health_check():
    if getattr(Response, "method", None) == "HEAD":
        return Response(status_code=200)  # body 없는 응답
    asyncio.create_task(check_models())
    return {"status": "✅ KSEL bot is running"}

# ------------------------------
# 여러 모델 동시에 변경 체크
# ------------------------------
async def check_models():
    models = load_models()
    if not models:
        return

    tasks = []
    for model in models:
        tasks.append(fetch_model_info(model["model"]))
    results_list = await asyncio.gather(*tasks)

    for saved_model, results in zip(models, results_list):
        channel_id = saved_model.get("channel", "")
        if not results:
            continue

        # 🔹 모델명과 길이가 완전히 일치하는 결과만 필터링
        filtered_results = [
            r for r in results
            if r["model"] == saved_model["model"] and len(r["model"]) == len(saved_model["model"])
        ]

        if not filtered_results:
            continue

        r = filtered_results[0]  # 첫 번째 결과 사용
        changed = False
        for key in ["cert_no", "identifier", "cert_date", "exp_date"]:
            if r.get(key) != saved_model.get(key):
                changed = True
                break
        if changed:
            print(f"[INFO] 변경 감지: {saved_model['model']} 이전={saved_model} → 새로운={r}")
            add_model_entry({**r, "channel": channel_id})
            if channel_id:
                await send_dooray_message(channel_id,
                    f"🔔 [{r['model']}] 등록정보가 업데이트 되었어요!\n"
                    f"[{r['cert_no']}] {r['model']}\n"
                    f"- 식별번호: {r['identifier']}\n"
                    f"- 인증일자: {r['cert_date']}\n"
                    f"- 만료일자: {r['exp_date']}"
                )
