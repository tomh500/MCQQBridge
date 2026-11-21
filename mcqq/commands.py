import re

HELP = """【SMP 入服与账户】
/SMP账号 绑定 Java 游戏名 或 /绑定Java 游戏名
/SMP账号 绑定 基岩 Xbox昵称 或 /绑定基岩 Xbox昵称
/SMP账号 关联 Xbox昵称 或 /关联基岩 Xbox昵称
双端共用存档时先绑定 Java，再申请关联，最后在 Java 游戏内按提示验证。
/SMP账号 查询 或 /我的绑定 —— 查看入服资格、主账号与关联状态
/SMP账号 换绑 Java|基岩 名字 或 /换绑Java 游戏名、/换绑基岩 Xbox昵称 —— 更换主账号与入服资格，存档保留在原账号
/SMP账号 解除关联 或 /解除关联 —— 移除基岩关联，保留 Java 主账号
/SMP账号 解绑 或 /解绑 —— 退出白名单，保留游戏存档
解绑和解除关联会先显示影响，确认后在命令末尾加「确认」。

【头衔与服务器】
/SMP头衔 设置 文字 或 /设置头衔 文字 —— 设置头衔，最多 10 个字符
/SMP头衔 清除 或 /清除头衔 —— 恢复默认身份标签
设置和清除共用冷却时间，普通群员 1 小时，群主和管理员 30 秒。
/服状态 在线 或 /在线、/服务器 —— 查看各服在线人数
/服状态 系统 或 /状态情报 —— 查看服务器系统、运行时长与内存
/群服互通 —— 查看 QQ 与游戏的互通方式

【群情报与跨群】
/群讯息情报统计 或 /群情报 今日 —— 绘制今日聊天星图与话题，仅 Bot 主人或管理
/群友情报 @群友 或 /群情报 成员 @群友 —— 生成聊天画像
/群友情报 重置 或 /群情报 重置 —— 重置本群群友情报名额，仅 Bot 主人或管理
/历史讯息向量化 —— 整理本群历史聊天并保存记忆，仅 Bot 主人或管理
/跨群信息 —— 查询目标群和 ID
/跨群信息 群别名 内容 —— 定向发送。使用 ALL 或省略目标时发往其他授权群
引用回复 Bot 转发的跨群消息，可直接发回原来源群。
/跨群信息 临时全量模式 一群,二群 —— 自动转发你的消息 2 小时。用英文逗号分隔群别名或 ID，省略范围即 ALL。再次执行会更新范围和两小时有效期。
/跨群信息 结束全量模式 —— 立即停止自动转发

【游戏指令与 Bot 管理】
/发命令 子服 /指令 参数 —— 以绑定玩家身份执行，proxy 仅限在线玩家
/大发命令 服务器名 /指令 参数 —— 手动输入，以控制台身份执行
Bot 管理可指定一个已授权的子服。Bot 主人也可用 proxy（总代）或 ALL。
/设bot管理 @成员 —— 添加 Bot 管理，仅 Bot 主人
/取消bot管理 @成员 或 /取缔bot管理 @成员 —— 移除 Bot 管理，仅 Bot 主人

【今日老婆】
/今日老婆 —— 抽取或查看今日角色。/换老婆 可换一次
/今日老婆 许愿 角色名 —— 首次抽取前许愿，花费 16 积分并消耗当天交换机会
/今日老婆 积分点 查询 —— 查看自己的积分
/今日老婆 重置 —— 清除本日抽取与交换记录，仅 Bot 主人

发送 /SMP账号、/SMP头衔、/群情报 或 /服状态 可查看该组的用法。Xbox 昵称中的空格可原样填写。"""

COMMANDS = (
    ("SMP头衔", "设置或清除自己的群服头衔"),
    ("群讯息情报统计", "今日群聊星图与话题"),
    ("群友情报", "指定群友生成聊天画像"),
    ("SMP账号", "入服绑定、双端关联、换绑查询"),
    ("帮助", "查看完整命令和用法"),
    ("跨群信息", "跨群转发及临时全量模式"),
    ("发命令", "以绑定玩家身份执行游戏指令"),
    ("状态情报", "查看机器系统、时长和内存"),
    ("今日老婆", "每日抽一位，可换一次"),
)

COMMAND_GROUPS = {
    "SMP账号": ({
        "绑定": ("绑定", True), "换绑": ("换绑", True), "关联": ("关联基岩", True),
        "查询": ("我的绑定", False), "解绑": ("解绑", None), "解除关联": ("解除关联", None),
    }, """【SMP 账号】
/SMP账号 绑定 Java 游戏名
/SMP账号 绑定 基岩 Xbox昵称
/SMP账号 关联 Xbox昵称 —— 让基岩端共用已绑定的 Java 存档
/SMP账号 查询 —— 查看主账号与关联状态
/SMP账号 换绑 Java|基岩 新名字 —— 更换对应版本的主账号
/SMP账号 解绑 [确认] —— 退出白名单
/SMP账号 解除关联 [确认] —— 只移除基岩关联"""),
    "SMP头衔": ({
        "设置": ("设置头衔", True), "清除": ("清除头衔", False),
    }, "/SMP头衔 设置 文字（最多10字）\n/SMP头衔 清除"),
    "服状态": ({
        "在线": ("在线", False), "系统": ("状态情报", False),
    }, "/服状态 在线\n/服状态 系统"),
    "群情报": ({
        "今日": ("群讯息情报统计", False), "成员": ("群友情报", True),
        "重置": ("群友情报 重置", False),
    }, "/群情报 今日\n/群情报 成员 @群友\n/群情报 重置（管理）"),
}


def expand_command_group(text):
    """Resolve the panel syntax to existing commands and keep their authorization paths."""
    parts = text.split(maxsplit=2)
    if not parts or parts[0].removeprefix("/") not in COMMAND_GROUPS:
        return text
    actions, usage = COMMAND_GROUPS[parts[0].removeprefix("/")]
    action = actions.get(parts[1]) if len(parts) >= 2 else None
    argument = parts[2] if len(parts) == 3 else ""
    if action is None:
        raise ValueError(usage)
    command, needs_argument = action
    if needs_argument is not None and needs_argument != bool(argument):
        raise ValueError(usage)
    return f"/{command} {argument}" if argument else f"/{command}"


def parse(text):
    text = expand_command_group(re.sub(r"^<@!?[^>]+>\s*", "", text or "").strip()).lstrip("/")
    parts = text.split(maxsplit=2)
    if not parts or parts[0] in ("帮助", "help"):
        return "help", None, None
    command = parts[0]
    if command == "今日老婆":
        argument = text[len(command):].strip()
        if argument == "重置":
            return "daily_waifu_reset", None, None
        if argument:
            raise ValueError("格式：/今日老婆 或 /今日老婆 重置")
        return "daily_waifu", None, None
    if command in ("设bot管理", "取缔bot管理", "取消bot管理"):
        argument = text[len(command):].strip()
        if not argument:
            raise ValueError(f"格式：/{command} @成员")
        return ("admin_add" if command == "设bot管理" else "admin_remove"), None, argument
    if command == "状态情报":
        if text[len(command):].strip():
            raise ValueError("格式：/状态情报")
        return "system_info", None, None
    if command in ("发命令", "大发命令"):
        argument = text[len(command):].strip().split(maxsplit=1)
        if len(argument) != 2 or not argument[1].strip():
            raise ValueError(f"格式：/{command} lobby|survival|proxy|ALL /指令 参数")
        if argument[0].startswith("/"):
            raise ValueError(f"请先指定目标：/{command} lobby|survival|proxy|ALL /指令 参数")
        target = {"总代": "proxy", "all": "ALL"}.get(argument[0].lower(), argument[0].lower())
        content = argument[1] if argument[1].startswith("/") else "/" + argument[1]
        return ("console_command" if command == "大发命令" else "game_command"), target, content
    if command == "跨群信息":
        argument = text[len(command):].strip()
        if not argument:
            return "cross_group_list", None, None
        target, *body = argument.split(maxsplit=1)
        if target == "临时全量模式":
            return "cross_group_mode_start", body[0] if body else "ALL", None
        if target == "结束全量模式":
            if body:
                raise ValueError("用法：/跨群信息 结束全量模式")
            return "cross_group_mode_stop", None, None
        match = re.fullmatch(r"\[([^\]]+)\]\s+([\s\S]+)", argument)
        if match:
            target, content = match.group(1).strip(), match.group(2)
            if not target:
                raise ValueError("格式：/跨群信息 [群名/别名] 内容")
            return "cross_group", target, content
        if argument.startswith("["):
            raise ValueError("格式：/跨群信息 [群名/别名] 内容")
        if body and target.upper() == "ALL":
            return "cross_group", target, body[0]
        if body and re.fullmatch(r"[0-9a-f]{32}", target, re.IGNORECASE):
            return "cross_group", target, body[0]
        # Only the bot knows whether the first word names a configured target.
        return "cross_group_implicit", target if body else None, argument
    if command in ("服务器", "在线"):
        if len(parts) != 1:
            raise ValueError("格式：/服务器 或 /在线；不接受附加参数。")
        return "server_status", None, None
    if command == "设置头衔":
        title = text[len(command):].strip()
        if not title:
            raise ValueError("格式：/设置头衔 你的头衔（最多10个字符）")
        return "title_set", None, title
    if command == "清除头衔":
        if text[len(command):].strip():
            raise ValueError("格式：/清除头衔；只能清除自己的头衔。")
        return "title_clear", None, ""
    if command == "群服互通":
        return "chat", None, None
    if command == "本群ID":
        return "group", None, None
    if command == "我的绑定":
        return "query", None, None
    if command in ("解绑", "解除关联"):
        argument = text[len(command):].strip()
        if argument not in ("", "确认"):
            raise ValueError(f"请先发送 /{command} 查看影响，再发送 /{command} 确认。")
        return ("unbind" if command == "解绑" else "unlink"), None, argument
    if command == "关联基岩":
        name = text[len(command):].strip()
        if not name:
            raise ValueError("【双端共通】请填写 Xbox 昵称。\n格式：/关联基岩 Xbox昵称\n例如：/关联基岩 tombh500\n已有 Java 主账号会保留；接下来需在 Java 游戏内验证。")
        return "link", "bedrock", name
    for prefix, action, platform in (("绑定Java", "bind", "java"), ("绑定基岩", "bind", "bedrock"),
                                      ("换绑Java", "rebind", "java"), ("换绑基岩", "rebind", "bedrock")):
        if command.lower() == prefix.lower():
            name = text[len(command):].strip()
            if not name:
                raise ValueError(f"【缺少游戏名字】\n格式：/{prefix} 游戏名\n例如：/{prefix} tombh500")
            return action, platform, name
    if command not in ("绑定", "换绑"):
        return "help", None, None
    if len(parts) != 3 or not parts[2].strip():
        candidate = text[len(command):].strip() or "你的游戏名"
        if command == "换绑":
            raise ValueError(f"【更换主账号】你还没有选择游戏版本。\nJava：/换绑Java {candidate}\n基岩：/换绑基岩 {candidate}\n★ 只想让两端共用现有存档？请使用 /关联基岩 Xbox昵称。")
        raise ValueError(f"【选择你玩的版本】\nJava：/绑定Java {candidate}\n基岩：/绑定基岩 {candidate}\n★ 两端都玩：先绑定Java，再 /关联基岩 Xbox昵称。")
    platform = {"java": "java", "je": "java", "基岩": "bedrock", "bedrock": "bedrock", "be": "bedrock"}.get(parts[1].lower())
    if not platform:
        raise ValueError("【版本未识别】请使用 /绑定Java 游戏名 或 /绑定基岩 Xbox昵称；输入 /帮助 查看全部步骤。")
    return "bind" if command == "绑定" else "rebind", platform, parts[2].strip()
