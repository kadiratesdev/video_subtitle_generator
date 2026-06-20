@echo off
cd /d "%~dp0"

echo ========================================
echo  El Clon - Tasinabilir EXE Derleme
echo  (Groq API - CUDA gerekmez)
echo ========================================
echo.

echo [1/4] Bagimliliklar kuruluyor...
python -m pip install -r requirements.txt pyinstaller -q
if errorlevel 1 (
  echo [HATA] pip kurulumu basarisiz.
  pause
  exit /b 1
)

echo [2/4] EXE derleniyor (birkaç dakika surebilir)...
pyinstaller --noconfirm --clean ElClon.spec
if errorlevel 1 (
  echo [HATA] PyInstaller basarisiz.
  pause
  exit /b 1
)

echo [3/4] Dagitim paketi hazirlaniyor...
python scripts\package_dist.py
if errorlevel 1 (
  echo [HATA] Paket hazirlama basarisiz.
  pause
  exit /b 1
)

echo.
echo [4/4] Tamamlandi!
echo.
echo   dist\ElClon\ klasorunu kullaniciya verin.
echo   Calistir.bat veya ElClon.exe ile baslatilir.
echo   .env icine GROQ_API_KEY eklemeyi unutmayin.
echo.
pause
