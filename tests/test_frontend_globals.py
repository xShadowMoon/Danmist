"""网页的脚本（static/app/*.js）是几个普通 <script> 共用一套全局名字：
两个文件顶层声明了同一个 const / let / class，后加载的那个文件整个跑不起来（2026-11-28：isAnchor 撞名，songs.js 没加载，
页面卡在「连接中…」）。这里把顶层声明的名字都找出来，不许重名。"""
import os
import re
import unittest

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'static', 'app')
DECL = re.compile(r'^(?:const|let|class|function\*?|async function)\s+([A-Za-z_$][\w$]*)', re.M)
DESTRUCT = re.compile(r'^(?:const|let)\s+([A-Za-z_$][\w$]*)\s*=.*?,\s*([A-Za-z_$][\w$]*)\s*=', re.M)


class FrontendGlobalsTests(unittest.TestCase):
    def test_no_duplicate_top_level_names(self):
        seen = {}
        dups = []
        for name in sorted(os.listdir(APP)):
            if not name.endswith('.js'):
                continue
            with open(os.path.join(APP, name), encoding='utf-8') as f:
                src = f.read()
            names = set(DECL.findall(src))
            for a, b in DESTRUCT.findall(src):
                names.update((a, b))
            for n in names:
                if n in seen and seen[n] != name:
                    dups.append(f'{n}：{seen[n]} 和 {name}')
                seen.setdefault(n, name)
        self.assertEqual(dups, [], '这些名字在两个脚本里都声明了：' + '；'.join(dups))


if __name__ == '__main__':
    unittest.main()
