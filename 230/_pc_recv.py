# -*- coding: utf-8 -*-
# =============================================================================
#  电脑端接收器：接收 K230 推过来的诊断文件
#  用法: python _pc_recv.py
#  板子(ai_dump.py)会把 ai_meta.txt / stream.jpg / ai_raw.bin / model_in.bin
#  用 HTTP POST 推到这个服务上，文件落在 _dump 目录里。
# =============================================================================
import http.server
import os
import sys

PORT = 8000
OUT = r"D:\ai_project_tree\230\_dump"


class Handler(http.server.BaseHTTPRequestHandler):

    def do_POST(self):
        name = os.path.basename(self.path.lstrip('/').split('?')[0]) or 'unknown'
        total = int(self.headers.get('Content-Length', 0) or 0)
        os.makedirs(OUT, exist_ok=True)
        path = os.path.join(OUT, name)
        got = 0
        with open(path, 'wb') as f:
            while got < total:
                d = self.rfile.read(min(8192, total - got))
                if not d:
                    break
                f.write(d)
                got += len(d)
        print("[收到] %-16s %8d / %8d 字节" % (name, got, total), flush=True)
        body = b'OK'
        self.send_response(200)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        body = "PC receiver ready\n".encode()
        self.send_response(200)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass          # 不打印每一条访问日志，保持输出干净


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(errors='replace')
    except Exception:
        pass
    os.makedirs(OUT, exist_ok=True)
    srv = http.server.ThreadingHTTPServer(('0.0.0.0', PORT), Handler)
    print("PC 接收器已启动: 0.0.0.0:%d  ->  %s" % (PORT, OUT), flush=True)
    srv.serve_forever()
