from __future__ import annotations

import concurrent.futures
import csv
import datetime as dt
import ipaddress
import json
import socket
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent
MAX_PORTS = 64
HISTORY_FILE = ROOT / "history.csv"


def check_port(host: str, port: int) -> dict:
    try:
        with socket.create_connection((host, port), timeout=1.5):
            return {"port": port, "open": True}
    except OSError:
        return {"port": port, "open": False}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_GET(self) -> None:
        if urlparse(self.path).path == "/api/history":
            history = []
            if HISTORY_FILE.exists():
                try:
                    with HISTORY_FILE.open("r", encoding="utf-8-sig", newline="") as file:
                        for row in csv.DictReader(file):
                            try:
                                ports = json.loads(row.get("open_ports", "[]"))
                                history.append({
                                    "checkedAt": row.get("checked_at", ""),
                                    "host": row.get("host", ""),
                                    "openPorts": ports if isinstance(ports, list) else [],
                                })
                            except (json.JSONDecodeError, TypeError):
                                continue
                except OSError:
                    self._json({"error": "이력 파일을 읽지 못했습니다."}, 500)
                    return
            self._json({"history": history})
            return
        super().do_GET()

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/api/check":
            self.send_error(404)
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size > 16_384:
                raise ValueError("요청이 너무 큽니다.")
            payload = json.loads(self.rfile.read(size))
            host = str(payload.get("host", "")).strip()
            if not host or len(host) > 253 or any(c.isspace() for c in host):
                raise ValueError("IP 또는 호스트 이름을 확인하세요.")
            try:
                ipaddress.ip_address(host)
            except ValueError:
                if any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-" for c in host):
                    raise ValueError("IP 또는 호스트 이름을 확인하세요.")
            ports = payload.get("ports")
            if not isinstance(ports, list) or not ports or len(ports) > MAX_PORTS:
                raise ValueError(f"포트는 1~{MAX_PORTS}개 입력할 수 있습니다.")
            ports = sorted(set(int(p) for p in ports))
            if any(p < 1 or p > 65535 for p in ports):
                raise ValueError("포트 번호는 1~65535 범위여야 합니다.")
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            self._json({"error": str(error)}, 400)
            return

        with concurrent.futures.ThreadPoolExecutor(max_workers=min(16, len(ports))) as pool:
            results = list(pool.map(lambda port: check_port(host, port), ports))
        checked_at = dt.datetime.now().astimezone().isoformat(timespec="seconds")
        opened = [item["port"] for item in results if item["open"]]
        try:
            write_header = not HISTORY_FILE.exists() or HISTORY_FILE.stat().st_size == 0
            with HISTORY_FILE.open("a", encoding="utf-8", newline="") as file:
                writer = csv.writer(file)
                if write_header:
                    file.write("\ufeff")
                    writer.writerow(["checked_at", "host", "open_ports"])
                writer.writerow([checked_at, host, json.dumps(opened, ensure_ascii=False)])
                file.flush()
        except OSError:
            self._json({"error": "검사 결과를 history.csv에 저장하지 못했습니다."}, 500)
            return
        self._json({"host": host, "checkedAt": checked_at, "results": results})

    def _json(self, body: dict, status: int = 200) -> None:
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, format: str, *args) -> None:
        pass


if __name__ == "__main__":
    address = ("127.0.0.1", 8765)
    print("IP 포트 헬스체크가 실행 중입니다: http://127.0.0.1:8765")
    print("종료하려면 이 창을 닫거나 Ctrl+C를 누르세요.")
    ThreadingHTTPServer(address, Handler).serve_forever()
