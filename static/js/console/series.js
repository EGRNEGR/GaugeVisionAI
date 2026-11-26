// Ряды тренда: единый маршрут /api/instruments/{id}/trend (работает и для живой камеры, и для симуляции).
import { api, isoLocal, LEVEL_RANK } from './util.js';

export async function fetchSeries(instId, since, buckets, until = null) {
  const endMs = until ? until.getTime() : Date.now();
  const span = Math.max(1, (endMs - since.getTime()) / 1000);
  const step = Math.max(1, span / buckets);
  const qUntil = until ? `&until=${encodeURIComponent(isoLocal(until))}` : '';
  const rows = await api(
    `/api/instruments/${encodeURIComponent(instId)}/trend?since=${encodeURIComponent(isoLocal(since))}${qUntil}&step=${step.toFixed(3)}`
  );
  return {
    camId: instId,
    since: since.getTime(),
    stepMs: step * 1000,
    points: rows.map((r) => ({ t: Date.parse(r.t), min: r.min, max: r.max, avg: r.avg, n: r.n, level: r.level })),
  };
}

export function pushLive(series, tsMs, value, level) {
  if (!series || value === null || value === undefined || tsMs < series.since) return;
  const b = Math.floor((tsMs - series.since) / series.stepMs);
  const t = series.since + b * series.stepMs;
  const last = series.points[series.points.length - 1];
  if (last && Math.abs(last.t - t) < series.stepMs / 2) {
    last.min = Math.min(last.min, value);
    last.max = Math.max(last.max, value);
    last.avg = (last.avg * last.n + value) / (last.n + 1);
    last.n += 1;
    if (LEVEL_RANK[level] > LEVEL_RANK[last.level]) last.level = level;
  } else if (!last || t > last.t) {
    series.points.push({ t, min: value, max: value, avg: value, n: 1, level: level || 'normal' });
  }
}
