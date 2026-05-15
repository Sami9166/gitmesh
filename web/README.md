# GitMesh Web Frontend

Vanilla HTML/CSS/JS 기반 웹 프론트엔드입니다. Flutter 없이도 GitMesh를 웹에서 데모할 수 있습니다.

## 실행

백엔드를 먼저 실행합니다.

```bash
cd ../backend
pip install -r requirements.txt
cp .env.example .env
# .env에 UPSTAGE_API_KEY 입력
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

웹 프론트엔드를 실행합니다.

```bash
cd ../web
python -m http.server 5173
```

브라우저에서 열기:

```text
http://127.0.0.1:5173
```

## API 주소 변경

기본 API 주소는 `http://127.0.0.1:8000`입니다. 브라우저 콘솔에서 다음처럼 바꿀 수 있습니다.

```js
localStorage.setItem("GITMESH_API_BASE_URL", "http://your-server:8000")
```

이후 새로고침하면 적용됩니다.

## 폰트

CSS는 `CookieRun`, `BMJUA`를 우선 폰트로 지정해두었습니다. 실제 폰트 파일은 포함하지 않았습니다. 사용하려면 라이선스를 확인한 뒤 직접 웹 폰트 또는 asset으로 추가하세요.

`styles.css` 상단의 `--font-family` 값을 수정하면 됩니다.
