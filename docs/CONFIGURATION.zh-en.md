# 配置说明 / Configuration guide

每个字段的双语说明见配置模板本身。/ Bilingual field descriptions are included in each template.

| 文件 / File | 使用者 / Consumer | 生效方式 / Apply |
|---|---|---|
| `settings.json` | Python 机器人和 API / Bot + API | 重启两个服务 / Restart both services |
| `plugins/MCQQBridge/config.yml` | BungeeCord 代理 / Proxy | 控制台 `mcqq reload`；更换JAR需重启 / Reload config; restart for JAR changes |
| `plugins/MCQQSpigot/config.yml` | 每个子服 / Each backend | 重启对应子服 / Restart that backend |

JSON 没有原生注释，`_comments` 对象提供逐字段中文和英文说明，不参与业务逻辑。真实配置值在 `_comments` 外面；不要在 JSON 中写 `#` 或 `//`。YAML 则使用 `#` 注释和空格缩进。/ JSON has no native comments; `_comments` documents each field and is ignored by runtime logic. Edit actual settings outside that object. YAML uses `#` comments and space indentation.

## MySQL

先创建数据库和授权账号，然后配置子服：/ Create the database and account first, then configure the backend:

```yaml
storage:
  type: sql
  sql:
    url: 'jdbc:mysql://127.0.0.1:3306/YOUR_DATABASE?useUnicode=true&characterEncoding=UTF-8&connectTimeout=5000&socketTimeout=5000'
    username: '' # 填你的账号 / Your database account
    password: '' # 填你的密码 / Your database password
    table: mcqq_settings
```

数据库名位于URL中，表名由 `table` 指定，插件只会自动创建表。已有同名表必须具有 `setting_key`、`setting_value` 两列；不要复用其他插件的表。/ Database name is in the URL, table name is configured separately. The plugin creates only the table. Existing tables must have the expected two columns; never reuse another plugin's table.

Spigot Storage API 的 MySQL 数据、机器人 SQLite 绑定/队列、代理 YAML 聊天偏好是三个独立的数据源。本配置不会把绑定、队列或偏好自动搬到 MySQL。切换后端前先备份，旧 YAML/SQLite 文件不会自动导入。/ Spigot MySQL storage, bot SQLite bindings/queues and proxy YAML preferences are independent; changing this backend does not migrate other data or import old files.

群路由使用官方 `group_openid`，不是数字群号。机器人允许群列表和入站群列表负责授权；群名和别名只负责显示。/ Routes use official group_openids, not numeric group numbers. Allowed/inbound lists control authorization; names and aliases control display only.

公开模板的凭据全部为空。实际运行配置保存在用户空间，禁止提交到 Git。/ Public templates contain no credentials; keep actual configuration outside version control.

## 存储故障与聊天 / Storage failures and chat

存储初始化失败会记录错误，插件仍注册 `/said` 和群命令。不会静默改用其他数据库；扩展调用 `storage()` 时会明确收到 unavailable 错误，避免数据写入错误后端。MySQL 驱动单独打包到插件命名空间，避开 Spigot 1.12 内置旧驱动。/ Storage initialization failures keep chat commands registered. No silent backend fallback occurs; extensions calling storage() receive an explicit unavailable error. MySQL classes are relocated to avoid legacy Spigot driver collisions.
