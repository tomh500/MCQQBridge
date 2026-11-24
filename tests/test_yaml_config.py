import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from mcqq.config import load, read_mapping


class YamlConfigTest(unittest.TestCase):
    def test_json_and_yaml_configs_have_equivalent_meaning(self):
        config = {'database': 'data/db', 'afterglow_connection': 'bridge.yml',
                  'bot_token': 'b' * 32, 'proxy_token': 'p' * 32,
                  'allowed_groups': ['GROUP'], 'daily_waifu': {'enabled': True, 'credentials_file': 'secret.yml'}}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'secret.yml').write_text('password: "0123"\n', encoding='utf-8')
            paths = [root / 'settings.yml', root / 'settings.json']
            paths[0].write_text(yaml.safe_dump(config), encoding='utf-8')
            paths[1].write_text(json.dumps(config), encoding='utf-8')
            results = []
            for path in paths:
                with patch.dict(os.environ, {'MCQQ_SETTINGS': str(path)}):
                    results.append(load())
            self.assertEqual(results[0], results[1])
            self.assertEqual(results[0]['daily_waifu']['password'], '0123')

    def test_rejects_non_mapping(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'settings.yml'
            path.write_text('- item\n', encoding='utf-8')
            with self.assertRaises(ValueError):
                read_mapping(path)


if __name__ == '__main__':
    unittest.main()
