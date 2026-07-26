# StockSense Hub 服务 API 契约 v1

> 状态：冻结候选
> 版本：v1.1
> 更新日期：2026-07-24
> 适用范围：StockSense Desktop、StockSense 远程 Hub 服务
> 远程工程：`/Users/penn/Projects/stocksense-admin`

## 1. 边界与命名

Hub 是 StockSense 官方维护的技能与应用分发中心。Desktop 只调用本地
Gateway；Gateway 负责访问远程 Hub、缓存目录、校验制品，并把 `.happ`
送入既有两阶段导入流程。第一阶段不支持远程 Gateway、第三方自助发布、
用户账号或服务端执行 Skill/App。

| 范围 | 冻结值 |
|---|---|
| 公开 Base URL | `https://<host>/app-api/hub/v1` |
| 管理 Base URL | `https://<host>/admin-api/hub` |
| Desktop 配置 | `hub.enabled`、`hub.base_url`、`hub.channel`、`hub.trusted_keys` |
| Python 客户端 | `HubClient`、`HubConfig`、`HubError` |
| 本地应用 API | `/api/apps/hub` |
| 安装平台 | `windows-x64`、`macos-arm64` |

公开接口返回裸 JSON 和标准 HTTP 状态码，不使用 `CommonResult`；管理接口
继续使用工程现有 `CommonResult<T>`、`PageResult<T>` 和 `pageNo/pageSize`。

服务端、客户端、配置和本地应用 API 统一使用 Hub 命名。

## 2. 公共协议

客户端发送 `Accept: application/json`、`X-StockSense-Client-Version`、
`X-StockSense-Runtime-Version`，列表/详情可附带 `If-None-Match`。
分类、列表与详情必须返回 `ETag`，命中后返回 `304`；推荐
`Cache-Control: public,max-age=300,stale-if-error=86400`。resolve 与下载
URL 不得缓存。

列表通用参数为 `q`、`category`、`page`、`page_size`、`channel`、
`compatible_only`；默认 `page=1`、`page_size=24`、`channel=stable`、
`compatible_only=true`，`page_size` 最大 50。

```json
{
  "items": [],
  "page": 1,
  "page_size": 24,
  "total": 0,
  "has_more": false,
  "generated_at": "2026-07-24T20:30:00+08:00"
}
```

公开端点：

| 方法 | 路径 |
|---|---|
| GET | `/categories?type=skill|app` |
| GET | `/skills`、`/skills/{id}` |
| POST | `/skills/{id}/resolve` |
| GET | `/apps`、`/apps/{id}` |
| POST | `/apps/{id}/resolve` |
| GET | `/artifacts/{artifact_id}/download?token=...` |

Skill 和 App 目录项包含 `id`、`name`、`summary`、`description`、
`category`、`version`、`channel`、`verified`、`featured`、`icon_url`、
`tags`、`compatibility`、`permissions`、`updated_at`。App `id` 必须等于
`.happ` Manifest `id`。首期发布方为官方固定展示信息，不建独立发布方资源。

resolve 请求：

```json
{"version":"1.2.0","channel":"stable","platform":"windows-x64"}
```

resolve 返回 `{item, artifact}`。Artifact 的 `kind` 为 `skill_bundle` 或
`happ`，并包含 `artifact_id`、`version`、`sha256`、`size_bytes`、
`download_url`、`expires_at` 和 `signature`。下载必须同源、HTTPS、无重定向，
开发环境仅允许 loopback HTTP，令牌建议十分钟有效，制品最大 50 MiB，并返回
准确 `Content-Length`。

## 3. 错误与信任根

错误为裸 JSON：

```json
{"error":{"code":"HUB_ITEM_NOT_FOUND","message":"未找到指定中心条目","retryable":false,"request_id":"req_01J...","details":{}}}
```

公开错误码使用 `HUB_` 前缀：`HUB_INVALID_REQUEST`、
`HUB_ITEM_NOT_FOUND`、`HUB_VERSION_INCOMPATIBLE`、`HUB_ARTIFACT_EXPIRED`、
`HUB_ARTIFACT_TOO_LARGE`、`HUB_ARTIFACT_REJECTED`、
`HUB_SIGNATURE_INVALID`、`HUB_RATE_LIMITED`、`HUB_DISABLED`、
`HUB_UNAVAILABLE`。

签名固定为 Ed25519，原文严格为 `kind`、`artifact_id`、`version`、
`sha256`、`size_bytes` 五行 UTF-8 文本，以 LF 连接且末尾无换行。私钥不写入
数据库、普通配置或日志；由部署侧受控配置、KMS 或 Vault 引用管理。客户端只
信任随安装包或 `hub.trusted_keys` 预置的公钥，不得从同一 Hub 动态建立信任根。

## 4. 最小数据模型与管理 API

远程数据库固定为 `hub_category`、`hub_item`、`hub_item_version`、
`hub_artifact`、`hub_download_log` 五表。除下载日志外均使用现有 `BaseDO`
审计字段、逻辑删除和 `@TenantIgnore`；不使用 `tenant_id` 或物理外键。二进制
制品和图标复用 `infra_file`。

| 表 | 关键职责 |
|---|---|
| `hub_category` | `type/code` 唯一的技能与应用分类。 |
| `hub_item` | 目录主实体；`hub_id` 对外唯一，含 `publisher_name` 官方展示字段。 |
| `hub_item_version` | SemVer、渠道、兼容性、权限、Manifest 和发布状态。 |
| `hub_artifact` | 文件引用、摘要、大小、签名、校验报告和可用状态。 |
| `hub_download_log` | 追加式下载结果日志；IP、UA 仅存加盐哈希。 |

Artifact 保留 `signature_key_id` 与签名值；当前签名 key 的轮换由部署侧管理。

管理 API 位于 `/admin-api/hub`，使用 `hub:*` 权限点，只提供分类、条目、
版本、制品和下载日志管理。版本支持 `upload-artifact`、`validate`、
`publish`、`offline`；不提供发布方或签名密钥 CRUD。发布是原子流程：草稿、
上传、安全校验、SHA-256/大小、验证报告、Ed25519 签名、更新最新版本指针、
清理目录缓存。已发布版本不可改写，修复必须创建新版本。

## 5. 技能 ZIP 上传预检规则

技能制品通过 `StockSenseHubSource._read_bundle()` 后，Desktop 只会把
`SKILL.md` 与它显式引用的支持文件送入隔离、扫描和安装流程。后台预检采用相同
的结构限制；通过预检即可保证客户端不会因 ZIP 内部结构拒绝该技能包。

| 规则组 | 关键规则 | 失败示例 |
|---|---|---|
| ZIP 与路径 | 复用所有 ZIP 容器、加密、特殊文件、可执行位、路径穿越和容量基础规则。 | `ARCHIVE_MAGIC_INVALID`、`ENTRY_ENCRYPTED`、`ENTRY_PATH_INVALID` |
| 主文件 | 根目录必须有非空、严格 UTF-8 的 `SKILL.md`。 | `SKILL_MD_MISSING`、`SKILL_MD_UTF8_INVALID` |
| 数量与大小 | 最多 200 个常规文件；任意单文件最多 1,000,000 字节。这与 Desktop 读取器一致。 | `SKILL_FILE_COUNT_EXCEEDED`、`SKILL_FILE_SIZE_EXCEEDED` |
| 文件位置 | 除 `SKILL.md` 外，只允许 `references/`、`templates/`、`scripts/`、`assets/`、`examples/` 下的支持文件。 | `SKILL_FILE_LOCATION_INVALID` |
| 引用闭包 | `SKILL.md` 使用 Markdown 链接、反引号或文本形式引用的支持文件必须存在；禁止引用中的路径穿越；所有支持文件都必须被显式引用，防止“后台已上传但 Desktop 会静默丢弃”的文件。 | `SKILL_REFERENCE_PATH_INVALID`、`SKILL_REFERENCE_MISSING`、`SKILL_FILE_UNREFERENCED` |

这保证的是**结构可读取与可安装**。安装时 Desktop 仍会对技能运行既有的安全扫描、
风险策略和用户确认；若扫描规则命中高风险内容，客户端可能拒绝安装，这是有意保留的
运行时安全边界，而非上传预检失败。

## 6. 应用 `.happ` 上传预检规则

后台管理端在上传后、发布前执行非执行式预检；任何 `BLOCK` 级问题都会阻止
制品发布和客户端下载。预检通过表示制品满足 Desktop `.happ` v1 的静态导入
契约，Desktop 安装时仍必须执行其两阶段二次校验和权限确认。

| 规则组 | 关键规则 | 失败示例 |
|---|---|---|
| ZIP 容器 | 必须为非加密 ZIP；仅允许 Stored/Deflate；条目不允许符号链接、设备文件或可执行位。 | `ARCHIVE_MAGIC_INVALID`、`ENTRY_ENCRYPTED`、`ENTRY_SPECIAL_TYPE` |
| 路径安全 | 拒绝绝对路径、盘符、反斜杠、空/`.`/`..` 段、尾部空格或点、重复及大小写/NFC 冲突路径。 | `ENTRY_PATH_INVALID`、`ENTRY_CASE_COLLISION` |
| 容量限制 | 压缩包和单文件最多 50 MiB、解压总量最多 200 MiB、最多 5,000 条目，且大文件压缩比不超过 200:1。 | `ARCHIVE_SIZE_EXCEEDED`、`EXPANDED_SIZE_EXCEEDED`、`COMPRESSION_RATIO_EXCEEDED` |
| 应用内容边界 | 根目录仅允许 `happ.json`、`app.yaml`、`checksums.json`、可选图标及规定内容目录；禁止 `.env`、密钥、`node_modules`、VCS 目录、脚本、动态库和服务端代码。 | `HAPP_ROOT_NOT_ALLOWED`、`HAPP_SECRET_FILE_FORBIDDEN`、`HAPP_SERVER_CODE_FORBIDDEN` |
| 封装元数据 | 根目录必须包含 `happ.json`、`app.yaml`、`checksums.json`；封装版本必须为 1，创建器、时间、应用 ID、SemVer、`source_included` 与固定文件名必须合法。 | `HAPP_REQUIRED_FILE_MISSING`、`HAPP_ENVELOPE_*` |
| Hub 一致性 | `happ.json` 与 `app.yaml` 的 ID/版本必须相互一致，并与管理端条目 `hub_id` 和版本一致。 | `HAPP_HUB_ID_MISMATCH`、`HAPP_HUB_VERSION_MISMATCH`、`MANIFEST_IDENTITY_MISMATCH` |
| 完整性 | `checksums.json` 必须是按键排序、无多余空白并以 LF 结尾的规范 JSON；其内容须列出每个常规文件（排除自身和可选签名），UTF-8 路径升序、大小和小写 SHA-256 必须精确匹配。 | `HAPP_CHECKSUM_*` |
| Manifest | 严格执行 `app.yaml` v1 schema：未知字段拒绝；入口、图标、提示词和 JSON schema 均需存在；存储权限、MCP 声明和动作参数必须一致。 | `MANIFEST_*` |
| 能力边界 | Hub 导入应用只能声明 `agent` 或已获准 MCP 动作；`agent` 必须请求 `permissions.agent`，MCP 服务必须在白名单中；禁止 `service` 动作。 | `MANIFEST_AGENT_PERMISSION_REQUIRED`、`MANIFEST_ACTION_MCP_PERMISSION_REQUIRED`、`MANIFEST_SERVICE_ACTION_FORBIDDEN` |
| 包签名 | Hub v1 对发布描述符签名。未配置 `.happ` 包签名信任链时，含 `signature.json` 的包一律拒绝，避免后台放行而客户端因未知签名失败。 | `PACKAGE_SIGNATURE_UNSUPPORTED` |

预检报告保存为制品的 `validation_report`，结构为 `{passed, issues[]}`；每个
issue 包含稳定的 `code`、`level`、`path` 和面向管理人员的中文 `message`。

## 7. 验收

- 公开协议、`ETag/304`、错误码和无重定向下载符合本契约。
- 恶意 ZIP/.happ、过期下载令牌、未知签名 key、摘要不匹配和不兼容平台均被拒绝。
- 真实 `HubClient` 消费者契约、Windows x64 与 macOS arm64 安装测试通过。
- `.happ` 安装始终经过 AppHost 的两阶段导入与权限确认。
