from flask import Flask, request, jsonify
from apscheduler.schedulers.background import BackgroundScheduler
import requests
from bs4 import BeautifulSoup
import os

app = Flask(__name__)

# -----------------------------
# 전역 변수
# -----------------------------
watch_list = {}   # { "모델명": {"cert_date": "...", "exp_date": "..."} }
WEBHOOK_URL = os.getenv("DOORAY_WEBHOOK_URL")  # Render 환경변수로 설정

# -----------------------------
# 크레피아 사이트 검색 함수
# -----------------------------
def fetch_model_info(model_name):
    url = "https://www.crefia.or.kr/portal/store/cardTerminal/cardTerminalList.xx"
    res = requests.post(url, data={"searchKeyword": model_name})
    soup = BeautifulSoup(res.text, "html.parser")
    rows = soup.select("tbody tr")

    for row in rows[:10]:  # 최대 10개
        cols = row.find_all("td")
        if len(cols) >= 8:
            cert_no = cols[2].text.strip()
            identifier = cols[3].text.strip().split()[0]
            model = cols[5].text.strip().split()[0]
            date_parts = cols[6].text.strip().split()
            cert_date = date_parts[0]
            exp_date = date_parts[1] if len(date_parts) > 1 else ""

            if model == model_name:
                return {
                    "cert_no": cert_no,
                    "identifier": identifier,
                    "model": model,
                    "cert_date": cert_date,
                    "exp_date": exp_date,
                }
    return None

# -----------------------------
# Dooray 메시지 전송
# -----------------------------
def send_notification(text, to_channel=True):
    """to_channel=True → 채팅방 메시지 / False → ephemeral(자신만 보기)"""
    if not WEBHOOK_URL:
        print("⚠️ WEBHOOK_URL 미설정")
        return

    payload = {
        "botName": "KSEL Notifier",
        "text": text
    }
    requests.post(WEBHOOK_URL, json=payload)

# -----------------------------
# 슬래시 커맨드 처리
# -----------------------------
@app.route("/kselnoti", methods=["POST"])
def kselnoti():
    data = request.form
    command_text = data.get("text", "").strip()
    user = data.get("userName", "unknown")

    if command_text.startswith("help"):
        return jsonify({
            "response_type": "ephemeral",
            "text": (
                "📝 사용법:\n"
                "`/kselnoti 모델명` → 모델 등록\n"
                "`/kselnoti remove 모델명` → 모델 제거\n"
                "`/kselnoti list` → 등록된 모델 확인\n"
                "`/kselnoti help` → 도움말 보기"
            )
        })

    elif command_text.startswith("remove"):
        _, model = command_text.split(maxsplit=1)
        if model in watch_list:
            del watch_list[model]
            return jsonify({
                "response_type": "ephemeral",
                "text": f"🗑 모델 `{model}` 제거 완료"
            })
        else:
            return jsonify({
                "response_type": "ephemeral",
                "text": f"❌ 모델 `{model}` 은(는) 등록되어 있지 않습니다."
            })

    elif command_text.startswith("list"):
        if not watch_list:
            return jsonify({
                "response_type": "ephemeral",
                "text": "📂 등록된 모델이 없습니다."
            })
        else:
            models = "\n".join([f"- {m}" for m in watch_list.keys()])
            return jsonify({
                "response_type": "ephemeral",
                "text": f"📂 등록된 모델:\n{models}"
            })

    else:
        # 모델 등록
        model = command_text
        info = fetch_model_info(model)
        if info:
            watch_list[model] = {
                "cert_date": info["cert_date"],
                "exp_date": info["exp_date"]
            }
            return jsonify({
                "response_type": "ephemeral",
                "text": (
                    f"✅ 모델 `{model}` 등록 완료\n"
                    f"[{info['cert_no']}] {info['model']}\n"
                    f" - 식별번호 : {info['identifier']}\n"
                    f" - 인증일자 : {info['cert_date']}\n"
                    f" - 만료일자 : {info['exp_date']}"
                )
            })
        else:
            return jsonify({
                "response_type": "ephemeral",
                "text": f"❌ 모델 `{model}` 을(를) 찾을 수 없습니다."
            })

# -----------------------------
# 변경 감지 스케줄러
# -----------------------------
def check_updates():
    if not watch_list:
        return

    for model, old_data in list(watch_list.items()):
        new_info = fetch_model_info(model)
        if not new_info:
            send_notification(f"⚠️ 단말기 `{model}` 정보가 더 이상 검색되지 않습니다.")
            del watch_list[model]
        else:
            if (new_info["exp_date"] != old_data["exp_date"] or
                new_info["cert_date"] != old_data["cert_date"]):
                msg = (
                    "🔔 단말기 인증정보가 업데이트 되었습니다.\n"
                    f"[{new_info['cert_no']}] {new_info['model']}\n"
                    f" - 식별번호 : {new_info['identifier']}\n"
                    f" - 인증일자 : {new_info['cert_date']}\n"
                    f" - 만료일자 : {new_info['exp_date']}"
                )
                send_notification(msg)
                del watch_list[model]  # 변경 감지 후 제거

# 스케줄러 (08~20시 매시 정각 실행)
scheduler = BackgroundScheduler(timezone="Asia/Seoul")
scheduler.add_job(check_updates, "cron", hour="8-20", minute=0)
scheduler.start()

# -----------------------------
# 로컬 실행 / Render 실행 둘 다 지원
# -----------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
