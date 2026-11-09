# 按群设置聊天互通

配置文件属于 Python 机器人服务，在服务器上是 `/home/ubuntu/qqbot-mc/settings.json`。请不要把它或其中的凭据提交到公开仓库。

1. 在各 QQ 群里向机器人发送 `/本群ID`，记下返回的 `group_openid`。使用这个值，不要填写数字群号。
2. SSH 登录服务器后，先备份配置：

   ```sh
   cp -p ~/qqbot-mc/settings.json ~/qqbot-mc/settings.json.before-group-routing
   nano ~/qqbot-mc/settings.json
   ```

3. 找到原有的 `allowed_groups` 和 `chat_bridge`，编辑这几项，保留文件中其他原有字段：

   ```json
   "allowed_groups": ["GROUP_A", "GROUP_B"],
   "chat_bridge": {
     "servers": ["lobby", "survival", "bw"],
     "inbound_groups": ["GROUP_A"],
     "outbound_groups": ["GROUP_B"],
     "group_aliases": {"GROUP_A": "朋友群", "GROUP_B": "公告群"}
   }
   ```

   例子中 A 的群消息可以进入游戏，B 接收游戏消息；A 不接收游戏消息，B 的群消息不进入游戏。两个名单均可包含同一个群，也可以是空数组 `[]`。所有名单成员必须先在 `allowed_groups` 中。省略任一方向字段时，该方向兼容旧版，使用全部授权群。定向群命令也受 `outbound_groups` 约束。`servers` 应保留你现有的实际子服配置。
4. nano 中按 Ctrl+O、回车保存，再按 Ctrl+X 退出。检查 JSON 格式，然后重启并逐个确认服务：

   ```sh
   python3 -m json.tool ~/qqbot-mc/settings.json >/dev/null && echo 'JSON 格式正确'
   systemctl --user restart mcqq-api
   systemctl --user start mcqq-bot
   systemctl --user is-active mcqq-api
   systemctl --user is-active mcqq-bot
   ```

5. 在各群及游戏中发送测试消息，分别检查两种方向。游戏到群的主动消息仍需 QQ 机器人具备相应权限和额度。

如果启动失败，可用备份还原并重新启动两个服务：

```sh
cp -p ~/qqbot-mc/settings.json.before-group-routing ~/qqbot-mc/settings.json
systemctl --user restart mcqq-api
systemctl --user start mcqq-bot
```
