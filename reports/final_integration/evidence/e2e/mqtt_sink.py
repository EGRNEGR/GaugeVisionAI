"""Подписчик MQTT (библиотека amqtt, отдельное окружение инструментов): все сообщения — в JSONL.

    python mqtt_sink.py <port> <out.jsonl> [topic_filter]
"""
import asyncio
import json
import sys
import time

from amqtt.client import MQTTClient
from amqtt.mqtt.constants import QOS_1


async def main() -> None:
    port, out = int(sys.argv[1]), sys.argv[2]
    topic = sys.argv[3] if len(sys.argv) > 3 else "#"
    while True:
        cli = MQTTClient(config={"auto_reconnect": False})
        try:
            await cli.connect(f"mqtt://127.0.0.1:{port}/")
            await cli.subscribe([(topic, QOS_1)])
            with open(out, "a", encoding="utf-8") as f:
                while True:
                    msg = await cli.deliver_message()
                    pkt = msg.publish_packet
                    try:
                        payload = json.loads(pkt.payload.data.decode("utf-8"))
                    except (ValueError, UnicodeDecodeError):
                        payload = {"_bytes": len(pkt.payload.data)}
                    f.write(json.dumps({"rx": time.time(), "topic": pkt.variable_header.topic_name,
                                        "payload": payload}, ensure_ascii=False) + "\n")
                    f.flush()
        except Exception as exc:  # брокер остановлен — переподключение
            print(f"sink: {type(exc).__name__}: {exc}", flush=True)
            await asyncio.sleep(1.0)


asyncio.run(main())
