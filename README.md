# MedVision OCR Lab

의약품 포장지 이미지를 브라우저에서 업로드하고 PaddleOCR PP-OCRv5 한국어 모델로 분석하는 로컬 웹앱입니다.

## 실행

```bash
conda activate medicine-ocr
cd /Users/maengsinbi/Documents/ChatGPT/컴퓨터비전/medicine-ocr-web
python -m pip install -r requirements.txt
python -m uvicorn app:app --reload --port 8000
```

브라우저에서 `http://127.0.0.1:8000`을 엽니다. 서버를 끌 때는 터미널에서 `Control+C`를 누릅니다.

## Render 공개 배포

이 폴더를 GitHub 저장소에 올린 뒤 Render에서 **New → Blueprint**를 선택하고 저장소를 연결합니다. `render.yaml`이 Docker 웹서비스를 자동 구성합니다. 배포 후 `https://서비스이름.onrender.com` 형태의 공개 주소가 생성됩니다.

OCR는 오래 걸릴 수 있으므로 업로드 요청과 분석 작업을 분리했습니다. 브라우저는 작업 상태를 조회하며, 서버는 한 번에 한 작업을 처리합니다. 업로드 이미지와 결과는 메모리에만 보관되고 약 1시간 후 정리되며, 재배포 또는 재시작 시 즉시 사라집니다.

무료 인스턴스는 비활성 상태에서 정지될 수 있고 CPU·메모리가 제한되어 첫 분석이 느리거나 PaddleOCR 실행에 부족할 수 있습니다. 실제 시연 또는 다중 사용자 운영에서는 충분한 메모리의 유료 인스턴스를 권장합니다.

## 사용 순서

1. 약 포장지 앞면 이미지를 업로드합니다.
2. CER가 필요하면 사진에 실제로 보이는 정답 문구를 입력합니다.
3. 빠른 분석(원본) 또는 전체 비교(6종)를 선택합니다.
4. 결과에서 신뢰도, 인식 영역 수, 처리 시간, CER와 추출 후보를 확인합니다.

첫 실행은 PaddleOCR 모델 준비 때문에 더 오래 걸릴 수 있습니다. 3000px 이상의 이미지는 긴 변 1800px로 자동 축소됩니다.

