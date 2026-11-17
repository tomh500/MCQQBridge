import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from mcqq.waifu_images import PortraitMaterials
from mcqq.waifu_preferences import learn, similarity, pick


class PreferenceTests(unittest.TestCase):
    def test_vector_uses_shared_tags_and_handles_empty(self):
        first = {'features': ['作品:A', '题材:校园']}
        same = {'features': ['作品:A', '题材:校园']}
        other = {'features': ['作品:B']}
        vector = learn({}, first)
        self.assertGreater(similarity(vector, same), similarity(vector, other))
        self.assertEqual(similarity({}, same), 0)
        self.assertIn(pick([first, other], vector), [first, other])


class MaterialTests(unittest.IsolatedAsyncioTestCase):
    async def test_existing_official_material_is_reused(self):
        with tempfile.TemporaryDirectory() as temp:
            content = b'test-image'
            Path(temp, '123.jpg').write_bytes(content)
            filename = 'mcqq-waifu-' + hashlib.sha256(content).hexdigest() + '.jpg'
            request = AsyncMock(return_value={'images': [{'file_name': filename, 'url': 'qqbot-media://image/v1/test'}]})
            materials = PortraitMaterials(SimpleNamespace(_http=SimpleNamespace(request=request)), temp)
            self.assertEqual(await materials.resolve('https://lain.bgm.tv/pic/crt/l/a/b/123_crt_x.jpg'), 'qqbot-media://image/v1/test')
            self.assertEqual(request.await_count, 1)
