import re

HELP = """【MC 入服与双端共通】
/服务器 或 /在线 —— 查看各服人数与状态快照
只玩 Java：/绑定Java 游戏名
只玩基岩：/绑定基岩 Xbox昵称
两端共用 Java 存档：先绑定Java，再 /关联基岩 Xbox昵称，按提示在 Java 游戏内验证。
★ 两端名字相同也需要关联验证，名字相同不代表同一个账号。

【管理自己的账号】
/我的绑定 —— 查看主账号、基岩关联与下一步
/换绑Java 新名字 或 /换绑基岩 新Xbox昵称 —— 更换主账号，旧账号失去入服资格；不会搬运存档
/解除关联 —— 仅移除基岩关联，Java 主号保留
/解绑 —— 退出白名单，保留游戏存档
/设置头衔 文字 —— 设置自己的群服头衔，最多10个字符
/清除头衔 —— 清除自己的群服头衔
/发命令 子服 /指令 参数 —— 以绑定玩家身份执行；proxy 仅限在线
/大发命令 子服 /指令 参数 —— 以 Console 身份执行，仅 Bot 主人或管理
/设bot管理 @成员、/取缔bot管理 @成员 —— 仅 Bot 主人
/状态情报 —— 查看机器系统、运行时长和内存占用
/今日老婆 —— 每天抽取一位角色，首次可换一次；再查维持相同结果
/今日老婆 重置 —— 主人清除今天所有人的抽取与换取次数
/历史讯息向量化 —— 整理最近群聊并保存记忆，仅 Bot 主人或管理
/跨群信息 —— 查询可用群和ID；/跨群信息 [群名] 内容 或 /跨群信息 ALL 内容
设置/清除共用冷却：普通群员1小时；群主、管理员30秒。

每条命令前请 @机器人。名字中有空格可原样填写。"""

COMMANDS = (
    ("设置头衔", "自定义头衔最多10字"),
    ("清除头衔", "清除自己的群服头衔"),
    ("历史讯息向量化", "管理整理群聊记忆"),
    ("绑定Java", "Java玩家入服"),
    ("绑定基岩", "基岩玩家入服"),
    ("关联基岩", "双端共用Java存档"),
    ("我的绑定", "查看账号与下一步"),
    ("换绑Java", "更换Java主账号"),
    ("换绑基岩", "更换基岩主账号"),
    ("解绑", "退出白名单"),
    ("解除关联", "仅解除基岩关联"),
    ("帮助", "查看完整使用步骤"),
    ("本群ID", "获取群授权标识"),
    ("跨群信息", "向其他授权群发送消息"),
    ("发命令", "以绑定玩家身份执行游戏指令"),
    ("大发命令", "以控制台身份执行指定服指令"),
    ("设bot管理", "主人添加Bot管理"),
    ("取缔bot管理", "主人移除Bot管理"),
    ("状态情报", "查看机器系统运行和内存"),
    ("今日老婆", "每日抽一位，可换一次"),
)


def parse(text):
    text = re.sub(r"^<@!?[^>]+>\s*", "", text or "").strip().lstrip("/")
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
    if command in ("设bot管理", "取缔bot管理"):
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
        match = re.fullmatch(r"\[([^\]]+)\]\s+([\s\S]+)", argument)
        if match:
            target, content = match.group(1).strip(), match.group(2)
        else:
            pieces = argument.split(maxsplit=1)
            if len(pieces) != 2:
                raise ValueError("格式：/跨群信息 [群名/别名] 内容；或 /跨群信息 ALL 内容")
            target, content = pieces
        if not target or not content.strip():
            raise ValueError("格式：/跨群信息 [群名/别名] 内容；或 /跨群信息 ALL 内容")
        return "cross_group", target, content
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
