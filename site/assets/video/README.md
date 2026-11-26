# Ролик листа 02 и его кадры

Ролик сгенерирован в Gemini (Veo) по двум ключевым кадрам, тоже из Gemini. Это иллюстрация, а не съёмка
со стенда. Подпись об этом на странице убрана по просьбе пользователя (2026-11-22); происхождение записано
здесь и в JPEG-комментарии `impeccable:prompt` обоих постеров.

Вторая версия (2026-11-23, по просьбе пользователя): обходчик уносит журнал с собой, в последнем кадре на поручне
только камера. Прежний исходник сохранён как `docs/gemini_journal/shift_video_v1.mp4`.

| Шаг | Что | Исходник (вне git) |
|---|---|---|
| Кадр А | ночная смена: обходчик фиолетовой ручкой пишет показание манометра в журнал на поручне | `docs/gemini_journal/frameA_obhodchik.jpg`, промпт `promptA.txt` |
| Кадр Б | та же точка съёмки: людей и журнала нет, на пустом поручне камера на хомуте смотрит на шкалу | `docs/gemini_journal/frameB2_camera_nolog.jpg` — правка прежнего `frameB_camera.jpg` (убран закрытый журнал), промпт `promptB2.txt` |
| Ролик | 10 с, 1280×720, 24 к/с: А на 0 с, Б на 10 с; обходчик дописывает, закрывает журнал и уносит его с собой, камера проявляется наплывом | `docs/gemini_journal/shift_video.mp4`, промпт `promptV2.txt` |

| Файл | Что это | Размер |
|---|---|---|
| `shift.scrub.mp4` | копия для перемотки прокруткой: 1280×720, ключевой кадр каждый 4-й, без звука, moov в начале; SSIM 0,995 к исходнику | 11,1 МБ |
| `shift.scrub-m.mp4` | то же для экранов до 768 px: 854×480; SSIM 0,992 | 5,2 МБ |
| `../img/shift-before.jpg` | первый кадр ролика — постер и левый кадр при «уменьшить движение» | 202 КБ |
| `../img/shift-after.jpg` | последний кадр ролика — правый кадр при «уменьшить движение» и замена, если ролик не загрузился | 187 КБ |

Почему ключевой кадр каждый 4-й: `video.currentTime` при прокрутке прыгает в любую точку ролика. С редкими
ключевыми кадрами браузер декодирует всё от ближайшего ключевого, и перемотка дёргается; при `-g 4` это
не больше трёх лишних кадров 720p.

Прежние копии (до 2026-11-23) кодировались с `-g 1` и CRF 24–25: каждый кадр сжимался сам по себе
и терял фактуру Veo (зерно, ржавчину, пар), SSIM к исходнику 0,958 и 0,938. Межкадровое сжатие с шагом 4
и CRF 16–18 почти без потерь и укладывается в бюджет.

## Команды

ffmpeg 7.1 из пакета `imageio_ffmpeg` (Python 3.14), запуск из корня репозитория:

```
F="C:/Users/Egoru/AppData/Local/Programs/Python/Python314/Lib/site-packages/imageio_ffmpeg/binaries/ffmpeg-win-x86_64-v7.1.exe"
SRC=docs/gemini_journal/shift_video.mp4

"$F" -i "$SRC" -an -c:v libx264 -preset slow -crf 16 \
  -g 4 -keyint_min 1 -sc_threshold 0 -bf 0 -pix_fmt yuv420p -profile:v high \
  -movflags +faststart site/assets/video/shift.scrub.mp4

"$F" -i "$SRC" -an -vf scale=854:480:flags=lanczos -c:v libx264 -preset slow -crf 18 \
  -g 4 -keyint_min 1 -sc_threshold 0 -bf 0 -pix_fmt yuv420p -profile:v high \
  -movflags +faststart site/assets/video/shift.scrub-m.mp4
```

Проверка качества копии против исходника:

```
"$F" -i site/assets/video/shift.scrub.mp4 -i "$SRC" -lavfi "[0:v][1:v]ssim" -f null -
```

Постеры — первый и последний кадр ролика через OpenCV, качество JPEG 92 (mjpeg-кодер этой сборки ffmpeg
отказывается писать JPEG из yuv420p ограниченного диапазона). После записи в начало файла возвращается
сегмент-комментарий `impeccable:prompt` с промптом генерации:

```
python -c "import cv2; c=cv2.VideoCapture('docs/gemini_journal/shift_video.mp4'); n=int(c.get(7)); \
[ (c.set(1,i), cv2.imwrite(p, c.read()[1], [cv2.IMWRITE_JPEG_QUALITY, 92, cv2.IMWRITE_JPEG_PROGRESSIVE, 1])) \
  for i, p in [(0,'site/assets/img/shift-before.jpg'), (n-1,'site/assets/img/shift-after.jpg')] ]"
```

Бюджеты и параметры копий проверяет `node site/tests/check.js`: размер, отсутствие звука, moov перед mdat,
ключевой кадр не реже каждого 4-го кадра.
