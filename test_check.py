import json
import asyncio
from main import save_models, check_models

# 테스트용 모델 데이터 저장 (만료일자 일부러 잘못 저장)
def setup_test_data():
    fake_model = {
        "cert_no": "2015-012-C1",
        "identifier": "#####KTC5700101b",
        "model": "KTC5700",   # 실제 사이트에 존재하는 모델명을 넣어야 함!
        "cert_date": "2024.01.01",
        "exp_date": "9999.99.99",   # <-- 일부러 틀린 값
        "channel": "4021293257473884753"
    }
    save_models([fake_model])
    print("[TEST] models.json에 테스트 데이터 저장 완료:", fake_model)

# 테스트 실행
if __name__ == "__main__":
    setup_test_data()
    asyncio.run(check_models())
