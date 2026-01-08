#!/usr/bin/env python3
import json
import os
import random
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError

# ================== Configuration ==================
# Single-port UDP choice: "hy2" (default) or "tuic"
SINGLE_PORT_UDP = "hy2"

# Default ports when SERVER_PORT is not set (space-separated).
# Example: "443" for single-port, or "443 8443" for multi-port.
DEFAULT_PORTS = ""

# Argo settings:
# - ARGO_TOKEN: fixed tunnel token; empty means Quick Tunnel.
# - ARGO_DOMAIN: your fixed tunnel domain (required to emit Argo node in subscription).
# - ARGO_PORT: local port cloudflared forwards to (default 8081).
ARGO_TOKEN = os.environ.get("ARGO_TOKEN", "").strip()
ARGO_DOMAIN_OVERRIDE = os.environ.get("ARGO_DOMAIN", "").strip()
ARGO_PORT = int(os.environ.get("ARGO_PORT", "8081"))

CF_DOMAINS = [
    "cf.090227.xyz",
    "cf.877774.xyz",
    "cf.130519.xyz",
    "cf.008500.xyz",
    "store.ubi.com",
    "saas.sin.fan",
]

# ================== Switch to script directory ==================
BASE_DIR = Path(__file__).resolve().parent
os.chdir(BASE_DIR)
FILE_PATH = BASE_DIR / ".npm"

if FILE_PATH.exists():
    shutil.rmtree(FILE_PATH)
FILE_PATH.mkdir(parents=True, exist_ok=True)

# ================== Helpers ==================

def fetch_text(url, timeout):
    req = Request(url, headers={"User-Agent": "curl/7.79.1"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            data = resp.read()
        return data.decode("utf-8", errors="ignore").strip()
    except URLError:
        return ""
    except Exception:
        return ""


def select_random_cf_domain():
    available = []
    for domain in CF_DOMAINS:
        if fetch_text(f"https://{domain}", timeout=2):
            available.append(domain)
    if available:
        return random.choice(available)
    return CF_DOMAINS[0]


# ================== Public IP ==================
print("[network] fetching public IP...")
PUBLIC_IP = fetch_text("https://ipv4.ip.sb", timeout=5) or fetch_text("https://api.ipify.org", timeout=5)
if not PUBLIC_IP:
    print("[error] unable to get public IP")
    sys.exit(1)
print(f"[network] public IP: {PUBLIC_IP}")

# ================== CF preferred domain ==================
print("[CF] testing...")
BEST_CF_DOMAIN = select_random_cf_domain()
print(f"[CF] {BEST_CF_DOMAIN}")

# ================== Ports ==================
PORTS_STRING = os.environ.get("SERVER_PORT", "").strip() or DEFAULT_PORTS
AVAILABLE_PORTS = PORTS_STRING.split() if PORTS_STRING else []
PORT_COUNT = len(AVAILABLE_PORTS)
if PORT_COUNT == 0:
    print("[error] no ports found; set SERVER_PORT, e.g. 'SERVER_PORT=443'")
    sys.exit(1)
print(f"[port] found {PORT_COUNT}: {' '.join(AVAILABLE_PORTS)}")

if PORT_COUNT == 1:
    UDP_PORT = AVAILABLE_PORTS[0]
    TUIC_PORT = ""
    HY2_PORT = ""
    if SINGLE_PORT_UDP == "tuic":
        TUIC_PORT = UDP_PORT
    else:
        HY2_PORT = UDP_PORT
    REALITY_PORT = ""
    HTTP_PORT = AVAILABLE_PORTS[0]
    SINGLE_PORT_MODE = True
else:
    TUIC_PORT = AVAILABLE_PORTS[0]
    HY2_PORT = AVAILABLE_PORTS[1]
    REALITY_PORT = AVAILABLE_PORTS[0]
    HTTP_PORT = AVAILABLE_PORTS[1]
    SINGLE_PORT_MODE = False

# ================== UUID ==================
UUID_FILE = FILE_PATH / "uuid.txt"
if UUID_FILE.exists():
    UUID = UUID_FILE.read_text(encoding="utf-8").strip()
else:
    UUID = str(uuid.uuid4())
    UUID_FILE.write_text(UUID, encoding="utf-8")
print(f"[uuid] {UUID}")

# ================== Arch & download ==================
ARCH = os.uname().machine if hasattr(os, "uname") else os.environ.get("PROCESSOR_ARCHITECTURE", "")
BASE_URL = "https://arm64.ssss.nyc.mn" if ARCH == "aarch64" else "https://amd64.ssss.nyc.mn"
ARGO_ARCH = "arm64" if ARCH == "aarch64" else "amd64"

SB_FILE = FILE_PATH / "sb"
ARGO_FILE = FILE_PATH / "cloudflared"


def download_file(url, output_path):
    if output_path.exists() and os.access(output_path, os.X_OK):
        return True
    print(f"[download] {output_path}...")
    try:
        req = Request(url, headers={"User-Agent": "curl/7.79.1"})
        with urlopen(req, timeout=60) as resp, open(output_path, "wb") as f:
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)
        os.chmod(output_path, 0o755)
        print(f"[download] {output_path} done")
        return True
    except Exception:
        print(f"[download] {output_path} failed")
        return False


if not download_file(f"{BASE_URL}/sb", SB_FILE):
    sys.exit(1)
if not download_file(f"https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-{ARGO_ARCH}", ARGO_FILE):
    sys.exit(1)

# ================== Reality keys ==================
private_key = ""
public_key = ""
if not SINGLE_PORT_MODE:
    print("[key] checking...")
    KEY_FILE = FILE_PATH / "key.txt"
    if KEY_FILE.exists():
        key_data = KEY_FILE.read_text(encoding="utf-8", errors="ignore")
    else:
        key_data = subprocess.check_output([str(SB_FILE), "generate", "reality-keypair"], text=True)
        KEY_FILE.write_text(key_data, encoding="utf-8")
    m_priv = re.search(r"PrivateKey:\s*(\S+)", key_data)
    m_pub = re.search(r"PublicKey:\s*(\S+)", key_data)
    private_key = m_priv.group(1) if m_priv else ""
    public_key = m_pub.group(1) if m_pub else ""
    print("[key] ready")

# ================== Certificates ==================
print("[cert] generating...")
PRIVATE_KEY = FILE_PATH / "private.key"
CERT_FILE = FILE_PATH / "cert.pem"

openssl = shutil.which("openssl")
if openssl:
    subprocess.run(
        [
            openssl,
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-sha256",
            "-keyout",
            str(PRIVATE_KEY),
            "-out",
            str(CERT_FILE),
            "-days",
            "3650",
            "-subj",
            "/CN=www.bing.com",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )
else:
    PRIVATE_KEY.write_text(
        "-----BEGIN EC PRIVATE KEY-----\n"
        "MHcCAQEEIM4792SEtPqIt1ywqTd/0bYidBqpYV/+siNnfBYsdUYsoAoGCCqGSM49\n"
        "AwEHoUQDQgAE1kHafPj07rJG+HboH2ekAI4r+e6TL38GWASAnngZreoQDF16ARa/\n"
        "TsyLyFoPkhTxSbehH/OBEjHtSZGaDhMqQ==\n"
        "-----END EC PRIVATE KEY-----\n",
        encoding="utf-8",
    )
    CERT_FILE.write_text(
        "-----BEGIN CERTIFICATE-----\n"
        "MIIBejCCASGgAwIBAgIUFWeQL3556PNJLp/veCFxGNj9crkwCgYIKoZIzj0EAwIw\n"
        "EzERMA8GA1UEAwwIYmluZy5jb20wHhcNMjUwMTAxMDEwMTAwWhcNMzUwMTAxMDEw\n"
        "MTAwWjATMREwDwYDVQQDDAhiaW5nLmNvbTBZMBMGByqGSM49AgEGCCqGSM49AwEH\n"
        "A0IABNZB2nz49O6yRvh26B9npACOK/nuky9/BlgEgJ54Ga3qEAxdegEWv07Mi8ha\n"
        "D5IU8Um3oR/zgRIx7UmRmg4TKkOjUzBRMB0GA1UdDgQWBBTV1cFID7UISE7PLTBR\n"
        "BfGbgrkMNzAfBgNVHSMEGDAWgBTV1cFID7UISE7PLTBRBfGbgrkMNzAPBgNVHRMB\n"
        "Af8EBTADAQH/MAoGCCqGSM49BAMCA0cAMEQCIARDAJvg0vd/ytrQVvEcSm6XTlB+\n"
        "eQ6OFb9LbLYL9Zi+AiB+foMbi4y/0YUQlTtz7as9S8/lciBF5VCUoVIKS+vX2g==\n"
        "-----END CERTIFICATE-----\n",
        encoding="utf-8",
    )
print("[cert] ready")

# ================== ISP ==================
isp = "Node"
meta = fetch_text("https://speed.cloudflare.com/meta", timeout=2)
if meta:
    try:
        data = json.loads(meta)
        org = data.get("asOrganization") or data.get("asName") or ""
        country = data.get("clientCountry") or ""
        isp = f"{org}-{country}".strip("-") if (org or country) else "Node"
    except Exception:
        pass

# ================== Subscription generation ==================

def generate_sub(argo_domain):
    lines = []
    if TUIC_PORT:
        lines.append(
            f"tuic://{UUID}:admin@{PUBLIC_IP}:{TUIC_PORT}?sni=www.bing.com&alpn=h3&congestion_control=bbr&allowInsecure=1#TUIC-{isp}"
        )
    if HY2_PORT:
        lines.append(
            f"hysteria2://{UUID}@{PUBLIC_IP}:{HY2_PORT}/?sni=www.bing.com&insecure=1#Hysteria2-{isp}"
        )
    if REALITY_PORT:
        lines.append(
            f"vless://{UUID}@{PUBLIC_IP}:{REALITY_PORT}?encryption=none&flow=xtls-rprx-vision&security=reality&sni=www.nazhumi.com&fp=chrome&pbk={public_key}&type=tcp#Reality-{isp}"
        )
    if argo_domain:
        lines.append(
            f"vless://{UUID}@{BEST_CF_DOMAIN}:443?encryption=none&security=tls&sni={argo_domain}&type=ws&host={argo_domain}&path=%2F{UUID}-vless#Argo-{isp}"
        )

    list_path = FILE_PATH / "list.txt"
    sub_path = FILE_PATH / "sub.txt"
    content = "\n".join(lines) + "\n"
    list_path.write_text(content, encoding="utf-8")
    sub_path.write_text(content, encoding="utf-8")


# ================== HTTP server ==================
class SubHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if "/sub" in self.path or f"/{UUID}" in self.path:
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            try:
                self.wfile.write((FILE_PATH / "sub.txt").read_bytes())
            except Exception:
                self.wfile.write(b"error")
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"404")

    def log_message(self, _format, *_args):
        return


def start_http_server(port, bind):
    server = HTTPServer((bind, port), SubHandler)
    server.serve_forever()


print(f"[HTTP] starting subscription server on port {HTTP_PORT}...")
threading.Thread(target=start_http_server, args=(int(HTTP_PORT), "0.0.0.0"), daemon=True).start()
time.sleep(1)
print("[HTTP] subscription server started")

# ================== sing-box config ==================
print("[config] generating...")

inbounds = []
if TUIC_PORT:
    inbounds.append(
        {
            "type": "tuic",
            "tag": "tuic-in",
            "listen": "::",
            "listen_port": int(TUIC_PORT),
            "users": [{"uuid": UUID, "password": "admin"}],
            "congestion_control": "bbr",
            "tls": {
                "enabled": True,
                "alpn": ["h3"],
                "certificate_path": str(CERT_FILE),
                "key_path": str(PRIVATE_KEY),
            },
        }
    )

if HY2_PORT:
    inbounds.append(
        {
            "type": "hysteria2",
            "tag": "hy2-in",
            "listen": "::",
            "listen_port": int(HY2_PORT),
            "users": [{"password": UUID}],
            "tls": {
                "enabled": True,
                "alpn": ["h3"],
                "certificate_path": str(CERT_FILE),
                "key_path": str(PRIVATE_KEY),
            },
        }
    )

if REALITY_PORT:
    inbounds.append(
        {
            "type": "vless",
            "tag": "vless-reality-in",
            "listen": "::",
            "listen_port": int(REALITY_PORT),
            "users": [{"uuid": UUID, "flow": "xtls-rprx-vision"}],
            "tls": {
                "enabled": True,
                "server_name": "www.nazhumi.com",
                "reality": {
                    "enabled": True,
                    "handshake": {"server": "www.nazhumi.com", "server_port": 443},
                    "private_key": private_key,
                    "short_id": [""],
                },
            },
        }
    )

inbounds.append(
    {
        "type": "vless",
        "tag": "vless-argo-in",
        "listen": "127.0.0.1",
        "listen_port": int(ARGO_PORT),
        "users": [{"uuid": UUID}],
        "transport": {"type": "ws", "path": f"/{UUID}-vless"},
    }
)

config = {
    "log": {"level": "warn"},
    "inbounds": inbounds,
    "outbounds": [{"type": "direct", "tag": "direct"}],
}

CONFIG_FILE = FILE_PATH / "config.json"
CONFIG_FILE.write_text(json.dumps(config, indent=2), encoding="utf-8")
print("[config] generated")

# ================== start sing-box ==================
print("[sing-box] starting...")

sb_proc = subprocess.Popen([str(SB_FILE), "run", "-c", str(CONFIG_FILE)])
time.sleep(2)

if sb_proc.poll() is not None:
    print("[sing-box] failed to start")
    try:
        with open(PRIVATE_KEY, "r", encoding="utf-8", errors="ignore") as f:
            for _ in range(2):
                line = f.readline()
                if not line:
                    break
                print(line.rstrip())
    except Exception:
        pass
    subprocess.call([str(SB_FILE), "run", "-c", str(CONFIG_FILE)])
    sys.exit(1)

print(f"[sing-box] started PID: {sb_proc.pid}")

# ================== Argo tunnel ==================
ARGO_LOG = FILE_PATH / "argo.log"
ARGO_DOMAIN = ARGO_DOMAIN_OVERRIDE

if ARGO_TOKEN:
    print("[Argo] starting fixed tunnel...")
    with open(ARGO_LOG, "w", encoding="utf-8") as log_f:
        argo_proc = subprocess.Popen(
            [
                str(ARGO_FILE),
                "tunnel",
                "--no-autoupdate",
                "run",
                "--token",
                ARGO_TOKEN,
            ],
            stdout=log_f,
            stderr=subprocess.STDOUT,
        )
    if ARGO_DOMAIN:
        print(f"[Argo] domain: {ARGO_DOMAIN}")
    else:
        print("[Argo] warning: ARGO_DOMAIN not set; subscription will omit Argo node")
else:
    print("[Argo] starting quick tunnel (HTTP2 mode)...")
    with open(ARGO_LOG, "w", encoding="utf-8") as log_f:
        argo_proc = subprocess.Popen(
            [
                str(ARGO_FILE),
                "tunnel",
                "--edge-ip-version",
                "auto",
                "--protocol",
                "http2",
                "--no-autoupdate",
                "--url",
                f"http://127.0.0.1:{ARGO_PORT}",
            ],
            stdout=log_f,
            stderr=subprocess.STDOUT,
        )

    for _ in range(30):
        time.sleep(1)
        try:
            log_text = ARGO_LOG.read_text(encoding="utf-8", errors="ignore")
            m = re.search(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", log_text)
            if m:
                ARGO_DOMAIN = m.group(0).replace("https://", "")
                break
        except Exception:
            pass

    if ARGO_DOMAIN:
        print(f"[Argo] domain: {ARGO_DOMAIN}")
    else:
        print("[Argo] failed to get domain")

# ================== Subscription ==================
generate_sub(ARGO_DOMAIN)
SUB_URL = f"http://{PUBLIC_IP}:{HTTP_PORT}/sub"

print("\n===================================================")
if SINGLE_PORT_MODE:
    mode = SINGLE_PORT_UDP.upper()
    print(f"mode: single port ({mode} + Argo)")
    print("\nproxy nodes:")
    if HY2_PORT:
        print(f"  - HY2 (UDP): {PUBLIC_IP}:{HY2_PORT}")
    if TUIC_PORT:
        print(f"  - TUIC (UDP): {PUBLIC_IP}:{TUIC_PORT}")
    if ARGO_DOMAIN:
        print(f"  - Argo (WS): {ARGO_DOMAIN}")
else:
    print("mode: multi port (TUIC + HY2 + Reality + Argo)")
    print("\nproxy nodes:")
    print(f"  - TUIC (UDP): {PUBLIC_IP}:{TUIC_PORT}")
    print(f"  - HY2 (UDP): {PUBLIC_IP}:{HY2_PORT}")
    print(f"  - Reality (TCP): {PUBLIC_IP}:{REALITY_PORT}")
    if ARGO_DOMAIN:
        print(f"  - Argo (WS): {ARGO_DOMAIN}")

print("")
print(f"subscription URL: {SUB_URL}")
print("===================================================\n")

# ================== Keep running ==================
sb_proc.wait()
