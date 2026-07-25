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

## 5. 验收

- 公开协议、`ETag/304`、错误码和无重定向下载符合本契约。
- 恶意 ZIP/.happ、过期下载令牌、未知签名 key、摘要不匹配和不兼容平台均被拒绝。
- 真实 `HubClient` 消费者契约、Windows x64 与 macOS arm64 安装测试通过。
- `.happ` 安装始终经过 AppHost 的两阶段导入与权限确认。
