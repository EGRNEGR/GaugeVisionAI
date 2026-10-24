"""
GaugeVision AI — автогенерация самоподписных SSL-сертификатов с SAN.

Мобильные браузеры (WebKit/Safari, Chromium) блокируют getUserMedia по
незащищённому HTTP на внешнем LAN-IP, поэтому сертификат ОБЯЗАН содержать
Subject Alternative Name: DNS localhost + IP 127.0.0.1 + реальный LAN IP хоста.
"""
from __future__ import annotations

import datetime as _dt
import ipaddress
import socket
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from . import config
from .config import candidate_lan_ips, get_lan_ip


def _build_subject_alt_names(lan_ip: str) -> list[x509.GeneralName]:
    """
    DNS: localhost (+ имя хоста); IP: 127.0.0.1; IP: реальный адрес хоста в LAN
    и остальные пригодные адреса интерфейсов (Wi-Fi + Ethernet и т.п.).
    """
    alt_names: list[x509.GeneralName] = [
        x509.DNSName("localhost"),
        x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
    ]
    try:
        host = socket.gethostname()
        if host and host.isascii() and host.lower() != "localhost":
            alt_names.append(x509.DNSName(host))
    except OSError:
        pass
    seen = {"127.0.0.1"}
    for ip in [lan_ip, *candidate_lan_ips()]:
        if ip in seen:
            continue
        try:
            alt_names.append(x509.IPAddress(ipaddress.IPv4Address(ip)))
            seen.add(ip)
        except (ipaddress.AddressValueError, ValueError):
            pass
    return alt_names


def generate_self_signed_cert(
    cert_path: Path = config.CERT_FILE,
    key_path: Path = config.KEY_FILE,
    lan_ip: str | None = None,
) -> tuple[Path, Path]:
    """
    Генерирует RSA-2048 ключ и самоподписный X.509 сертификат на 365 дней.

    Сертификат содержит расширения basicConstraints(CA=True), keyUsage и
    SubjectAltName. Возвращает пути (cert, key).
    """
    if lan_ip is None:
        lan_ip = get_lan_ip()

    key_path.parent.mkdir(parents=True, exist_ok=True)

    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=config.CERT_KEY_SIZE,
    )

    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "RU"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "GaugeVision AI"),
        x509.NameAttribute(NameOID.COMMON_NAME, lan_ip),
    ])

    now = _dt.datetime.now(_dt.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - _dt.timedelta(days=1))
        .not_valid_after(now + _dt.timedelta(days=config.CERT_VALID_DAYS))
        .add_extension(
            x509.SubjectAlternativeName(_build_subject_alt_names(lan_ip)),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_encipherment=True,
                content_commitment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(private_key, hashes.SHA256())
    )

    key_path.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return cert_path, key_path


def cert_san_ips(cert: x509.Certificate) -> list[str]:
    """IP-адреса из расширения SubjectAlternativeName сертификата."""
    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        return [str(ip) for ip in san.value.get_values_for_type(x509.IPAddress)]
    except x509.ExtensionNotFound:
        return []


def cert_fingerprint(cert_path: Path = config.CERT_FILE) -> str:
    """SHA-256 отпечаток сертификата (для сверки оператором на смартфоне)."""
    cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    digest = cert.fingerprint(hashes.SHA256()).hex().upper()
    return ":".join(digest[i:i + 2] for i in range(0, len(digest), 2))


def ensure_certs() -> tuple[Path, Path]:
    """
    Проверяет наличие валидного сертификата в certs/ и создаёт при отсутствии.

    Сертификат считается валидным, если оба файла существуют, парсятся и срок
    действия не истёк. Возвращает пути (cert, key).
    """
    cert_path, key_path = config.CERT_FILE, config.KEY_FILE
    lan_ip = get_lan_ip()
    if cert_path.exists() and key_path.exists():
        try:
            data = cert_path.read_bytes()
            cert = x509.load_pem_x509_certificate(data)
            now = _dt.datetime.now(_dt.timezone.utc)
            expires = cert.not_valid_after_utc
            if expires <= now:
                print("[SSL] Срок действия сертификата истёк — перегенерирую…")
            elif lan_ip not in cert_san_ips(cert) and not lan_ip.startswith("127."):
                print(f"[SSL] LAN IP хоста изменился ({lan_ip} нет в SAN) — перегенерирую…")
            else:
                return cert_path, key_path
        except Exception as exc:  # повреждённый файл -> пересоздаём
            print(f"[SSL] Не удалось прочитать сертификат ({exc}) — перегенерирую…")

    generate_self_signed_cert(cert_path, key_path, lan_ip)
    ips = ", ".join(dict.fromkeys([lan_ip, *candidate_lan_ips()]))
    print(f"[SSL] Создан самоподписный сертификат RSA-2048 на {config.CERT_VALID_DAYS} дн. "
          f"(SAN: localhost, 127.0.0.1, {ips})")
    return cert_path, key_path
