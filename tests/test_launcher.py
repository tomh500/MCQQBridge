import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from mcqq.launcher import Challenges, groups, reply
from mcqq.service import create_app


class ChallengeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.clock = 10000
        self.store = Challenges(Path(self.temp.name) / "auth.sqlite", lambda: self.clock)

    def test_secret_and_identity_and_expiry(self):
        ticket = self.store.create()
        self.assertEqual("pending", self.store.status(ticket["code"], ticket["secret"])["state"])
        with self.assertRaises(web.HTTPUnauthorized):
            self.store.status(ticket["code"], "wrong" * 10)
        self.assertTrue(self.store.complete(ticket["code"], "member", "123456789", "event"))
        self.assertFalse(self.store.complete(ticket["code"], "other", "123456789", "other-event"))
        state = self.store.status(ticket["code"], ticket["secret"])
        self.assertEqual((state["member"], state["group"]), ("member", "123456789"))
        self.clock += 601
        self.assertEqual("expired", self.store.status(ticket["code"], ticket["secret"])["state"])
        self.assertFalse(self.store.complete(ticket["code"], "member", "123456789", "new"))

    def test_event_replay_does_not_unlock_second_challenge(self):
        one, two = self.store.create(), self.store.create()
        self.assertTrue(self.store.complete(one["code"], "m", "123456789", "same-event"))
        self.assertFalse(self.store.complete(two["code"], "m", "123456789", "same-event"))
        self.assertEqual("pending", self.store.status(two["code"], two["secret"])["state"])

    def test_fail_closed_configuration(self):
        self.assertEqual({}, groups({"allowed_groups": []}))
        self.assertEqual({}, groups({"allowed_groups": ["one", "two"]}))
        self.assertEqual({}, groups({"launcher_groups": {"one": "963526637"}}))
        self.assertEqual({"one": "123456789"}, groups({"allowed_groups": ["one"], "group_number": "123456789"}))


class IntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.cfg = dict(database=str(Path(self.temp.name) / "db.sqlite"),
                        bot_token="b" * 40, proxy_token="p" * 40, app_id="app",
                        allowed_groups=["official-group"], group_number="123456789")
        self.client = TestClient(TestServer(create_app(self.cfg)))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.temp.cleanup()

    async def test_public_cannot_complete_and_wrong_group_denied(self):
        ticket = await (await self.client.post("/launcher/v1/challenge", json={})).json()
        payload = dict(app_id="app", group_openid="official-group", member_openid="official-member",
                       code=ticket["code"], event_id="evt")
        self.assertEqual(401, (await self.client.post("/launcher/v1/complete", json=payload)).status)
        self.assertEqual(401, (await self.client.post("/launcher/v1/complete", json=payload,
                         headers={"Authorization": "Bearer " + "p" * 40})).status)
        headers = {"Authorization": "Bearer " + self.cfg["bot_token"]}
        payload["group_openid"] = "wrong-group"
        self.assertEqual(403, (await self.client.post("/launcher/v1/complete", json=payload, headers=headers)).status)
        payload["group_openid"] = "official-group"
        self.assertTrue((await (await self.client.post("/launcher/v1/complete", json=payload, headers=headers)).json())["accepted"])
        result = await (await self.client.post("/launcher/v1/status", json=ticket)).json()
        self.assertEqual(("authorized", "123456789", "official-member"),
                         (result["state"], result["group"], result["member"]))
        self.assertEqual(401, (await self.client.post("/v1/bind", json={})).status)

    async def test_poll_requires_secret_and_limits_challenge_creation(self):
        ticket = await (await self.client.post("/launcher/v1/challenge", json={})).json()
        self.assertEqual(401, (await self.client.post("/launcher/v1/status", json={"code": ticket["code"], "secret": "x" * 40})).status)
        for _ in range(11):
            self.assertEqual(200, (await self.client.post("/launcher/v1/challenge", json={})).status)
        self.assertEqual(429, (await self.client.post("/launcher/v1/challenge", json={})).status)

    async def test_bot_uses_event_identity(self):
        bot = SimpleNamespace(settings=self.cfg, call_service=AsyncMock(return_value={"accepted": True}))
        message = SimpleNamespace(content="<@!bot> /引导验证 AABBCCDDEEFF", group_openid="official-group",
                                  author=SimpleNamespace(member_openid="trusted-member"), id="evt")
        self.assertIn("验证通过", await reply(bot, message))
        self.assertEqual("trusted-member", bot.call_service.call_args.args[1]["member_openid"])
        message.group_openid = "untrusted"
        bot.call_service.reset_mock()
        await reply(bot, message)
        bot.call_service.assert_not_called()

    async def test_receipt_only_signed_for_trusted_group_event(self):
        bot = SimpleNamespace(settings=self.cfg, call_service=AsyncMock())
        message = SimpleNamespace(content='/引导验证 ' + 'AB' * 16, group_openid='official-group',
                                  author=SimpleNamespace(member_openid='trusted-member'), id='evt')
        with patch('mcqq.launcher.sign_receipt', return_value='SG1.payload.signature') as sign:
            self.assertIn('SG1.payload.signature', await reply(bot, message))
            sign.assert_called_once_with(self.cfg, 'AB' * 16, 'trusted-member', '123456789')
        message.group_openid = 'other-group'
        with patch('mcqq.launcher.sign_receipt') as sign:
            await reply(bot, message)
            sign.assert_not_called()
        message.group_openid = 'official-group'
        message.author.member_openid = ''
        with patch('mcqq.launcher.sign_receipt') as sign:
            await reply(bot, message)
            sign.assert_not_called()


if __name__ == "__main__":
    unittest.main()
