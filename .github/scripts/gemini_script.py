import os
from google import genai

# GitHub Secrets에서 환경 변수 가져오기
api_key = os.environ.get("GEMINI_API_KEY")

if not api_key:
    raise ValueError("GEMINI_API_KEY가 설정되지 않았습니다.")

# Gemini 클라이언트 초기화 (새로운 google-genai SDK 기준)
client = genai.Client(api_key=api_key)

# Gemini 모델 호출 테스트
response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents="GitHub Actions에서 안녕! 넌 정상적으로 동작하고 있어?",
)

print("--- Gemini API 응답 결과 ---")
print(response.text)
