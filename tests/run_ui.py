"""网页自动检查（2026-11-26）：开一个演示服务（随便找个空端口，不写 data），跑 tests/check_ui.mjs，跑完关掉。
用法：py -3 tests/run_ui.py [--config 包的 config.json]   退出码 0 = 全过。没有 node 或浏览器就跳过（退出码 0，会说一声）。
"""
import argparse
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--config', default=os.path.join(ROOT, 'tests', 'no-config.json'), help='用哪份 config.json（默认不读电脑上的）')
    a = ap.parse_args()
    if not shutil.which('node'):
        print('SKIP 没装 node，网页检查跳过')
        return 0
    port = free_port()
    log = open(os.path.join(ROOT, 'tests', 'ui-demo.log'), 'w', encoding='utf-8')
    srv = subprocess.Popen([sys.executable, '-B', os.path.join(ROOT, 'server.py'), '--config', a.config, '--demo', '--port', str(port), '--no-alert', '--no-update-check'],
                           cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(f'http://127.0.0.1:{port}/', timeout=2)
                break
            except OSError:
                time.sleep(0.5)
        else:
            print('演示服务没起来，看 tests/ui-demo.log')
            return 1
        return subprocess.call(['node', os.path.join(ROOT, 'tests', 'check_ui.mjs'), f'http://127.0.0.1:{port}'])
    finally:
        srv.terminate()
        try:
            srv.wait(10)
        except subprocess.TimeoutExpired:
            srv.kill()
        log.close()


if __name__ == '__main__':
    sys.exit(main())
