<h1 align="center">ChatGPT2API</h1>


<p align="center">ChatGPT2API 主要是对 ChatGPT 官网相关能力进行逆向整理与封装，提供面向 ChatGPT 图片生成、图片编辑、多图组图编辑场景的 OpenAI 兼容图片 API / 代理，并集成在线画图、号池管理、多种账号导入方式与 Docker 自托管部署能力。</p>

> [!WARNING]
> 免责声明：
>
> 本项目涉及对 ChatGPT 官网文本生成、图片生成与图片编辑等相关接口的逆向研究，仅供个人学习、技术研究与非商业性技术交流使用。
>
> - 严禁将本项目用于任何商业用途、盈利性使用、批量操作、自动化滥用或规模化调用。
> - 严禁将本项目用于破坏市场秩序、恶意竞争、套利倒卖、二次售卖相关服务，以及任何违反 OpenAI 服务条款或当地法律法规的行为。
> - 严禁将本项目用于生成、传播或协助生成违法、暴力、色情、未成年人相关内容，或用于诈骗、欺诈、骚扰等非法或不当用途。
> - 使用者应自行承担全部风险，包括但不限于账号被限制、临时封禁或永久封禁以及因违规使用等所导致的法律责任。
> - 使用本项目即视为你已充分理解并同意本免责声明全部内容；如因滥用、违规或违法使用造成任何后果，均由使用者自行承担。
> - 本项目基于对 ChatGPT 官网相关能力的逆向研究实现，存在账号受限、临时封禁或永久封禁的风险。请勿使用你自己的重要账号、常用账号或高价值账号进行测试。


## 赞助商

<table>
  <tr>
    <td width="190" align="center">
      <a href="https://www.atlascloud.ai/zh?utm_source=github&utm_medium=link&utm_campaign=chatgpt2api"><img src="assets/atlascloud.svg" width="163" alt="Atlas Cloud"></a>
    </td>
    <td>
      <a href="https://www.atlascloud.ai/zh?utm_source=github&utm_medium=link&utm_campaign=chatgpt2api">Atlas Cloud</a> is a full-modal AI inference platform that gives developers a single AI API to access video generation, image generation, and LLM APIs. Instead of managing multiple vendor integrations, you connect once and get unified access to 300+ curated models across all modalities. Check out <a href="https://www.atlascloud.ai/console/coding-plan">Atlas Cloud's new coding plan promotion</a> for more budget-friendly API access.
    </td>
  </tr>
</table>

## 快速开始

### Docker 运行

```bash
git clone https://github.com/pcg562240/chatgpt2api.git
cd chatgpt2api
cp .env.example .env
# 编辑 .env，设置你自己的 CHATGPT2API_AUTH_KEY，再启动
docker compose up -d --build
```

启动前在 `.env` 中设置 `CHATGPT2API_AUTH_KEY`，不要把密钥或账号 Token 提交到 Git。
默认监听 `0.0.0.0:8030`，允许局域网访问；仅本机使用可设置 `CHATGPT2API_BIND_HOST=127.0.0.1`。

- Web 面板：`http://localhost:8030`
- API 地址：`http://localhost:8030/v1`
- 数据目录：`./data`

### WARP / FlareSolverr 稳定代理部署

如果图片链路经常遇到 Cloudflare 拦截，可以启用附带的 WARP + Privoxy + FlareSolverr 方案：

```bash
cp .env.example .env
docker compose -f docker-compose.warp.yml up -d --build
```

该 compose 会启动：

- `warp-proxy`：提供 WARP SOCKS5 出口。
- `privoxy`：把 WARP SOCKS5 转成 HTTP 代理。
- `flaresolverr`：刷新 Cloudflare clearance。
- `init-config`：幂等写入 `proxy_runtime` 默认配置。
- `app`：启动 ChatGPT2API 主服务。

默认只让上游 OpenAI / ChatGPT 请求走稳定代理，账号邮箱、CPA 等辅助链路不会被强制接管。账号自身配置的代理优先级最高，其次是稳定代理运行时，再其次是显式代理和旧版全局代理。

可在 `.env` 中调整端口和代理运行时参数，也可在后台设置页的「稳定代理运行时」面板手动保存、测试代理和测试 clearance。

### 本地开发

启动后端：

```bash
git clone https://github.com/pcg562240/chatgpt2api.git
cd chatgpt2api
uv sync
uv run main.py
```

启动前端：

```bash
cd chatgpt2api/web
bun install
bun run dev
```

本 fork 更新代码后重新构建（不要拉取原作者镜像代替本 fork）：

```bash
git pull --ff-only
docker compose up -d --build
```

### 存储后端配置

支持通过环境变量 `STORAGE_BACKEND` 切换存储方式：

- `json` - 本地 JSON 文件（默认）
- `sqlite` - 本地 SQLite 数据库
- `postgres` - 外部 PostgreSQL（需配置 `DATABASE_URL`）
- `git` - Git 私有仓库（需配置 `GIT_REPO_URL` 和 `GIT_TOKEN`）

示例：使用 PostgreSQL

```yaml
environment:
  - STORAGE_BACKEND=postgres
  - DATABASE_URL=postgresql://user:password@host:5432/dbname
```

## 功能

### API 兼容能力

- 兼容 `POST /v1/images/generations` 图片生成接口
- 兼容 `POST /v1/images/edits` 图片编辑接口
- 兼容面向图片场景的 `POST /v1/chat/completions`
- 兼容面向图片场景的 `POST /v1/responses`
- `GET /v1/models` 动态返回账号目录、已发现模型的 `web-image/` 生图候选入口和兼容别名
- 支持通过 `n` 返回多张生成结果
- 支持生成可编辑 PPT 文件
- 支持生成可编辑 PSD 文件
- 支持 Codex 中的画图接口逆向，仅 `Plus` / `Team` / `Pro` 订阅可用，模型别名为 `codex-gpt-image-2`，如有需要可自行在其他场景映射回
  `gpt-image-2`，用于和官网画图区分；也就意味着同一账号会同时有官网和 Codex 两份生图额度

### 在线画图功能

- 内置在线画图工作台，支持生成、图片编辑与多图组图编辑
- 支持 `gpt-image-2`、`codex-gpt-image-2`、`auto`、`gpt-5`、`gpt-5-1`、`gpt-5-2`、`gpt-5-3`、`gpt-5-3-mini`、`gpt-5-mini` 模型选择
- 编辑模式支持参考图上传
- 前端支持多图生成交互
- 本地保存图片会话历史，支持回看、删除和清空
- 支持服务端缓存图片URL
- 图片生成进度追踪，超时后可继续等待
- 图片懒加载与滚动位置记忆，优化大量图片场景性能

### 号池管理功能

- 自动刷新账号邮箱、类型、额度和恢复时间（异步进度追踪）
- 轮询可用账号执行图片生成与图片编辑
- 遇到 Token 失效类错误时自动剔除无效 Token
- 定时检查限流账号并自动刷新
- 支持密码重新登录恢复异常账号，刷新后可自动重登
- 支持网页端配置全局 HTTP / HTTPS / SOCKS5 / SOCKS5H 代理
- 支持 WARP / FlareSolverr 稳定代理运行时
- 支持搜索、筛选、批量刷新、导出、手动编辑和清理账号
- 支持四种导入方式：本地 CPA JSON 文件导入、远程 CPA 服务器导入、`sub2api` 服务器导入、`access_token` 导入
- 支持在设置页配置 `sub2api` 服务器，筛选并批量导入其中的 OpenAI OAuth 账号

### 实验性 / 规划中

- 详细状态说明见：[功能清单](./docs/feature-status.en.md)

## 效果展示

<table width="100%">
  <tr>
    <td width="50%"><img src="https://i.ibb.co/Jj8nfwwP/image.png" alt="image" border="0"></td>
    <td width="50%"><img src="https://i.ibb.co/pqf235v/image-edit.png" alt="image edit" border="0"></td>
  </tr>
  <tr>
    <td width="50%"><img src="https://i.ibb.co/tPcqtVfd/chery-studio.png" alt="chery studio" border="0"></td>
    <td width="50%"><img src="https://i.ibb.co/PsT9YHBV/account-pool.png" alt="account pool" border="0"></td>
  </tr>
  <tr>
    <td width="50%"><img src="https://i.ibb.co/rRWLG08q/new-api.png" alt="new api" border="0"></td>
  </tr>
</table>

## 账号模型发现（本 fork）

1. 在号池导入网页账号，然后打开 **设置 → 模型发现**，选择当前账号，点击 **刷新当前账号模型**。
2. 成功后显示上游真实返回的模型 ID、刷新时间和可选生图候选入口；刷新失败或返回空目录时保留最近成功结果。
3. 选择 **全局默认生图模型** 并保存；生图页面的“图像设置 → 模型”也可选择模型或点击刷新。
   新对话采用全局默认模型，已有对话继承最后一次提交的模型；API 省略 `model` 时也采用全局默认值。
4. `GET /v1/models` 动态暴露模型，无需为每个新版本修改白名单。
   普通聊天使用上游 ID；生图使用 `web-image/<上游ID>`，服务端移除前缀后原样传递。
   例如上游返回 `new-model-id` 时，图片接口使用 `web-image/new-model-id`。
   这样同一个模型的聊天与图片请求不会互相混淆。
5. 模型按**具体账号**路由，不将同套餐的其他账号当成必然具有同样权限。
   缓存保存在 `data/model_catalog.json`，只保存不透明账号标识、模型元数据和时间，不保存账号凭据。
   禁用/删除账号后其目录不再参与路由；缓存可跨服务重启保留。
6. 内置 `gpt-image-2.5-flare` 与 `gpt-image-2.5-sunburst`，可以直接在模型下拉框选择，
   或作为图片 API 的 `model` 使用；两个 ID 原样传给上游，不映射到旧模型。
   网页目录未列出不代表不可调用，但内置也不保证每个账号都具有权限。
7. **设置 → 模型发现** 和 **生图页 → 图像设置** 均提供 **自定义上游模型 ID → 添加并选择**。
   输入准确 ID（例如 `future-image-model`，不是显示名称），保存后使用 `web-image/future-image-model` 调用图片 API。
   输入已有的 `web-image/` 前缀也会正确处理，模型大小写及后缀原样保留。
   自定义项跨刷新、跨重启保留，可在设置页删除；添加本身不执行生图，也不改变全局默认。
   要默认使用，另外点击 **保存默认模型**。先切换默认模型，才能删除正在作为默认值的自定义项。

**路由区别：**目录发现项只分配给宣告该模型的账号；内置 Flare / Sunburst 及管理员手动添加项
允许向可用的网页账号池发起请求，不以目录缺失作为拒绝依据，不使用匿名或 Codex 账号。
这不会将手动模型伪装成上游已发现的文本模型，也不会在调用失败时自动换成其他模型。
最多保存 100 个自定义 ID；格式限制为 1–128 个英文字符/数字/`._:/-`，首字符为英文或数字，拒绝空值、网址、`auto` 和嵌套前缀。

管理接口（仍需 Bearer 密钥；刷新/改默认/增删自定义模型仅管理员）：

- `GET /api/model-catalog?account_id=...`：读取账号目录及可选账号，不发起生成。
- `POST /api/model-catalog/refresh`，JSON `{"account_id":"目录返回的账号ID"}`：强制刷新所选账号。
- `POST /api/model-catalog/default`，JSON `{"model":"web-image/new-model-id"}`：保存默认生图模型。
- `POST /api/model-catalog/custom`，JSON `{"model":"future-image-model"}`：保存手动模型，返回 `registered_model` 供图片接口使用。
- `DELETE /api/model-catalog/custom`，JSON `{"model":"future-image-model"}`：删除手动项；如果目录仍宣告此 ID，其发现入口仍会保留。

**边界：**“上游目录已发现”不等于“已验证可生图”。网页目录通常也含文本模型，因此生图入口明确标为候选。
刷新不会消耗生图额度来逐个验证；实际权限、额度和图像能力以上游调用结果为准。
只要上游模型目录和调用协议保持兼容，新增模型可以刷新即用；认证、接口协议或工具参数改变时仍需要适配代码。
原生生成尺寸与速度不因模型发现功能得到保证；下述输出尺寸修复继续保留。

## API

### 图片输出尺寸和张数（本地修复）

- `size` 支持 `WIDTHxHEIGHT`（每边 1–4096 像素），例如 `512x512`、`768x768`。
  省略 `size` 或使用 `auto` 时保留上游原始图片，不做缩放。
- 官网图片链路的尺寸参数只是提示词，不是强制的原生生成分辨率。
  显式指定尺寸时，本服务在输出层使用 LANCZOS 重采样；宽高比不同则居中留边，
  不拉伸、不裁掉画面。小尺寸输出**不代表**上游原生小尺寸生成，也不保证生图更快。
- Base64 和图片 URL 使用同一份处理后的图片字节；流式、非流式、编辑和任务续轮询
  都遵循同一尺寸规则。响应图片条目包含 `original_size`、`size`、`resized` 和
  `size_processing`，明确区分 `upstream` 与 `server_resize_pad`。
- 每个生图工作任务最多返回一张图片；API 的 `n` 决定任务数，防止上游多图或重复
  结果导致返回张数超过 `n`。多任务部分失败时仍保留原有的部分成功行为。
- 非法尺寸在获取账号前返回 HTTP 400（`invalid_size`），不消耗生图额度。

所有 AI 接口都需要请求头：

```http
Authorization: Bearer <auth-key>
```

<details>
<summary><code>GET /v1/models</code></summary>
<br>

返回当前暴露的图片模型列表。

```bash
curl http://localhost:8000/v1/models \
  -H "Authorization: Bearer <auth-key>"
```

<details>
<summary>说明</summary>
<br>

| 字段   | 说明                                                                                                         |
|:-----|:-----------------------------------------------------------------------------------------------------------|
| 返回模型 | `gpt-image-2`、`codex-gpt-image-2`、`auto`、`gpt-5`、`gpt-5-1`、`gpt-5-2`、`gpt-5-3`、`gpt-5-3-mini`、`gpt-5-mini` |
| 接入场景 | 可接入 Cherry Studio、New API 等上游或客户端                                                                          |

<br>
</details>
</details>

<details>
<summary><code>POST /v1/images/generations</code></summary>
<br>

OpenAI 兼容图片生成接口，用于文生图。

```bash
curl http://localhost:8000/v1/images/generations \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <auth-key>" \
  -d '{
    "model": "gpt-image-2",
    "prompt": "一只漂浮在太空里的猫",
    "n": 1,
    "response_format": "b64_json"
  }'
```

<details>
<summary>字段说明</summary>
<br>

| 字段                | 说明                                                 |
|:------------------|:---------------------------------------------------|
| `model`           | 图片模型，当前可用值以 `/v1/models` 返回结果为准，推荐使用 `gpt-image-2` |
| `prompt`          | 图片生成提示词                                            |
| `n`               | 生成数量，当前后端限制为 `1-4`                                 |
| `response_format` | 当前请求模型中包含该字段，默认值为 `b64_json`                       |

<br>
</details>
</details>

<details>
<summary><code>POST /v1/images/edits</code></summary>
<br>

OpenAI 兼容图片编辑接口，可上传图片文件，也可按官方 JSON 格式传入图片链接并生成编辑结果。

```bash
curl http://localhost:8000/v1/images/edits \
  -H "Authorization: Bearer <auth-key>" \
  -F "model=gpt-image-2" \
  -F "prompt=把这张图改成赛博朋克夜景风格" \
  -F "n=1" \
  -F "image=@./input.png"
```

也可以直接传图片 URL：

```bash
curl http://localhost:8000/v1/images/edits \
  -H "Authorization: Bearer <auth-key>" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-image-2",
    "prompt": "把这张图改成赛博朋克夜景风格",
    "images": [
      {"image_url": "https://example.com/input.png"}
    ]
  }'
```

<details>
<summary>字段说明</summary>
<br>

| 字段          | 说明                                            |
|:------------|:----------------------------------------------|
| `model`     | 图片模型， `gpt-image-2`                           |
| `prompt`    | 图片编辑提示词                                       |
| `n`         | 生成数量，当前后端限制为 `1-4`                            |
| `image`     | 需要编辑的图片文件，使用 multipart/form-data 上传           |
| `images`    | JSON 图片引用数组，支持 `{"image_url": "https://..."}` |
| `image_url` | 表单模式下也可直接传图片链接，支持重复字段传多张图                     |

<br>
</details>
</details>

<details>
<summary><code>POST /v1/chat/completions</code></summary>
<br>

面向文本、网页搜索与图片场景的 Chat Completions 兼容接口，不是完整通用聊天代理。

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <auth-key>" \
  -d '{
    "model": "gpt-image-2",
    "messages": [
      {
        "role": "user",
        "content": "生成一张雨夜东京街头的赛博朋克猫"
      }
    ],
    "n": 1
  }'
```

<details>
<summary>字段说明</summary>
<br>

| 字段                   | 说明                                                                           |
|:---------------------|:-----------------------------------------------------------------------------|
| `model`              | 文本、搜索或图片模型；搜索模型会触发网页搜索兼容逻辑                                                   |
| `messages`           | 消息数组，支持文本、搜索和图片请求内容                                                          |
| `n`                  | 图片生成数量，按当前实现解析为图片数量                                                          |
| `stream`             | 文本、搜索和图片场景均支持，仍在测试                                                           |
| `tools`              | 文本场景支持 `web_search` / `web_search_preview` / `web_search_preview_2025_03_11` |
| `web_search_options` | 传入时会触发网页搜索兼容逻辑                                                               |

<br>
</details>
</details>

<details>
<summary><code>POST /v1/responses</code></summary>
<br>

面向文本、网页搜索和图片生成工具调用的 Responses API 兼容接口，不是完整通用 Responses API 代理。

```bash
curl http://localhost:8000/v1/responses \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <auth-key>" \
  -d '{
    "model": "gpt-5",
    "input": "生成一张未来感城市天际线图片",
    "tools": [
      {
        "type": "image_generation"
      }
    ]
  }'
```

<details>
<summary>字段说明</summary>
<br>

| 字段       | 说明                                                                                      |
|:---------|:----------------------------------------------------------------------------------------|
| `model`  | 响应中会回显该模型字段，搜索和图片生成会走对应兼容逻辑                                                             |
| `input`  | 输入内容；搜索使用最后一条用户文本，图片生成需能解析出提示词                                                          |
| `tools`  | 支持 `image_generation`、`web_search`、`web_search_preview`、`web_search_preview_2025_03_11` |
| `stream` | 已实现，但仍在测试                                                                               |

<br>
</details>
</details>

## 社区支持

学 AI , 上 L 站：[LinuxDO](https://linux.do)

## Contributors

感谢所有为本项目做出贡献的开发者：

<a href="https://github.com/basketikun/chatgpt2api/graphs/contributors">
  <img alt="Contributors" src="https://contrib.rocks/image?repo=basketikun/chatgpt2api" />
</a>

## Star History

[![Star History Chart](https://api.star-history.com/chart?repos=basketikun/chatgpt2api&type=date&legend=top-left)](https://www.star-history.com/?repos=basketikun%2Fchatgpt2api&type=date&legend=top-left)
