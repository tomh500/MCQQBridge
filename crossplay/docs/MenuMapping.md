# MasterGAL 界面映射与验收

BungeeMaster-GAL 用 Floodgate 确认当前代理连接能接收基岩表单，SpigotMaster-GAL 在后端维护该连接的表单状态。FabricMaster-GAL 用能力协商接收业务插件显式打开的 Screen。

| 交互 | Java（含 Fabric） | 基岩 |
| --- | --- | --- |
| 导航、列表、互斥选择，且每项都有可复用的服务端入口 | 已有容器保持原生。新业务可显式提供 Fabric Screen | 优先用 Floodgate 表单。表单不可用时保留现有库存或命令 |
| 真实容器、拖拽、Shift 快移、交换、数量和装备槽操作，以及依赖左右键区别的菜单 | 原生库存 | 由 Geyser 翻译原生库存 |
| 只读信息、装饰纹理和本地动画 | 按可用能力渲染 | 可用短文本、通用图标或省略动效。导航、成本、权限和状态仍应可辨 |

决策、目标配置、货币、价格、库存、权限和选择状态由后端插件维护。表单或 Screen 只返回当前界面的按钮序号。绑定当前连接、界面编号和可选项，在游戏线程重新解析并校验后再调用插件原有业务入口。玩家主动关闭即取消。代理未确认能力、发出失败或插件接口未知时，让原入口继续处理。待处理期间换世界、离开后端或打开其他库存会取消旧回调。

## 已审计入口

| 入口 | 处理方式 | 审计依据 |
| --- | --- | --- |
| BedWars1058 21.11.2 普通商品商人 | 基岩获得分类、快捷购买和原版商店入口。选择商品后重新检查当前对局、队伍、玩家状态、商店缓存和位置，再调用 `CategoryContent.execute`。每次选择只执行一次购买，继续购买可再次打开商店 | 本地 `bedwars-plugin-21.11.2-spigot112.jar` 的 `ShopOpenListener`、`ShopOpenEvent`、`CategoryContent`，以及 `shop.yml` |
| BedWars1058 编辑快捷购买、队伍升级、普通箱子及玩家库存 | 保留原生库存。升级入口有独立监听器，快捷购买编辑依赖槽位语义 | BedWars 的 `QuickBuyListener`、`upgrades.listeners.InventoryListener`，以及 `upgrades2.yml` |
| BedWars 大厅的模式、选图及重新加入 | 保留现有入口。独立的导航表单可在以后使用插件提供的玩家入口 | DeluxeMenus 的 `play-solo.yml` 调用玩家命令 `bw join Solo`、`bw gui Solo`、`rejoin`。设置菜单另外包含开放条件和控制台命令 |
| BW 大厅快捷栏箱子与 `/gmenu main` | GadgetsMenu 4.5.4 主菜单对基岩显示表单，对 Java 保留库存。按钮通过插件自己的主菜单处理器打开对应分类，表单内可返回原版主菜单 | BedWars1058 的 `lobby-items.gadgets-menu` 在快捷栏第 4 格配置 `CHEST`，执行 `gmenu main`。适配器识别 GadgetsMenu 的 `MainMenu.openMainMenu` 调用 |
| GadgetsMenu 分类、购买、神秘箱 | 保留插件库存，包含点击、装备、交易和确认 | GadgetsMenu 各分类监听器和 Mystery Dust 配置。DeluxeMenus 的 `gadgets.yml` 另走 `ma gui`、`bwws open` 等玩家命令 |
| ChestCommands 4.0.5 大厅导航 | 可按文件开启基岩表单。已审计示例 `lobby.yml` 的 `/menu`、`/lobbymenu`、`/cd` 提供换服、返回出生点和关闭。适配器只接受插件自己的菜单 holder，每次校验同一菜单仍已加载且拥有打开权限，再调用原图标 `onClick` | 本地 ChestCommands JAR 的 `MenuInventoryHolder`、`InternalMenu`、`MenuManager`、`InventoryListener` 和 `Icon`。插件的库存监听器额外维护点击节流 |
| 未审计 ChestCommands 菜单、脚本式菜单或依赖点击手势的插件菜单 | 保留插件原生界面 | 按具体业务入口审核 Open Actions、权限、花费、刷新和点击语义后，再决定是否加入 |

ChestCommands 表单由 `plugins/MasterGALMenus/config.yml` 的 `chestcommands-form-menus` 控制，初始列表为空。审核配置确认只含一次点击可执行的导航后，填写含扩展名的文件名，例如 `chestcommands-form-menus: [lobby.yml]`。含交易、频率限制、动态 Open Actions 或库存手势时应使用原生入口。列表修改后重启加载适配器。基岩表单每页保留“打开原版菜单”。

GadgetsMenu 的 `gadgetsmenu-main-form` 默认开启，缺省配置也沿用此行为。在需要用原生主菜单的后端，可以将该项设为 `false` 后重启适配器。普通箱子和各分类菜单继续由 Geyser 翻译。

## 本地与真机验证

1. 用 JDK 25 构建代理、Spigot、菜单 JAR，以及 Fabric 的 26.2 和 26.3 双目标。检查产物内的 `fabric.mod.json` 对应 Minecraft、Loader 和 Fabric API 模块。依赖见 [Fabric 版本表](FabricMaster-GAL.md)。
2. 通过测试代理，在 Java 原版与两种 Fabric 目标上打开大厅菜单、普通商品商店、编辑快捷购买、队伍升级和 GadgetsMenu。核对库存点击、快移和退出，与安装适配器前结果一致。用 `/crossplayevent`、`/mastergalclient` 和 `/crossplayprobe` 验证 Fabric 通道及换服后的重新协商。
3. 用基岩触屏和手柄测试 `/mastergalform`、ChestCommands 的翻页与返回原版菜单，以及 BedWars 单次购买、资源不足、背包已满和死亡后迟到的按钮。从 BW 大厅第 4 格箱子打开 GadgetsMenu 表单，测试分类库存、表单关闭和原版回退，并核对真实箱子和队伍升级。
4. 在菜单打开时切换后端、换世界、打开其他库存，或由管理员撤销 ChestCommands 开放权限并重载配置。确认旧按钮没有副作用。分别核对主动关闭、断开和派发失败时的表现。
5. 用最小 UI 缩放空间和高 GUI 缩放验证业务插件显式打开的 Fabric Screen，并检查键盘、鼠标、关闭和换服。26.3 的 SDL3 输入能力按具体客户端 API 适配。

服务端产物与依赖版本来自本地检出和本地 JAR。隔离的 Spigot 1.12.2 已用 Java 协议客户端验证 ChestCommands 原生库存打开和图标动作。另用 BedWars1058 21.11.2 和 GadgetsMenu 4.5.4 在隔离服右键实际发放的大厅箱子，验证 Java 原生打开，以及注入表单能力后的主菜单映射、原生分类、普通箱子、原版回退和关闭。隔离 BungeeCord 和两个 Spigot 后端也用 Java 1.12.2 协议客户端验证了请求往返、换服重置和重新协商。基岩 26.65 的真实连接仍待在支持 NetherNet 的测试环境验收。 [Geyser NetherNet 配置](https://geysermc.org/wiki/geyser/setup/)
