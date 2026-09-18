# 专辑包装 MVP 实施计划

目标：在现有 Minuet 中增加封面搜索、预览、生成、状态、画廊和下载闭环。沿用 Python 标准库 HTTP 服务、Pillow、numpy、requests 和原生网页。

设计：新增 /packaging 页面及独立模块，入口加入原工作台。复用现有封面来源和 read_design 的色板、明暗、风格提取。任务和来源记录保存在 outputs/专辑包装。生成正面、封底、侧脊、CD、内页、海报、明信片和总览；所有产物标注个人设计概念，不伪造厂牌、版权授权、歌词或曲目。

用户已要求直接实施，并选择本地 ComfyUI。两种模式明确分开：本地排版可直接运行；AI 模式上传参考封面、提交图片工作流、查询 history、下载画面，再套入包装排版。API 路由依据 https://docs.comfy.org/development/comfyui-server/comms_routes 。现有 ComfyUI 只有 H3 视频模型，AI 实际推理验证受图片工作流缺失限制，不能宣称成功。

- [x] 新增 packaging_sources.py：网易云专辑/歌手搜索；服务端候选 ID；图片大小、格式和来源域名验证；上传作为搜索失败的替代入口。
- [x] 新增 packaging_comfy.py：本地地址配置、连接和模型预检、原生 img2img 工作流及可配置 API 工作流、排队/失败/超时处理；不打断其他 ComfyUI 任务。
- [x] 新增 packaging_render.py 和 packaging_service.py：七种部件与总览、来源说明、原子持久化、重启后中断标记、单任务互斥、历史恢复、单图/ZIP 下载。
- [x] 新增 packaging.html：搜索、封面选择/上传、色板、模式说明、生成按钮、阶段状态、画廊、历史任务；接入 server.py 与原首页入口。
- [x] 使用 unittest 验证来源校验、Comfy 契约和错误状态、任务持久化与下载边界；运行真实封面搜索和本地出图；浏览器验证主流程及窄屏。

不覆盖当前 tools/design_parts.py、tools/fetch163.py、tools/make_minicd_board.py、tools/typo.py 的已有修改。不自动下载大模型，不把本地排版结果声称为 AI 创作；尺寸仅为概念图像素尺寸，不承诺可直接印刷。

验收：12 项 unittest 通过；真实歌手搜索44张；范特西7部件+总览生成，ZIP 11文件完整；浏览器1280与390宽度无溢出，无控制台错误，刷新与独立服务启动恢复成功。AI真实推理受图片模型缺失限制；接口成功/错误已用模拟响应验证。最新本地预览端口8766。

