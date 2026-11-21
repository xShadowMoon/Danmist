"""运行副本中的离线回归测试。"""
import argparse
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

TESTS = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path[:0] = [str(TESTS.parent), str(TESTS)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-mutation', action='store_true',
                        help='在内存中故意关闭下一首切换，验证对应的测试会失败')
    args = parser.parse_args()
    runner = unittest.TextTestRunner(verbosity=2)
    loader = unittest.defaultTestLoader
    if args.verify_mutation:
        from test_backend import SongTests, server

        original = server.Hub.song_cmd

        def broken_song_cmd(hub, cmd, *args, **kwargs):
            result = original(hub, cmd, *args, **kwargs)
            if cmd == 'song_done':
                for song in hub.state.songs:
                    song.pop('now', None)
            return result

        # 运行与正常测试完全相同的用例，只改变本进程里的实现。
        with patch.object(server.Hub, 'song_cmd', broken_song_cmd):
            result = runner.run(SongTests('test_completion_advances_queue_and_request'))
    else:
        result = runner.run(loader.discover(str(TESTS), pattern='test_*.py'))
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
