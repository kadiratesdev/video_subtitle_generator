@echo off
cd /d "%~dp0"

echo ========================================
echo  GenSub - Tasinabilir EXE Derleme
echo  (Groq API - CUDA gerekmez)
echo ========================================
echo.

echo [1/5] Arayuz derleniyor (Tailwind + Preline)...
if exist package.json (
  call npm run build:ui 2>nul
  if errorlevel 1 echo [UYARI] npm bulunamadi. Mevcut static dosyalar kullanilacak.
)

echo [2/5] Bagimliliklar kuruluyor...
python -m pip install -r requirements.txt pyinstaller -q
if errorlevel 1 (
  echo [HATA] pip kurulumu basarisiz.
  pause
  exit /b 1
)

echo [3/5] EXE derleniyor (birkaç dakika surebilir)...
pyinstaller --noconfirm --clean GenSub.spec
if errorlevel 1 (
  echo [HATA] PyInstaller basarisiz.
  pause
  exit /b 1
)

echo [4/5] Dagitim paketi hazirlaniyor...
python scripts\package_dist.py
if errorlevel 1 (
  echo [HATA] Paket hazirlama basarisiz.
  pause
  exit /b 1
)

echo [5/5] Release zip (istege bagli)...
python scripts\package_release.py
if errorlevel 1 (
  echo [UYARI] Release zip olusturulamadi.
)

echo.
echo Tamamlandi!
echo   dist\GenSub\ klasorunu kullaniciya verin.
echo   Calistir.bat veya GenSub.exe ile baslatilir.
echo   .env icine GROQ_API_KEY eklemeyi unutmayin.
echo.
pause
