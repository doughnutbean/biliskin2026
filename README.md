# 🎨 B站装扮抢购工具

> 自动抢购哔哩哔哩限量装扮的命令行工具，支持定时抢购和监控补货。

## 📦 安装

```bash
# 1. 克隆项目
git clone https://github.com/doughnutbean/biliskin2026.git
cd biliskin

# 2. 安装依赖
pip install -r requirements.txt

# 3. 扫码登录需要额外依赖（可选）
pip install qrcode[pillow]
```

## 📦 打包为 EXE

项目自带 `biliskin.spec`，使用 PyInstaller 一键打包：

```bash
pip install pyinstaller
python -m PyInstaller biliskin.spec --clean --noconfirm
```

产物在 `dist/biliskin-gui/` 目录，双击 `biliskin-gui.exe` 启动。

**打包特性：** 无命令行窗口 · 启动 < 1 秒（onedir 免解压）· 排除了 GUI 不用的模块减小体积

如需自定义图标，修改 `biliskin.spec` 中 `EXE(...)` 的 `icon="icon.ico"` 即可。

---

## 🚀 快速开始

### 1️⃣ 登录

**方式一：Cookie登录（推荐）**

从浏览器获取B站 Cookie（F12 → 网络 → 任意请求 → 请求头 → Cookie），然后：

```bash
python main.py login cookie "SESSDATA=xxx; bili_jct=xxx; DedeUserID=xxx"
```

**方式二：扫码登录**

```bash
pip install qrcode[pillow]  # 需要先安装
python main.py login qrcode
```

**方式三：一键登录（⭐推荐）**

自动从浏览器提取 Cookie，失败则弹窗扫码：

```bash
python main.py login quick
```

GUI 版直接点击「🔑 一键登录」按钮即可。

**方式四：查看登录状态**

```bash
python main.py login status
```

### 2️⃣ 查找装扮

```bash
# 搜索装扮
python main.py search "初音未来"

# 查看在售装扮列表
python main.py list

# 查看装扮详情（获取商品ID、开售时间、价格等）
python main.py info 12345

# 查询库存
python main.py stock 12345
```

### 3️⃣ 抢购

**定时抢购模式**（适用于已知开售时间的限量装扮）：

```bash
python main.py grab -i 12345 -t "2025-01-01 20:00:00" -c 8
```

参数说明：
- `-i` / `--item-id`：装扮商品ID
- `-t` / `--time`：开售时间，格式 `YYYY-MM-DD HH:MM:SS`
- `-c` / `--concurrent`：并发工作数（默认8）
- `-a` / `--advance`：提前发起请求秒数（默认0.5秒）
- `-r` / `--retries`：最大重试次数（默认20）
- `-f` / `--force`：跳过确认

**监控补货模式**（持续监控库存，有货自动抢）：

```bash
python main.py grab -i 12345 --mode watch -c 8
```

**数字卡片抢购**（DLC 抽奖类活动）：

```bash
python main.py dlc --act-id 113353 --lottery-id 113354 -t "2026-06-28 17:00:00"
```

**从活动链接一键导入**（自动解析商品ID和参数）：

```bash
# 查看链接解析结果
python main.py url "https://www.bilibili.com/blackboard/activity-xxx.html?type=dlc&id=113353&lottery_id=113354"

# 直接启动抢购（自动填入参数）
python main.py dlc --url "https://www.bilibili.com/blackboard/activity-xxx.html?type=dlc&id=113353&lottery_id=113354" -t "17:00:00"
```

GUI 版在参数配置栏底部粘贴链接 → 点「导入」即可自动填充。

### 4️⃣ 配置管理

```bash
# 查看当前配置
python main.py config --show

# 设置默认配置项
python main.py config --set item_id=12345
python main.py config --set concurrent=8
python main.py config --set advance=0.5
```

### 5️⃣ 一键抢购示例

```bash
# 完整流程
python main.py login cookie "SESSDATA=xxx; bili_jct=xxx; DedeUserID=xxx"
python main.py config --set item_id=12345
python main.py config --set sale_time="2025-01-01 20:00:00"
python main.py grab -f
```

## 📖 命令参考

| 命令 | 说明 | 示例 |
|------|------|------|
| `login cookie` | Cookie登录 | `python main.py login cookie "SESSDATA=xxx"` |
| `login qrcode` | 扫码登录 | `python main.py login qrcode` |
| `login quick` | 一键登录 | `python main.py login quick` |
| `login browser` | 浏览器提取Cookie | `python main.py login browser` |
| `login status` | 查看登录状态 | `python main.py login status` |
| `info <id>` | 查询装扮详情 | `python main.py info 12345` |
| `search <keyword>` | 搜索装扮 | `python main.py search "初音"` |
| `list` | 在售列表 | `python main.py list --page 1` |
| `stock <id>` | 查询库存 | `python main.py stock 12345` |
| `grab` | 执行抢购 | `python main.py grab -i 12345 -t "20:00:00"` |
| `dlc` | 数字卡片抢购 | `python main.py dlc --url "LINK" -t "17:00:00"` |
| `url <link>` | 解析活动链接 | `python main.py url "https://..."` |
| `config --show` | 查看配置 | `python main.py config --show` |
| `config --set` | 设置配置 | `python main.py config --set num=2` |
| `account` | 账户信息 | `python main.py account` |

## ⚙️ 配置文件

`config.json` 支持以下配置项：

```json
{
  "grab": {
    "item_id": "12345",           // 装扮商品ID
    "num": 1,                     // 购买数量
    "mode": "once",               // 抢购模式: once | watch
    "retry_interval": 0.5,        // 重试间隔（秒）
    "max_retries": 20,            // 最大重试次数
    "sale_time": "",              // 开售时间
    "advance_seconds": 0.5,       // 提前发起请求秒数
    "concurrent_workers": 8       // 并发工作数
  },
  "proxy": {
    "enabled": false,
    "http": "",
    "https": ""
  }
}
```

## 🔧 技术架构

```
biliskin/
├── main.py          # 主入口，CLI命令行界面
├── gui.py           # 图形界面（tkinter）
├── config.py        # 配置管理（JSON读写）
├── api.py           # B站API封装（登录、装扮、订单接口）
├── login.py         # 登录管理器（Cookie/扫码/一键登录）
├── graber.py        # 抢购引擎（定时触发/异步并发/重试）
├── grab_dlc.py      # 数字卡片抢购扩展
├── url_parser.py    # 活动链接解析器
├── biliskin.spec    # PyInstaller 打包配置
├── config.json      # 用户配置文件
├── cookies.json     # Cookie持久化存储
└── requirements.txt # Python依赖
```

### 核心特性

- **毫秒级触发**：忙等待实现精确到微秒的定时触发
- **异步并发**：基于 `asyncio` + `httpx` 的并发下单
- **一键登录**：自动从浏览器提取 Cookie，失败降级扫码
- **扫码登录**：GUI 端显示二维码图片，App 扫码即登
- **链接导入**：粘贴活动 URL 自动填充商品ID和参数
- **监控模式**：持续检测库存，有货立即抢购
- **图形界面**：基于 tkinter 的可视化操作

## ⚠️ 注意事项

1. **请务必先登录**：所有抢购操作需要有效的登录态
2. **Cookie时效**：B站Cookie有有效期，过期需要重新获取
3. **请遵守规则**：合理使用，不要对B站服务器造成过大压力
4. **限量装扮**：部分装扮为极少量发售，即使工具也不能保证100%抢到
5. **网络延迟**：可以考虑使用离B站服务器较近的网络环境

## 📝 License

MIT
