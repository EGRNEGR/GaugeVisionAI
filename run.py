"""
GaugeVision AI — единая точка запуска: `python run.py`

1. Проверяет/создаёт самоподписный SSL-сертификат с SAN в certs/.
2. Определяет реальный IP-адрес хоста в текущей Wi-Fi/LAN сети.
3. Выводит ASCII-баннер со ссылками https://localhost:8443 и https://<LAN_IP>:8443.
4. Запускает Uvicorn исключительно по HTTPS.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

from app import __app_name__, __version__, config
from app.cert_gen import cert_fingerprint, ensure_certs

BANNER = r"""
   ____                        __     ___     _                  _    ___
  / ___| __ _ _   _  __ _  ___ \ \   / (_)___(_) ___  _ __      / \  |_ _|
 | |  _ / _` | | | |/ _` |/ _ \ \ \ / /| / __| |/ _ \| '_ \    / _ \  | |
 | |_| | (_| | |_| | (_| |  __/  \ V / | \__ \ | (_) | | | |  / ___ \ | |
  \____|\__,_|\__,_|\__, |\___|   \_/  |_|___/_|\___/|_| |_| /_/   \_\___|
                    |___/
"""


def _enable_ansi() -> None:
    """Включает ANSI-цвета и UTF-8 вывод в консоли Windows."""
    if os.name == "nt":
        os.system("")
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:
            pass


def print_banner(lan_ip: str, port: int, fingerprint: str | None) -> None:
    g, y, c, b, r = "\033[92m", "\033[93m", "\033[96m", "\033[1m", "\033[0m"
    line = "═" * 78
    print(f"{c}{BANNER}{r}")
    print(f"  {b}{__app_name__} v{__version__}{r} — мультисенсорный мониторинг аналоговых КИПиА")
    print(f"  {line}")
    print(f"  {b}Дашборд оператора:{r}")
    print(f"    {g}➜  Этот ПК:          https://localhost:{port}{r}")
    print(f"    {g}➜  Сеть Wi-Fi / LAN: https://{lan_ip}:{port}{r}")
    others = [ip for ip in config.candidate_lan_ips() if ip != lan_ip]
    if others:
        print(f"    Другие адреса хоста: {', '.join(others)}  (выбор: python run.py --lan-ip <IP>)")
    print(f"  {line}")
    print(f"  {y}{b}Первый вход со смартфона или другого ПК (самоподписный сертификат):{r}")
    print(f"  {y}  • Android / Chrome: «Дополнительно» → «Перейти на сайт {lan_ip} (небезопасно)».{r}")
    print(f"  {y}  • iOS / Safari: «Подробнее» → «посетить этот веб-сайт» → «Посетить веб-сайт».{r}")
    print(f"  {y}  • Принять сертификат нужно один раз; без HTTPS браузеры запрещают доступ к камере.{r}")
    if fingerprint:
        print(f"    SHA-256 сертификата: {fingerprint[:47]}")
        print(f"                         {fingerprint[48:]}")
    print(f"  {line}")
    print(f"  Смартфон как камера: «Подключить смартфон» на дашборде → сканировать QR-код.")
    print(f"  БД: {config.DB_PATH}")
    print(f"  Остановка сервера: Ctrl+C\n", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=f"{__app_name__} — HTTPS-сервер")
    parser.add_argument("--host", default=config.HOST, help="адрес прослушивания (по умолчанию 0.0.0.0)")
    parser.add_argument("--port", type=int, default=config.HTTPS_PORT, help="HTTPS-порт (по умолчанию 8443)")
    parser.add_argument("--lan-ip", default=None,
                        help="IP-адрес хоста для ссылок и QR-кодов (по умолчанию определяется автоматически)")
    parser.add_argument("--log-level", default="info", choices=["debug", "info", "warning", "error"])
    args = parser.parse_args()
    if args.lan_ip:
        os.environ["GAUGEVISION_LAN_IP"] = args.lan_ip

    _enable_ansi()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s  %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.port != config.HTTPS_PORT:
        config.HTTPS_PORT = args.port  # ссылки QR-кодов используют фактический порт

    # 1. SSL-сертификат с SAN (localhost, 127.0.0.1, LAN IP)
    cert_file, key_file = ensure_certs()
    # 2. Реальный LAN IP
    lan_ip = config.get_lan_ip()
    fingerprint = None
    try:
        fingerprint = cert_fingerprint(cert_file)
    except Exception:
        pass
    # 3. Баннер
    print_banner(lan_ip, args.port, fingerprint)

    # 4. Uvicorn — только HTTPS
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        ssl_certfile=str(cert_file),
        ssl_keyfile=str(key_file),
        log_level=args.log_level,
        ws_max_size=16 * 1024 * 1024,
        proxy_headers=False,
        access_log=False,
    )


if __name__ == "__main__":
    main()
