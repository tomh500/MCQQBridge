import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from mcqq.waifu_images import PortraitMaterials


class PortraitMaterialTests(unittest.IsolatedAsyncioTestCase):
    async def test_reuses_matching_platform_material(self):
        with tempfile.TemporaryDirectory() as temp:
            data = b'portrait'
            Path(temp, '123.jpg').write_bytes(data)
            name = 'mcqq-waifu-' + hashlib.sha256(data).hexdigest() + '.jpg'
            request = AsyncMock(return_value={'images': [{'file_name': name, 'url': 'qqbot-media://image/v1/test'}]})
            client = PortraitMaterials(SimpleNamespace(_http=SimpleNamespace(request=request)), temp)
            self.assertEqual(await client.resolve('https://lain.bgm.tv/pic/crt/l/a/b/123_crt_x.jpg'), 'qqbot-media://image/v1/test')
            request.assert_awaited_once()
