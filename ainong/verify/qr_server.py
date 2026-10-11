"""本地扫码页面的 HTTP 服务。

页面自己按固定间隔拉新的二维码并显示，不依赖聊天工具传递图片——
从生成到显示没有额外延迟。二维码真实寿命比看起来短：扫码后手机端还要经
一次 `txz.qq.com` 跳转才回到授权页，所以刷新间隔要留得比直觉更短。

只用标准库，不引新依赖。
"""

from __future__ import annotations

import http.server
import socketserver
import threading
import time
from pathlib import Path

_轮询秒 = 10


def 启动(二维码路径: str, 端口: int = 8765) -> tuple[socketserver.TCPServer, str]:
    """起一个只提供二维码的服务，返回 (服务实例, 访问地址)。"""
    路径 = Path(二维码路径)

    class 处理器(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            # 页面用时间戳做查询参数绕缓存，所以只看路径不看查询串。
            路径部分 = self.path.split("?", 1)[0]
            if 路径部分 == "/qr.png":
                try:
                    数据 = 路径.read_bytes()
                except OSError:
                    self.send_error(404, "二维码尚未生成")
                    return
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(数据)))
                self.end_headers()
                self.wfile.write(数据)
                return

            页面 = (
                "<!doctype html><meta charset=utf-8>"
                "<title>爱农 扫码</title>"
                "<style>body{margin:0;background:#111;color:#eee;"
                "font-family:system-ui;display:flex;flex-direction:column;"
                "align-items:center;justify-content:center;height:100vh;gap:14px}"
                "img{width:340px;height:340px;background:#fff;padding:10px;"
                "border-radius:8px}p{margin:0;font-size:14px;opacity:.75}"
                "#t{font-variant-numeric:tabular-nums}</style>"
                "<img id=q src='/qr.png?_=0'>"
                "<p>用手机 QQ 扫描 · 每 5 秒自动换新</p>"
                "<p id=t></p>"
                "<script>let s=0;setInterval(()=>{q.src='/qr.png?_='+(++s)},5000);"
                "setInterval(()=>{t.textContent=new Date().toLocaleTimeString()},1000)"
                "</script>"
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(页面)))
            self.end_headers()
            self.wfile.write(页面)

        def log_message(self, *args: object) -> None:
            pass

    服务 = socketserver.TCPServer(("127.0.0.1", 端口), 处理器)
    线程 = threading.Thread(target=服务.serve_forever, daemon=True)
    线程.start()
    return 服务, f"http://127.0.0.1:{端口}"


def 开浏览器(地址: str) -> None:
    import webbrowser

    webbrowser.open(地址)


if __name__ == "__main__":
    import sys

    路径 = sys.argv[1] if len(sys.argv) > 1 else "ainong_qq_qr.png"
    端口 = int(sys.argv[2]) if len(sys.argv) > 2 else 8765

    实例, 地址 = 启动(路径, 端口)
    print(f"扫码页面：{地址}")
    print(f"二维码来源：{路径}")
    print("Ctrl-C 结束")
    开浏览器(地址)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        实例.shutdown()
