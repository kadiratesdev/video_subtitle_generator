# GenSub

Videolardan otomatik Türkçe altyazı üreten yerel web uygulaması. **İspanyolca** veya **İngilizce** kaynak videoları Groq API ile transkribe eder, Türkçeye çevirir ve tarayıcıda altyazılı oynatır.

## Özellikler

- Web arayüzü ile video listesi, izleme ve işlem takibi
- **Yerel klasör (varsayılan):** Proje içindeki `videos/` veya seçtiğiniz klasör
- **Uzak kaynak (isteğe bağlı):** HTTP üzerinden video dizini (URL listesi)
- Kaynak dil: İspanyolca (`es`) veya İngilizce (`en`)
- İşlem durumu kaydı ve kaldığı yerden devam
- **Yeniden oluştur:** Hatalı bölümleri sıfırdan işleme
- Taşınabilir Windows EXE (`build.bat`)
- İsteğe bağlı yerel Whisper (CUDA, `requirements-gpu.txt`)

## Pipeline

1. Video indirme veya yerel dosyadan kopyalama → `videos/`
2. Ses çıkarma (ffmpeg)
3. Groq Whisper transkripsiyon → `es.srt` / `en.srt`
4. Groq LLM çeviri → `tr.srt`
5. Tarayıcıda video + VTT altyazı

## Gereksinimler

- Python 3.11+
- [Groq API](https://console.groq.com) anahtarı
- ffmpeg (geliştirmede sistemde; EXE paketinde dahil)

## Kurulum

```bash
git clone https://github.com/kadiratesdev/video_subtitle_generator.git
cd video_subtitle_generator
pip install -r requirements.txt
copy .env.example .env
```

`.env` içine `GROQ_API_KEY` ekleyin.

## Çalıştırma

```bash
python app.py
```

Tarayıcı: `http://127.0.0.1:8765`

Windows: `run.bat`

### CLI

```bash
python main.py status
python main.py process --episode bolum-001 --limit 1
```

## Ortam değişkenleri

| Değişken | Açıklama |
|----------|----------|
| `GROQ_API_KEY` | Groq API anahtarı (yeni çeviri için zorunlu) |
| `VIDEO_SOURCE` | `local` (varsayılan) veya `remote` |
| `VIDEO_BASE_URL` | Uzak video dizini URL (uzak mod için) |
| `LOCAL_VIDEO_DIR` | Yerel video klasörü (varsayılan `videos`) |
| `SOURCE_LANG` | `es` veya `en` |
| `VIDEOS_DIR` | İndirilen videolar |
| `OUTPUT_DIR` | Altyazı ve ara dosyalar |
| `WEB_PORT` | Web arayüz portu (varsayılan `8765`) |
| `EMBED_SUBTITLES` | `1` → altyazı videoya gömülür |

Arayüzden kaynak ve dil değiştirilebilir; ayarlar `output/catalog-settings.json` dosyasına kaydedilir.

## Windows EXE

```bash
build.bat
```

Çıktı: `dist/GenSub/` — tüm klasörü dağıtın. Kullanıcının Python veya ffmpeg kurmasına gerek yoktur.

## Klasör yapısı

```
videos/                 # İndirilen / kopyalanan videolar
output/
  <video-stem>/
    audio.mp3
    es.srt | en.srt
    tr.srt
  pipeline-state.json
  catalog-settings.json
```

## Lisans

Bu proje kişisel kullanım için geliştirilmiştir. Groq API kullanımı Groq’un kendi koşullarına tabidir.
