# Ролик листа 02 и его кадры

Ролик сгенерирован в Gemini (Veo) по двум ключевым кадрам, тоже из Gemini. Это иллюстрация, а не съёмка
со стенда, и страница так её и подписывает (`content.compare.video.credit`).

| Шаг | Что | Исходник (вне git) |
|---|---|---|
| Кадр А | ночная смена: обходчик фиолетовой ручкой пишет показание манометра в журнал на поручне | `docs/gemini_journal/frameA_obhodchik.jpg`, промпт `promptA.txt` |
| Кадр Б | та же точка съёмки: людей нет, журнал закрыт, на поручне камера на хомуте смотрит на шкалу | `docs/gemini_journal/frameB_camera.jpg` (запасной вариант `frameB_camera_alt.jpg`), промпт `promptB.txt` |
| Ролик | 10 с, 1280×720, 24 к/с: А на 0 с, Б на 10 с; обходчик дописывает и уходит, камера проявляется наплывом | `docs/gemini_journal/shift_video.mp4`, промпт `promptV.txt` |

| Файл | Что это | Размер |
|---|---|---|
| `shift.scrub.mp4` | копия для перемотки прокруткой: 1280×720, каждый кадр ключевой, без звука, moov в начале | 8,6 МБ |
| `shift.scrub-m.mp4` | то же для экранов до 768 px: 854×480 | 4,4 МБ |
| `../img/shift-before.jpg` | первый кадр ролика — постер и левый кадр при «уменьшить движение» | 140 КБ |
| `../img/shift-after.jpg` | последний кадр ролика — правый кадр при «уменьшить движение» и замена, если ролик не загрузился | 133 КБ |

Почему каждый кадр ключевой: `video.currentTime` при прокрутке прыгает в любую точку ролика. С редкими
ключевыми кадрами браузер декодирует всё от ближайшего ключевого, и перемотка дёргается; при `-g 1`
каждый кадр декодируется сам по себе.

## Команды

ffmpeg 7.1 из пакета `imageio_ffmpeg` (Python 3.14), запуск из корня репозитория:

```
F="C:/Users/Egoru/AppData/Local/Programs/Python/Python314/Lib/site-packages/imageio_ffmpeg/binaries/ffmpeg-win-x86_64-v7.1.exe"
SRC=docs/gemini_journal/shift_video.mp4

"$F" -i "$SRC" -an -c:v libx264 -preset slow -crf 24 \
  -g 1 -keyint_min 1 -sc_threshold 0 -bf 0 -pix_fmt yuv420p -profile:v high \
  -movflags +faststart site/assets/video/shift.scrub.mp4

"$F" -i "$SRC" -an -vf scale=854:480:flags=lanczos -c:v libx264 -preset slow -crf 25 \
  -g 1 -keyint_min 1 -sc_threshold 0 -bf 0 -pix_fmt yuv420p -profile:v high \
  -movflags +faststart site/assets/video/shift.scrub-m.mp4
```

Постеры — первый и последний кадр ролика через OpenCV (mjpeg-кодер этой сборки ffmpeg отказывается
писать JPEG из yuv420p ограниченного диапазона):

```
python -c "import cv2; c=cv2.VideoCapture('docs/gemini_journal/shift_video.mp4'); n=int(c.get(7)); \
[ (c.set(1,i), cv2.imwrite(p, c.read()[1], [cv2.IMWRITE_JPEG_QUALITY, 82, cv2.IMWRITE_JPEG_PROGRESSIVE, 1])) \
  for i, p in [(0,'site/assets/img/shift-before.jpg'), (n-1,'site/assets/img/shift-after.jpg')] ]"
```

Бюджеты и параметры копий проверяет `node site/tests/check.js`: размер, отсутствие звука, moov перед mdat,
ключевой кадр не реже каждого второго кадра.
