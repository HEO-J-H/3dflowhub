@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 3dflowhub 대시보드를 시작합니다... (이 창을 닫으면 종료)
start "" http://localhost:8501
python -m streamlit run app.py --server.headless true --server.port 8501 --browser.gatherUsageStats false
