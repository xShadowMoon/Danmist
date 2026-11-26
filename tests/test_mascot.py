"""换看板娘（2026-11-26）：上传的尺寸校验、换没换过的版本号。"""
import os
import tempfile
import unittest

import input_validation as validation
import server


class MascotTests(unittest.TestCase):
    def test_only_known_sizes(self):
        for n in server.MASCOT_SIZES:
            self.assertEqual(validation.validate_http('mascot_put', {'size': str(n)}, {}), {'size': n})
        for bad in ('100', '0', '1024', 'abc', ''):
            with self.assertRaises(validation.InputError):
                validation.validate_http('mascot_put', {'size': bad}, {})

    def test_version_is_zero_until_replaced(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(server.mascot_ver(d), 0)
            self.assertEqual(server.mascot_ver(os.path.join(d, 'nope')), 0)
            path = os.path.join(d, 'icon-64.png')
            with open(path, 'wb') as f:
                f.write(b'\x89PNG\r\n\x1a\n')
            os.utime(path, (1700000000, 1700000000))
            self.assertEqual(server.mascot_ver(d), 1700000000)


if __name__ == '__main__':
    unittest.main()
