"""
Сторонний подписчик MQTT (amqtt) для проверки доставки GaugeVision AI.

Запускается окружением валидационных инструментов (не окружением приложения):
  <tools_py> mqtt_subscriber.py --port 18830 --topic "interrao/#" --out received.jsonl
Каждое полученное сообщение записывается строкой JSON: время, тема, event_uuid,
seq_id, размер; для сообщений `.../frame` — SHA-256 декодированного кадра.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import time

from amqtt.client import ClientError, MQTTClient
from amqtt.mqtt.constants import QOS_1


async def run(port: int, topic: str, out: str) -> None:
    while True:
        client = MQTTClient(config={"auto_reconnect": False})
        try:
            await client.connect(f"mqtt://127.0.0.1:{port}/")
            await client.subscribe([(topic, QOS_1)])
            with open(out, "a", encoding="utf-8") as fh:
                while True:
                    msg = await client.deliver_message()
                    raw = msg.data or b""
                    rec = {"t": time.time(), "topic": msg.topic, "bytes": len(raw)}
                    try:
                        body = json.loads(raw.decode("utf-8"))
                        rec["event_uuid"] = body.get("event_uuid")
                        rec["seq_id"] = body.get("seq_id")
                        if body.get("frame_b64"):
                            frame = base64.b64decode(body["frame_b64"])
                            rec["frame_sha256_actual"] = hashlib.sha256(frame).hexdigest()
                            rec["frame_sha256_declared"] = body.get("frame_sha256")
                    except (ValueError, UnicodeDecodeError):
                        rec["decode_error"] = True
                    fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    fh.flush()
        except (ClientError, ConnectionError, OSError, asyncio.IncompleteReadError):
            await asyncio.sleep(1.0)  # брокер перезапускается — переподключаемся
        except Exception:
            await asyncio.sleep(1.0)
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--topic", default="interrao/#")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    asyncio.run(run(args.port, args.topic, args.out))


if __name__ == "__main__":
    main()
