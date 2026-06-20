@echo off
cd /d "%~dp0"

if not exist ".env" (
  echo [BILGI] .env bulunamadi, .env.example kopyalaniyor...
  copy /Y ".env.example" ".env" >nul
  echo        Lutfen .env icinde GROQ_API_KEY degerini doldurun.
)

python -m pip install -r requirements.txt -q
python app.py
pause
