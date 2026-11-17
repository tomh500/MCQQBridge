"""Refresh an explicitly configured group's QQ command panel; safe to run from a timer."""
import asyncio
import os
from datetime import datetime

import aiohttp

from mcqq.config import load
from mcqq.feature_policy import FeaturePolicy, ZONE
from sync_commands import API, panel_config, read


def same_items(actual, wanted):
    keys = ('type', 'name', 'desc', 'only_admin')
    return [[item.get(key, False if key == 'only_admin' else None) for key in keys] for item in actual] == [
        [item.get(key, False if key == 'only_admin' else None) for key in keys] for item in wanted]


def group_panel(cfg, group, now=None):
    now = now or datetime.now(ZONE)
    panel = panel_config()
    panel['remark'] = 'mcqq-group-schedule-' + group
    verdict = FeaturePolicy(cfg, clock=lambda: now).check(group, 'entertainment', consume=False)
    if verdict['allowed']:
        description = '当前可用'
    else:
        following = verdict.get('next')
        description = '下次 ' + following.strftime('%m-%d %H:%M') if following else '暂不可用'
    for item in panel['items']:
        if item['name'] == '今日老婆':
            item['desc'] = description
    return panel


async def main():
    cfg = load()
    groups = cfg.get('scheduled_panel_groups', [])
    if os.environ.get('MCQQ_PANEL_GROUP'):
        groups = [os.environ['MCQQ_PANEL_GROUP']]
    if not groups or any(group not in cfg.get('allowed_groups', []) for group in groups):
        raise ValueError('scheduled_panel_groups must contain authorized group openids')
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
        async with session.post('https://bots.qq.com/app/getAppAccessToken', json={'appId': cfg['app_id'], 'clientSecret': cfg['app_secret']}) as response:
            token = (await read(response))['access_token']
        session.headers.update({'Authorization': 'QQBot ' + token, 'X-Union-Appid': cfg['app_id']})
        records, cursor = [], None
        while True:
            params = {'scope': 'group', 'limit': 50}
            if cursor:
                params['cursor'] = cursor
            async with session.get(API + '/v2/panels', params=params) as response:
                page = await read(response)
            records.extend(page.get('records', []))
            cursor = page.get('next_cursor')
            if page.get('is_end') or not cursor:
                break
        for group in groups:
            panel = group_panel(cfg, group)
            matches = [r for r in records if r.get('panel', {}).get('remark') == panel['remark']]
            if len(matches) > 1:
                raise RuntimeError('Duplicate managed group panels')
            if matches:
                panel_id = str(matches[0]['panel_id'])
                async with session.get(API + '/v2/panels/' + panel_id) as response:
                    current = await read(response)
                if current.get('target_type') != 'specific' or current.get('group_openids') != [group]:
                    raise RuntimeError('Managed panel target does not match configured group')
                if not same_items(current.get('panel', {}).get('items', []), panel['items']):
                    async with session.put(API + '/v2/panels/' + panel_id, json={'panel': panel}) as response:
                        await read(response)
            else:
                async with session.post(API + '/v2/panels', json={'scope': 'group', 'target_type': 'specific', 'group_openids': [group], 'panel': panel}) as response:
                    panel_id = str((await read(response))['panel_id'])
            async with session.get(API + '/v2/panels/' + panel_id) as response:
                actual = await read(response)
            if not same_items(actual.get('panel', {}).get('items', []), panel['items']):
                raise RuntimeError('QQ group panel readback mismatch')


if __name__ == '__main__':
    asyncio.run(main())
