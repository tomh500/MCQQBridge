import re

HELP = """【MC 入服与双端共通】
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
设置/清除共用冷却：普通群员1小时；群主、管理员30秒。

每条命令前请 @机器人。名字中有空格可原样填写。"""

COMMANDS = (
    ("设置头衔", "自定义头衔最多10字"),
    ("清除头衔", "清除自己的群服头衔"),
    ("群服互通", "查看互通范围与用法"),
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
)


def parse(text):
    text = re.sub(r"^<@!?[^>]+>\s*", "", text or "").strip().lstrip("/")
    parts = text.split(maxsplit=2)
    if not parts or parts[0] in ("帮助", "help"):
        return "help", None, None
    command = parts[0]
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
