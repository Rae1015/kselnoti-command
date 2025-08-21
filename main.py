import json
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import httpx
from bs4 import BeautifulSoup

app = FastAPI()
JSON_FILE = "models.json"
SEARCH_URL = "https://www.crefia.or.kr/portal/store/cardTerminal/cardTerminalList.xx"


# ------------------------------
# JSON 데이터 로드/저장
# ------------------------------
def load_models():
    try:
        with open(JSON_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_models(models):
    with open(JSON_FILE, "w", encoding="utf-8") as f:
        json.dump(models, f, ensure_ascii=False, indent=2)

# ------------------------------
# 크레피아 모델 정보 조회
# ------------------------------
async def fetch_model_info(model_name: str) -> str:
    async with httpx.AsyncClient(timeout=10) as client:
        payload = {"searchKey": "03", "searchValue": model_name, "currentPage": "1"}
        response = await client.post(SEARCH_URL, data=payload)
        soup = BeautifulSoup(response.text, "html.parser")
        rows = soup.select("table tbody tr")

        if "검색된 건이 없습니다." in soup.get_text(strip=True) or not rows:
            return f"🔍 [{model_name}] 검색 결과가 없습니다."

        results = []
        for row in rows[:10]:
            cols = row.find_all("td")
            if len(cols) >= 8:
                cert_no = cols[2].text.strip()
                identifier = cols[3].text.strip().split()[0]
                model = cols[5].text.strip().split()[0]
                date_parts = cols[6].text.strip().split()
                cert_date = date_parts[0]
                exp_date = date_parts[1] if len(date_parts) > 1 else ""
                results.append(
                    f"[{cert_no}] {model}\n"
                    f" - 식별번호 : {identifier}\n"
                    f" - 인증일자 : {cert_date}\n"
                    f" - 만료일자 : {exp_date}"
                )
        return "\n\n".join(results)


# ------------------------------
# /dooray/command (슬래시 커맨드)
# ------------------------------
@app.post("/dooray/command")
async def handle_command(request: Request):
    data = await request.form()
    text = data.get("text", "").strip()
    if not text:
        return {"text": "❗ 모델명을 입력해주세요. 예: /kselnoti KIS123"}

    model_name = text
    models = load_models()

    # 이미 존재
    if any(m["model"] == model_name for m in models):
        return {
            "text": f"리스트에 [{model_name}] 모델명이 이미 존재합니다. 제거할까요?",
            "attachments": [
                {
                    "actions": [
                        {"type": "button", "text": "제거", "name": "remove", "value": model_name}
                    ]
                }
            ],
        }

    # 검색
    search_result = await fetch_model_info(model_name)

    if "검색 결과가 없습니다" in search_result:
        models.append({"model": model_name})
        save_models(models)
        return {"text": f"신규 모델명 [{model_name}] 등록 완료 ✅"}

    if "\n\n" in search_result:  # 여러 개
        options = []
        for line in search_result.split("\n\n"):
            model_line = line.split("\n")[0]
            model_candidate = model_line.split("] ")[-1].split()[0]
            options.append(
                {"type": "button", "text": model_candidate, "name": "add", "value": model_candidate}
            )
        return {"text": "등록할 모델을 선택해주세요 👇", "attachments": [{"actions": options}]}

    # 검색 결과 1개
    models.append({"model": model_name})
    save_models(models)
    return {"text": f"[{model_name}] 모델명 등록 완료 ✅"}


# ------------------------------
# /dooray/interactive (버튼 콜백)
# ------------------------------
@app.post("/dooray/interactive")
async def handle_interactive(request: Request):
    data = await request.json()
    action = data["actions"][0]
    action_type = action["name"]
    model_name = action["value"]

    models = load_models()

    if action_type == "remove":
        models = [m for m in models if m["model"] != model_name]
        save_models(models)
        return JSONResponse({"text": f"[{model_name}] 제거 완료 🗑"})

    elif action_type == "add":
        if not any(m["model"] == model_name for m in models):
            models.append({"model": model_name})
            save_models(models)
        return JSONResponse({"text": f"[{model_name}] 등록 완료 ✅"})

    return JSONResponse({"text": "⚠ 알 수 없는 동작"})


# ------------------------------
# 헬스체크
# ------------------------------
@app.get("/")
def root():
    return {"status": "ok"}

# ------------------------------
# 서버 실행
# ------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)

