import asyncio
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
import test_chat
from mcqq import media
from mcqq.store import Store

IMAGE = "https://multimedia.nt.qq.com.cn/download?appid=1407&fileid=test&rkey=signed"


class ExtractionTests(unittest.TestCase):
    def test_image_only_and_mixed_nested_attachments(self):
        value = media.extract({"content":"", "attachments":[{"content_type":"image/png","url":IMAGE}]})
        self.assertEqual(value, {"text":"", "media":[{"url":IMAGE,"kind":"image"}]})
        value = media.extract({"content":"hello", "msg_elements":[{"attachments":[{"filename":"sticker.gif","url":"//gchat.qpic.cn/a.gif"}]}]})
        self.assertEqual(value["text"],"hello")
        self.assertEqual(value["media"][0], {"url":"https://gchat.qpic.cn/a.gif","kind":"sticker"})

    def test_qq_face_json_is_a_sticker_not_raw_json(self):
        value=media.extract({"content":'{"faceType":1,"faceId":"9","ext":"opaque"}'})
        self.assertEqual(value["text"],"")
        self.assertEqual(value["media"],[{"kind":"sticker","url":"https://qzonestyle.gtimg.cn/qzone/em/e9.gif"}])

    def test_untrusted_urls_and_html_are_not_images(self):
        for url in ("http://127.0.0.1/", "https://evil.qq.com.attacker.test/", "https://qq.com@127.0.0.1/", "file:///a", "https://qq.com:18765/"):
            with self.assertRaises(ValueError): media.qq_url(url)
        with self.assertRaises(ValueError): media.image_type(b"<html>not an image")


class MediaHTTPTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=test_chat.ChatTests.asyncSetUp
    asyncTearDown=test_chat.ChatTests.asyncTearDown
    post=test_chat.ChatTests.post
    qq=test_chat.ChatTests.qq

    async def test_unbound_name_only_and_image_without_text(self):
        data=self.qq(nickname="六月大仁菜",media=[{"url":IMAGE,"kind":"image"}])
        data["text"]=""
        with patch("mcqq.media.fetch",new=AsyncMock(return_value=(IMAGE,"image/png",".png",b""))):
            self.assertEqual((await self.post("from-qq",data)).status,200)
        item=(await (await self.post("to-game",{},True)).json())["messages"][0]
        self.assertEqual(item["name"],"六月大仁菜")
        self.assertNotIn("member",item["name"])
        self.assertEqual(item["media"],[{"url":IMAGE,"kind":"image"}])
        with Store(self.cfg["database"]).connect() as db:
            self.assertEqual(db.execute("SELECT member_openid FROM chat_sender_log").fetchone()[0],"member")

    async def test_missing_nickname_does_not_expose_id(self):
        await self.post("from-qq",self.qq())
        item=(await (await self.post("to-game",{},True)).json())["messages"][0]
        self.assertEqual(item["name"],"群友")

    async def test_fallback_is_public_image_only_and_expires(self):
        cfg=dict(self.cfg,media={"public_base_url":"http://lemoe.luotiany1.top:18766/mcqq-media"})
        app=web.Application()
        resolve,serve,cleanup=media.register(app,cfg,Store(self.cfg["database"]))
        app.router.add_get("/mcqq-media/{name}",serve)
        client=TestClient(TestServer(app)); await client.start_server()
        self.addAsyncCleanup(client.close)
        content=b"GIF89a"+b"0"*30
        mock=AsyncMock(side_effect=[ValueError("not public"),(IMAGE,"image/gif",".gif",content)])
        async with aiohttp.ClientSession() as session:
            with patch("mcqq.media.fetch",new=mock):
                result=await resolve(session,[{"url":IMAGE,"kind":"sticker"}])
        name=result[0]["url"].rsplit("/",1)[1]
        response=await client.get("/mcqq-media/"+name)
        self.assertEqual(response.status,200)
        self.assertEqual(await response.read(),content)
        self.assertEqual((await client.get("/v1/status")).status,404)
        with Store(self.cfg["database"]).connect() as db:
            db.execute("UPDATE chat_media SET expires=?",(time.time()-1,))
        self.assertEqual((await client.get("/mcqq-media/"+name)).status,404)
        cleanup()
        self.assertFalse((Path(self.cfg["database"]).parent/"media-temp"/name).exists())

    async def test_attachment_event_is_not_discarded_by_bot(self):
        from mcqq.bot import QQBot,RichGroupMessage
        from collections import OrderedDict
        bot=QQBot.__new__(QQBot); bot.settings=self.cfg; bot.seen=OrderedDict()
        bot.call_service=AsyncMock(return_value={"ok":True})
        data={"id":"photo-event","content":"","group_openid":"group","author":{"member_openid":"member"},"attachments":[{"url":IMAGE,"content_type":"image/jpeg"}]}
        message=RichGroupMessage(None,"event",data); message.raw_data=data
        await bot.on_group_message_create(message)
        bot.call_service.assert_awaited_once()
        self.assertEqual(bot.call_service.call_args.args[1]["media"][0]["kind"],"image")
