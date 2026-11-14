# Видео hero и картинки

Исходник — ролик Gemini `references/gauge_pullback.mp4` (он же `docs/gemini_video/gauge_pullback.mp4`):
1280×720, 24 к/с, 10 с, H.264 с одним ключевым кадром и звуком AAC. Камера отъезжает от манометра в котельной.

| Файл | Что это | Размер |
|---|---|---|
| `gauge_pullback.mp4` | оригинал без изменений, побайтно равен `references/gauge_pullback.mp4` | 5,0 МБ |
| `gauge_pullback.scrub.mp4` | копия для перемотки прокруткой: 1280×720, каждый кадр ключевой, без звука, moov в начале | 8,1 МБ |
| `gauge_pullback.scrub-m.mp4` | то же для экранов до 768 px: 854×480 | 4,2 МБ |
| `../img/poster.jpg` | первый кадр ролика — постер hero и замена видео при «уменьшить движение» | 130 КБ |
| `../img/boiler-hall.jpg` | кадр Gemini `docs/gemini_art/gaugevision_hero.jpg` (камера и манометр в котельной), ширина 1920 — фон финального экрана | 168 КБ |

Почему каждый кадр ключевой: `video.currentTime` при прокрутке прыгает в любую точку ролика. С одним
ключевым кадром браузер декодирует всё от начала до нужного кадра, и перемотка дёргается; при `-g 1`
каждый кадр декодируется сам по себе.

## Команды

ffmpeg 7.1 из пакета `imageio_ffmpeg` (Python 3.14), запуск из корня репозитория:

```
F="C:/Users/Egoru/AppData/Local/Programs/Python/Python314/Lib/site-packages/imageio_ffmpeg/binaries/ffmpeg-win-x86_64-v7.1.exe"

cp references/gauge_pullback.mp4 site/assets/video/gauge_pullback.mp4

"$F" -i references/gauge_pullback.mp4 -an -c:v libx264 -preset slow -crf 23 \
  -g 1 -keyint_min 1 -sc_threshold 0 -bf 0 -pix_fmt yuv420p -profile:v high \
  -movflags +faststart site/assets/video/gauge_pullback.scrub.mp4

"$F" -i references/gauge_pullback.mp4 -an -vf scale=854:480:flags=lanczos -c:v libx264 -preset slow -crf 24 \
  -g 1 -keyint_min 1 -sc_threshold 0 -bf 0 -pix_fmt yuv420p -profile:v high \
  -movflags +faststart site/assets/video/gauge_pullback.scrub-m.mp4

"$F" -i references/gauge_pullback.mp4 -vf "select=eq(n\,0)" -frames:v 1 -q:v 2 site/assets/img/poster.jpg

"$F" -i docs/gemini_art/gaugevision_hero.jpg -vf "scale=1920:-2:flags=lanczos" -q:v 4 site/assets/img/boiler-hall.jpg
```

Бюджеты и параметры копий проверяет `node site/tests/check.js`: размер, побайтное равенство оригинала,
нет звуковой дорожки, moov перед mdat, ключевой кадр не реже каждого второго кадра.
