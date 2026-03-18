import json
from main import load_models, save_models, add_model_entry

def test_register_model():
    # 1. 가짜 모델 데이터 생성
    test_entry = {
        "cert_no": "2015-012-C1",
        "identifier": "#####KTC5700101b",
        "model": "KTC5700",   # 실제 사이트에 존재하는 모델명을 넣어야 함!
        "cert_date": "2024.01.01",
        "exp_date": "9999.99.99",   # <-- 일부러 틀린 값
        "channel": "4021293257473884753"
    }

    # 2. 등록
    add_model_entry(test_entry)

    # 3. 불러오기
    models = load_models()
    print("현재 models.json 내용:")
    print(json.dumps(models, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    test_register_model()