# Minuet · 音乐卡片工坊

把一张专辑封面，变成可以直接印刷或上架的商品图。

给一张封面图，它能产出四种成品：**播放界面卡片**（30×50mm 实物尺寸）、**钥匙扣商品图**（1920×1920 场景图）、**白底商品图**（纯白/透明底电商图，可拼版）、**黑胶播放界面**（1:2 竖图）。

输入歌手名，还能一次抓出该歌手的**全部专辑**，产出**专辑卡**（方形版式）与**专辑墙**（全部封面拼版总览）。

![钥匙扣成品示例](assets/demo/keychain.jpg)

> 上图由本仓库代码生成（`tools/make_demo_assets.py`），使用程序绘制的抽象封面，不含任何第三方素材。

**白底商品图**（电商商品图形态，纯白底 + 钥匙扣当主角，可拼版）：

![白底商品图示例](assets/demo/shop-grid.jpg)

---

## 功能一览

| 功能 | 说明 | 脚本 |
|---|---|---|
| 播放界面 | 复刻音乐 App 深色播放页，**1181×1968 @1000DPI = 30×50mm** 实物比例 | `tools/make_player.py` |
| 钥匙扣商品图 | **1920×1920** 五层合成：模糊底图 → 白卡纸 → 清晰封面 → 播放界面 → 钥匙扣贴片 | `tools/make_keychain.py` |
| 白底商品图 | 纯白底 / 透明底，钥匙扣放大当主角；画布预设可配置（淘宝 / 天猫 / 拼多多 / 抖店 / 亚马逊 / Etsy…），可拼版总览 | `tools/make_keychain_shop.py` |
| 黑胶播放界面 | **1:2 竖图**（默认 1200×2400）：深色底 + 圆黑胶唱片 + 唱臂 + 控制区，中心圆形封面；宽度可选 900/1200/1500 | `tools/make_vinyl.py` |
| 专辑全集 | 给歌手名，抓**全部专辑**（含单曲 / EP / Live / Remix），出方形**专辑卡** + **专辑墙**总览 + 封面母版原图 | `tools/make_album.py` |
| **迷你CD 打印拼版** | 做**实体迷你唱片机**：把专辑排成 A4 300dpi 拼版（盘面 Ø40 / 封面折件 82×41 / 封底条 **111.2×38** = 右封4.4+封底49+左封4.4+背脊4.4+内盘底49），带裁切线 + 50mm 校验尺。**只有封面也能跑** —— 缺的部件由**封面衍生设计引擎**自动生成，并自动联网取**真实曲目列表**印到封底 | `tools/make_minicd.py` |
| 封面衍生设计引擎 | 从一张封面提色板 + 推断 mood/style（minimalist / retro / bold），长出配套的盘面（CD 沟槽 + 扇形高光）、内页、封底（曲目 + 条码）、内盘底、书脊 | `tools/design_parts.py` |
| 批量套装 | 按歌手抓取热门歌曲，一次产出一整套 + 总览图 | `tools/make_set.py` |
| 网页工作台 | 本地可视化界面，勾选即出图，支持打包 ZIP 下载 | `workbench/server.py` |

播放界面的每个元素（导航、封面、标签、歌名、进度条、控制按钮）都是**程序化绘制**的，
不依赖字体图标，也不依赖任何截图底图，因此分辨率可以任意缩放。

### 新增：AI 迷你CD 设计工作台（v1.10.0）

在首页「专辑全集」里搜索歌手 → 专辑列表**勾选一张或多张** → 点「设计这张专辑」或
「设计选中的 N 张」，或访问 `http://127.0.0.1:8765/design`。

固定包装结构（尺寸真源 `tools/spec_minicd.py`，合成与打印共用同一份常量）：

| 件 | 规格 |
|---|---|
| ① 盘面 | Ø40mm，中心孔 Ø5mm |
| ② 封面折件 | 展开 82×41mm（沿中缝对折成 41×41） |
| ③ 盒体展开 | **111.2×38mm** = 右封 4.4 + 封底 49 + 左封 4.4 + 背脊 4.4 + 内盘底 49 |

- 三件套**全部由封面衍生**：读封面色板/明暗/边密度 → 推断 mood + style → 按同一设计语言
  分别构图（不是同一张图换裁切）。内容分工：封面背面无条码；封底 = 曲目 + 真 EAN-13 条码
  + 厂牌版权行；内盘底 = 取下 CD 后的隐藏主视觉。
- **AI 可选增强**：三件各有上传槽位，上传即用该图覆盖对应件；未上传的仍走程序衍生，保证成套。
- 产出：三张部件 PNG + **1:1 印刷版面总览**（①②③ + 尺寸标注 + 折线 + 裁切十字 + 50mm 校验尺）
  + **A4 300dpi 拼版 PNG/PDF** + ZIP。批量模式另出**多专辑对照图**（每格自带文字标注）。
- 打印请在打印设置里选「**实际大小 / 100%**」：默认的「适合页面」会把 40mm 缩成 38mm。
  打完先量页脚的 50mm 校验尺再裁。
- 落盘 `outputs/迷你CD设计/<任务编号>/`（任务编号走 ASCII 白名单校验）。

---

## 环境要求

- **Python 3.9+**
- 依赖：`Pillow`、`numpy`、`requests`
- **一款中文字体**（否则标题会显示成方块，见下方「配置」）

支持 Windows / macOS / Linux。

## 安装

```bash
git clone <本仓库地址>
cd <仓库目录>

# 创建虚拟环境（推荐）
python -m venv .venv

# Windows
.venv\Scripts\pip install -r requirements.txt

# macOS / Linux
.venv/bin/pip install -r requirements.txt
```

## 快速开始

### 方式一：网页工作台（推荐）

```bash
# Windows：双击
启动工作台.bat

# macOS / Linux
./start.sh
```

浏览器会自动打开 `http://127.0.0.1:8765`。输入歌手名 → 选歌 → 勾选「同时出钥匙扣商品图」/「同时出白底商品图」/「同时出黑胶播放界面」→ 开始生成。
产物会落到 `outputs/工作台/<任务id>/`。

工作台顶部有四个模式页签：**热门歌曲**、**歌手单曲**、**上传封面**、**专辑全集**。
前三个是「按歌出图」，第四个是「按专辑出图」：

- 切到 **专辑全集** 页签，填入歌手名 → 点「查询专辑」先看清单（张数 / 发行日期 / 曲目数，只查不下载）→
  确认无误后开始生成。会把该歌手的**全部专辑**（含单曲 / EP / 演唱会 Live / Remix）一次抓下来，
  每张产出**封面母版原图**（方形，最大 2000×2000）+ **专辑卡**，最后拼一张**专辑墙**总览。
- 专辑卡可选边长 **1200 / 1500 / 2000**；「最多抓几张」填 `0` 表示**全部**（周杰伦实测 44 张）。
- 打包 ZIP 里除图片外还带一份 `albums.json`，**可离线重出**（不用再联网抓一遍）。
- 专辑模式只走网易云（QQ 音乐没有公开的专辑列表接口）。

三个产出开关的区别（热门 / 单曲 / 上传模式）：

- **钥匙扣商品图**（`keychain/`）—— *场景图*。1920×1920，封面模糊铺满当背景 + 白卡纸相框，钥匙扣缩在中间当点缀，像一张「效果图」。
- **白底商品图**（`shop/`）—— *商品图*。没有背景大图，纯白底或透明底，钥匙扣放大当主角，并附拼版总览。
  可选「透明底 PNG」，直接贴到任意底色或电商详情页上。
  画布可以**多选**（竖长 / 方形 / 淘宝 800×800 / 天猫 800×1200 / 拼多多 750×1000 /
  抖店 1080×1080 / 亚马逊 1000×1000 / Etsy 2000×2000 …）。
  预设清单在 [`config/canvas_presets.json`](config/canvas_presets.json)，**可自由增删改**，
  改完重启工作台即生效，不用动代码。
  > 注意：这里改的是外面那层商品图画布。卡面（`players/*.png`）必须保持 1:1.667，
  > 那是卡套内腔的比例，动了就嵌不进去。
- **黑胶播放界面**（`vinyl/`）—— 1:2 **竖图**（高 = 2×宽，默认 1200×2400）：
  深色底 + 圆黑胶唱片 + 唱臂 + 控制区，中心是圆形封面。可选宽度 **900 / 1200 / 1500**，
  并附一张 `总览-黑胶.jpg` 拼版。

### 方式二：命令行

```bash
cd tools

# 1) 单张播放界面
python make_player.py --cover 封面.jpg --title 歌名 --artist 歌手 \
                      --duration 257 --played 0.35 --width 1181 --ratio 1.6667 \
                      --out player.png

# 2) 单张钥匙扣商品图（场景图）
python make_keychain.py --cover 封面.jpg --player player.png --out keychain.png

# 3) 单张白底商品图
python make_keychain_shop.py --cover 封面.jpg --player player.png --out shop.png

# 4) 单张黑胶播放界面（1:2 竖图）
python make_vinyl.py --cover 封面.jpg --title 歌名 --artist 歌手 \
                     --duration 257 --played 0.10 --width 1200 --out vinyl.png

# 5) 按歌手出「专辑全集」（全部专辑 → 封面母版 + 专辑卡 + 专辑墙）
python make_album.py 周杰伦 --out ../outputs/周杰伦-专辑全集              # 全部 44 张
python make_album.py 周杰伦 --out ../outputs/周杰伦-专辑前10 --limit 10  # 只出最新的 10 张
python make_album.py 周杰伦 --out ../outputs/周杰伦-专辑卡 --no-wall --card-size 1200  # 只要卡，不要墙

# 从已抓好的任务目录离线重出（读 albums.json，不再联网）
python make_album.py --batch ../outputs/工作台/<任务id>

# 6) 按歌手批量出一整套热门歌曲
python make_set.py 周杰伦 --top 5 --out ../outputs/周杰伦-热门前5
python make_keychain.py --batch ../outputs/周杰伦-热门前5          # 场景图
python make_keychain_shop.py --batch ../outputs/周杰伦-热门前5     # 商品图

# 只出竖长白底、不要拼版
python make_keychain_shop.py --batch ../outputs/周杰伦-热门前5 \
        --canvas long --bg white --no-grid

# 一次出多种画布（逗号分隔），比如竖长 + 淘宝主图
python make_keychain_shop.py --batch ../outputs/周杰伦-热门前5 \
        --canvas long,taobao

# 看看有哪些画布预设可选
python make_keychain_shop.py --list-canvas

# 7) 迷你CD 打印拼版（做实体迷你唱片机）
#    只给一张封面就行 —— 盘面/内页/封底/内盘底全部由封面衍生设计出来，
#    曲目列表自动联网反查（拿不到就留空，不报错）
python make_minicd.py --cover 封面.jpg --artist 周杰伦 --album 范特西 \
       --out ../outputs/范特西-迷你CD --preview

# 全套素材齐全时（用文件名关键词自动识别部件）
python make_minicd.py --dir ../outputs/范特西-迷你CD素材 \
       --artist 周杰伦 --album 范特西 --out ../outputs/范特西-迷你CD --preview

# 批量：读 albums.json，为全部专辑各出一套（周杰伦 44 张实测全成功）
python make_minicd.py --batch ../outputs/周杰伦-专辑全集/albums.json \
       --artist 周杰伦 --out ../outputs/周杰伦-迷你CD全集

# 手动给曲目 / 离线加速 / 覆盖设计语言
python make_minicd.py --cover a.jpg --album X --tracks "曲目1;曲目2;曲目3"
python make_minicd.py --cover a.jpg --album X --no-tracks
python make_minicd.py --cover a.jpg --album X --style retro --mood dreamy

# 出对照图（① 封面 → ② 盘面 → ③ 折件 → ④ 封底条，自带文字标注）
python make_minicd_compare.py
```

**打印提示**：拼版左下角有一根 **50mm 校验尺**。家庭打印默认「缩放到可打印区域」
会把 40mm 打成 38mm（差 1mm 就装不进盒）—— 打出来拿尺子量那根线，
不足 50mm 就在打印设置里关掉缩放，或用 `--scale 1.02` 补偿。

不带任何素材参数直接运行 `make_keychain.py`，会用仓库自带的抽象占位图出一张演示图。

---

## 目录结构

```
.
├── tools/                     命令行脚本
│   ├── fetch163.py            网易云：搜索、封面、歌曲信息
│   ├── fetch_qq.py            QQ 音乐：搜索、封面、热门歌曲
│   ├── make_player.py         播放界面卡片
│   ├── make_vinyl.py          黑胶播放界面（1:2 竖图）
│   ├── make_album.py          专辑全集（全部专辑 → 封面母版 + 专辑卡 + 专辑墙）
│   ├── make_minicd.py         迷你CD 打印拼版（A4 300dpi，实体迷你唱片机）
│   ├── design_parts.py        封面衍生设计引擎（一张封面长出全套盒面部件）
│   ├── make_minicd_compare.py 迷你CD 对照图（① 封面 → ② 盘面 → ③ 折件 → ④ 封底条）
│   ├── fetch_parts.py         部件图网络搜索（备选路线：易被限流 / 结果污染）
│   ├── make_keychain.py       钥匙扣商品图（五层合成，场景图）
│   ├── make_keychain_shop.py  白底商品图（纯白/透明底，竖长/方形 + 拼版）
│   ├── keychain_build.py      贴片标定：从实拍素材反解 RGBA 叠加层
│   ├── make_set.py            批量套装 + 总览图
│   ├── make_demo_assets.py    生成仓库自带的抽象示例素材
│   ├── fonts.py               跨平台中文字体探测
│   ├── noproxy.py             绕过本机代理访问 127.0.0.1
│   ├── e2e_test.py            端到端验收：完整调用序列
│   ├── e2e_keychain.py        端到端验收：钥匙扣（17 项断言）
│   ├── e2e_shop.py            端到端验收：白底商品图
│   ├── e2e_vinyl.py           端到端验收：黑胶播放界面（19 项断言）
│   ├── e2e_album.py           端到端验收：专辑全集（38 项断言）
│   ├── e2e_design.py          端到端验收：封面衍生设计引擎（35 项断言）
│   └── start_bg.py            脱离会话后台启动工作台
├── workbench/                 网页工作台
│   ├── server.py              HTTP 后端（仅标准库，只绑 127.0.0.1）
│   └── index.html             单页前端
├── config/
│   └── canvas_presets.json    商品图画布预设（可自由增删改）
├── assets/
│   ├── keychain/
│   │   ├── keychain_overlay.png   钥匙扣 RGBA 叠加层（功能必需）
│   │   └── tone_curve.json        色调曲线标定数据（功能必需）
│   └── demo/                  抽象示例素材（无版权）
├── 启动工作台.bat              Windows 启动器
├── start.sh                   macOS / Linux 启动器
└── requirements.txt
```

---

## 配置

所有配置都通过**环境变量**完成，不需要改代码。

| 变量 | 默认值 | 说明 |
|---|---|---|
| `MINUET_PORT` | `8765` | 工作台端口 |
| `MINUET_FONT_BOLD` | 自动探测 | 粗体字体文件路径，如 `C:\Windows\Fonts\msyhbd.ttc` |
| `MINUET_FONT_REG` | 自动探测 | 常规字体文件路径 |
| `PLAYER_BG` | `l3` | 播放页背景配色。`l3` = 取封面主色并定标亮度；`legacy` = 旧的平均色方案 |

字体默认会自动探测：Windows 用微软雅黑，macOS 用苹方，Linux 用思源黑体 / Noto CJK / 文泉驿。
都找不到时会给出明确的安装提示。

```bash
# 例：指定字体并换端口
export MINUET_FONT_BOLD=/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc
export MINUET_PORT=9000
./start.sh
```

### 商品图画布预设

商品图（白底商品图）的画布预设住在 [`config/canvas_presets.json`](config/canvas_presets.json)，
界面上的画布按钮就是照它渲染的：

```json
"taobao": { "label": "淘宝主图 800×800", "tag": "淘宝", "w": 800, "h": 800, "pad": 0.070 }
```

| 字段 | 含义 |
|---|---|
| `label` | 界面上显示的名字（按钮上悬停可见） |
| `tag` | 写进文件名的中文简称，保持短 |
| `w` | 画布宽；填 `null` 表示按钥匙扣比例反算宽度（竖长画布用） |
| `h` | 画布高 |
| `pad` | 上下各留白占画布高的比例，钥匙扣高 = `1 - 2*pad` |

按 key 覆盖内置项，或直接加新项（例如 `"shopee": {...}`）。`_` 开头的键是注释，会被忽略。
改完**重启工作台**即生效；命令行可以用 `--list-canvas` 查当前预设。

> ⚠️ 这里改的只是外面那层商品图画布。卡面尺寸不受影响 —— 它必须是 1:1.667
> （卡套内腔的比例），改了会嵌不进去。

---

## 常见问题

**中文显示成方块**
系统没有中文字体。安装一款（Linux: `sudo apt install fonts-noto-cjk`），
或用 `MINUET_FONT_BOLD` / `MINUET_FONT_REG` 指定字体文件。

**浏览器打不开工作台**
本机代理软件可能把 `127.0.0.1` 也代理走了。把 localhost 加入代理白名单，
或临时关闭代理。诊断脚本：`python tools/diag_net.py`。

**提示缺少模块**
没装依赖。执行 `pip install -r requirements.txt`。

**改了配色不生效**
`workbench/server.py` 在**模块级**导入 `make_player`，常驻进程持有旧模块。
改完配置需要重启工作台。

---

## 数据来源与免责声明

⚠️ **请在使用前阅读**

- 本项目通过各音乐平台的**公开接口**获取歌曲信息与封面图片，用于个人学习与设计实践。
- **封面图片的版权归原平台及版权方所有**。本项目不存储、不分发任何音乐或封面资源。
- 生成的作品**仅供个人学习、研究和设计参考**，不得用于商业用途或任何侵犯版权的场景。
- 请遵守各音乐平台的用户协议与相关法律法规。因使用本项目产生的任何法律责任，由使用者自行承担。

如果你要用于商业产品，请使用你有合法授权的素材。

## 开源协议

[MIT](LICENSE)
