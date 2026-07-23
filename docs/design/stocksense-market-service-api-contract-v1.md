# StockSense 市场服务 API 契约 v1

> 状态：冻结候选
> 版本：v1.1
> 更新日期：2026-07-23
> 适用范围：StockSense Desktop、StockSense 远程市场服务
> 远程工程：`/Users/penn/Projects/stocksense-admin`

## 1. 目标与边界

本契约统一远程技能市场与远程应用市场的接口、缓存、制品校验和错误语义。第一阶段支持：

- 技能目录浏览、搜索、分类、详情、版本解析与安装包下载。
- 应用目录浏览、搜索、分类、详情、版本解析与 `.happ` 下载。
- 客户端平台仅支持 `windows-x64`、`macos-arm64`。
- 目录匿名可读；发布、上下架和签名密钥管理仅开放后台管理接口。
- 应用仍遵守 AppHost 安全边界，不允许携带自定义后端代码。
- 客户端继续执行 `.happ` 两阶段导入；远程服务只负责可信分发。

第一阶段不包含：

- 远程 Gateway。
- 用户账号、购买、订阅、付费结算。
- 第三方开发者自助发布。
- 动态下发信任根公钥。
- 服务端执行 Skill 或 App。

## 2. 双接口边界

远程服务同时提供两类接口，两类响应格式不得混用。

### 2.1 公开市场协议

- 基础地址：`https://<host>/app-api/market/v1`
- 桌面端配置项 `marketplace.base_url` 必须直接指向上述地址。
- 返回裸 JSON，使用标准 HTTP 状态码、`ETag`、`304 Not Modified`。
- 错误统一返回 `{"error": {...}}`。
- 不使用 RuoYi `CommonResult` 包装。

这是桌面端已经实现的外部协议。服务端不得把它改成 `{code,msg,data}`，否则会破坏目录缓存、错误映射和安装链路。

### 2.2 后台管理协议

- 基础地址：`https://<host>/admin-api/market`
- 延续远程工程现有规范：
  - `CommonResult<T>`：`{code,msg,data}`
  - `PageResult<T>`：`{list,total}`
  - 分页参数：`pageNo`、`pageSize`
  - `@PreAuthorize("@ss.hasPermission('market:...'))`
  - `BaseDO` 审计字段与逻辑删除

## 3. 通用约定

### 3.1 请求头

客户端发送：

| 请求头 | 必填 | 说明 |
|---|---:|---|
| `Accept: application/json` | 是 | JSON 响应 |
| `X-StockSense-Client-Version` | 是 | 桌面端版本，例如 `0.19.0` |
| `X-StockSense-Runtime-Version` | 是 | Hermes Runtime 版本 |
| `If-None-Match` | 否 | 列表、分类和详情缓存协商 |
| `X-Request-Id` | 否 | 客户端生成的链路 ID；服务端不存在时补充 |

服务端响应：

| 响应头 | 说明 |
|---|---|
| `ETag` | 分类、列表、详情响应的内容版本 |
| `Cache-Control` | 推荐 `public,max-age=300,stale-if-error=86400` |
| `X-Request-Id` | 全链路请求 ID |
| `Retry-After` | `429`、部分 `503` 响应的重试秒数 |

### 3.2 时间、ID 与版本

- 时间使用带时区 RFC 3339，例如 `2026-07-23T20:30:00+08:00`。
- 对外 `id` 使用稳定字符串，不暴露数据库自增主键。
- Skill ID 推荐反向域名或仓库命名空间，例如 `ai.stocksense.a-stock-data`。
- App ID 必须与 `.happ` Manifest 的 `id` 完全一致。
- 版本使用 SemVer；第一阶段不接受可变标签作为安装版本。
- 渠道仅允许 `stable`、`beta`，默认 `stable`。

### 3.3 分页与过滤

公开列表通用参数：

| 参数 | 默认值 | 约束 |
|---|---:|---|
| `q` | 空 | 名称、摘要、标签关键词 |
| `category` | 空 | 分类 code |
| `page` | 1 | 大于等于 1 |
| `page_size` | 24 | 1 到 50 |
| `channel` | `stable` | `stable` 或 `beta` |
| `compatible_only` | `true` | 按客户端与 Runtime 版本过滤 |

统一分页响应：

```json
{
  "items": [],
  "page": 1,
  "page_size": 24,
  "total": 0,
  "has_more": false,
  "generated_at": "2026-07-23T20:30:00+08:00"
}
```

### 3.4 公共错误格式

```json
{
  "error": {
    "code": "MARKET_ITEM_NOT_FOUND",
    "message": "未找到指定市场条目",
    "retryable": false,
    "request_id": "req_01J...",
    "details": {
      "item_id": "ai.stocksense.example"
    }
  }
}
```

主要错误码：

| HTTP | code | 可重试 | 场景 |
|---:|---|---:|---|
| 400 | `MARKET_INVALID_REQUEST` | 否 | 参数格式错误 |
| 404 | `MARKET_ITEM_NOT_FOUND` | 否 | 条目或版本不存在 |
| 409 | `MARKET_VERSION_INCOMPATIBLE` | 否 | 平台或版本不兼容 |
| 409 | `MARKET_ARTIFACT_EXPIRED` | 是 | 下载凭证过期，重新 resolve |
| 413 | `MARKET_ARTIFACT_TOO_LARGE` | 否 | 制品超过上限 |
| 422 | `MARKET_ARTIFACT_REJECTED` | 否 | 制品校验未通过 |
| 422 | `MARKET_SIGNATURE_INVALID` | 否 | 签名不可用 |
| 429 | `MARKET_RATE_LIMITED` | 是 | 访问频率过高 |
| 503 | `MARKET_DISABLED` | 否 | 服务端市场功能关闭 |
| 503 | `MARKET_UNAVAILABLE` | 是 | 临时不可用 |

## 4. 数据模型

### 4.1 Category

```json
{
  "id": "finance-data",
  "type": "skill",
  "name": "金融数据",
  "description": "行情、财务、公告和研报数据能力",
  "icon_url": "/assets/icons/categories/finance-data.png",
  "sort": 100
}
```

### 4.2 Publisher

```json
{
  "id": "stocksense-official",
  "name": "StockSense",
  "verified": true,
  "homepage_url": "https://stocksense.example.com"
}
```

### 4.3 SkillCatalogItem

```json
{
  "id": "ai.stocksense.a-stock-data",
  "type": "skill",
  "name": "A 股数据分析",
  "summary": "通过金融数据源完成行情、财务与板块分析",
  "description": "完整介绍文本",
  "category": "finance-data",
  "publisher": {
    "id": "stocksense-official",
    "name": "StockSense",
    "verified": true
  },
  "version": "1.2.0",
  "channel": "stable",
  "verified": true,
  "featured": true,
  "icon_url": "/assets/icons/skills/ai.stocksense.a-stock-data.png",
  "tags": ["A股", "行情", "财务"],
  "compatibility": {
    "min_client_version": "0.19.0",
    "min_runtime_version": "0.18.0",
    "platforms": ["windows-x64", "macos-arm64"]
  },
  "permissions": ["network:mx-ds-mcp"],
  "updated_at": "2026-07-23T20:30:00+08:00"
}
```

### 4.4 AppCatalogItem

```json
{
  "id": "ai.hermes.watchlist",
  "type": "app",
  "name": "自选股盯盘看板",
  "summary": "A 股自选股盯盘、K 线详情与公司分析应用",
  "description": "完整介绍文本",
  "category": "stock-analysis",
  "publisher": {
    "id": "stocksense-official",
    "name": "StockSense",
    "verified": true
  },
  "version": "1.1.0",
  "channel": "stable",
  "verified": true,
  "featured": true,
  "icon_url": "/assets/icons/apps/ai.hermes.watchlist.png",
  "tags": ["自选股", "盯盘"],
  "compatibility": {
    "min_client_version": "0.19.0",
    "min_runtime_version": "0.18.0",
    "platforms": ["windows-x64", "macos-arm64"]
  },
  "permissions": [
    "agent:invoke",
    "mcp:mx-ds-mcp",
    "storage:profile"
  ],
  "updated_at": "2026-07-23T20:30:00+08:00"
}
```

### 4.5 ArtifactDescriptor

```json
{
  "kind": "happ",
  "artifact_id": "art_01J...",
  "version": "1.1.0",
  "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "size_bytes": 1832451,
  "download_url": "https://market.example.com/app-api/market/v1/artifacts/art_01J.../download?token=...",
  "expires_at": "2026-07-23T20:40:00+08:00",
  "signature": {
    "algorithm": "ed25519",
    "key_id": "stocksense-market-2026-01",
    "value": "base64-signature"
  }
}
```

`kind` 仅允许：

- Skill：`skill_bundle`
- App：`happ`

签名原文必须是以下 5 行 UTF-8 字节，使用 `\n` 连接，末尾无额外换行：

```text
kind
artifact_id
version
sha256
size_bytes
```

示例：

```text
happ
art_01J...
1.1.0
0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
1832451
```

## 5. 公开市场接口

### 5.1 查询分类

`GET /categories?type=skill|app`

响应：

```json
{
  "items": [
    {
      "id": "finance-data",
      "type": "skill",
      "name": "金融数据",
      "description": "金融数据能力",
      "sort": 100
    }
  ],
  "generated_at": "2026-07-23T20:30:00+08:00"
}
```

支持 `ETag` 和 `304`。

### 5.2 查询技能列表

`GET /skills?q=&category=&page=1&page_size=24&channel=stable&compatible_only=true`

响应为通用分页对象，`items` 是 `SkillCatalogItem[]`。

### 5.3 查询技能详情

`GET /skills/{skill_id}?channel=stable&version=1.2.0`

`version` 可省略，省略时返回指定渠道最新已发布兼容版本。

```json
{
  "item": {},
  "versions": [
    {
      "version": "1.2.0",
      "channel": "stable",
      "published_at": "2026-07-23T20:30:00+08:00",
      "release_notes": "..."
    }
  ]
}
```

### 5.4 解析技能安装制品

`POST /skills/{skill_id}/resolve`

```json
{
  "version": "1.2.0",
  "channel": "stable",
  "platform": "windows-x64"
}
```

响应：

```json
{
  "item": {},
  "artifact": {
    "kind": "skill_bundle",
    "artifact_id": "art_01J...",
    "version": "1.2.0",
    "sha256": "...",
    "size_bytes": 104857,
    "download_url": "...",
    "expires_at": "...",
    "signature": {
      "algorithm": "ed25519",
      "key_id": "stocksense-market-2026-01",
      "value": "..."
    }
  }
}
```

### 5.5 查询应用列表

`GET /apps?q=&category=&page=1&page_size=24&channel=stable&compatible_only=true`

响应为通用分页对象，`items` 是 `AppCatalogItem[]`。

### 5.6 查询应用详情

`GET /apps/{app_id}?channel=stable&version=1.1.0`

响应结构与技能详情一致，`item` 为 `AppCatalogItem`。

### 5.7 解析应用安装制品

`POST /apps/{app_id}/resolve`

请求体与技能 resolve 一致。响应中的 `artifact.kind` 必须为 `happ`。

### 5.8 图标

`GET /assets/icons/{scope}/{id}.{ext}`

- 图标 URL 必须与 `marketplace.base_url` 同源。
- 禁止 HTTP 重定向。
- Content-Type 必须是 `image/*`。
- 单图最大 512 KiB。
- 推荐长期缓存：`public,max-age=86400,immutable`。

### 5.9 下载制品

`GET /artifacts/{artifact_id}/download?token=<short-lived-token>`

- 下载 URL 必须同源 HTTPS，开发环境允许 loopback HTTP。
- token 推荐 10 分钟过期，绑定 `artifact_id`、版本和客户端平台。
- 禁止重定向。
- 必须返回准确的 `Content-Length`。
- 制品上限 50 MiB。
- 客户端下载后校验 `size_bytes`、SHA-256 和 Ed25519 签名。
- Skill ZIP 还会由客户端检查路径穿越、符号链接、文件数量、单文件大小和 `SKILL.md`。
- `.happ` 还会进入客户端两阶段安全导入。

## 6. 缓存与一致性

- 分类、列表和详情必须产生稳定 ETag。
- ETag 至少覆盖：查询条件、可见条目、版本、上下架状态和更新时间。
- 收到相同 `If-None-Match` 时返回 `304`，响应体为空。
- 发布、下架、修改可见字段后必须清理相关分类、列表、详情缓存。
- 客户端默认目录缓存 5 分钟，离线陈旧缓存可使用 24 小时。
- resolve 与下载地址不得缓存。
- 发布必须原子化：元数据、制品验证、摘要、签名全部成功后，版本才可见。

## 7. 信任根与密钥

- 服务端使用 Ed25519 私钥签名制品描述符。
- 私钥不写入数据库明文；数据库只保存 KMS/Vault/环境密钥引用。
- 公钥通过安装包或受控配置预置到桌面端 `marketplace.trusted_keys`。
- 桌面端不得从同一个市场服务动态下载并直接信任新公钥。
- 密钥轮换时，安装包应先同时信任新旧公钥，再切换服务端签名 key，最后退役旧 key。
- `require_artifact_signature=true` 的生产包不得安装无签名或未知 `key_id` 制品。

## 8. 后台管理接口

后台管理接口统一返回 `CommonResult`。

### 8.1 分类

| 方法 | 路径 | 权限 |
|---|---|---|
| POST | `/admin-api/market/category/create` | `market:category:create` |
| PUT | `/admin-api/market/category/update` | `market:category:update` |
| DELETE | `/admin-api/market/category/delete?id=` | `market:category:delete` |
| GET | `/admin-api/market/category/get?id=` | `market:category:query` |
| GET | `/admin-api/market/category/page` | `market:category:query` |

### 8.2 发布方

| 方法 | 路径 | 权限 |
|---|---|---|
| POST | `/admin-api/market/publisher/create` | `market:publisher:create` |
| PUT | `/admin-api/market/publisher/update` | `market:publisher:update` |
| DELETE | `/admin-api/market/publisher/delete?id=` | `market:publisher:delete` |
| GET | `/admin-api/market/publisher/get?id=` | `market:publisher:query` |
| GET | `/admin-api/market/publisher/page` | `market:publisher:query` |

### 8.3 市场条目

| 方法 | 路径 | 权限 |
|---|---|---|
| POST | `/admin-api/market/item/create` | `market:item:create` |
| PUT | `/admin-api/market/item/update` | `market:item:update` |
| DELETE | `/admin-api/market/item/delete?id=` | `market:item:delete` |
| GET | `/admin-api/market/item/get?id=` | `market:item:query` |
| GET | `/admin-api/market/item/page` | `market:item:query` |
| PUT | `/admin-api/market/item/offline?id=` | `market:item:publish` |

### 8.4 版本与制品

| 方法 | 路径 | 权限 |
|---|---|---|
| POST | `/admin-api/market/version/create` | `market:version:create` |
| PUT | `/admin-api/market/version/update` | `market:version:update` |
| DELETE | `/admin-api/market/version/delete?id=` | `market:version:delete` |
| GET | `/admin-api/market/version/get?id=` | `market:version:query` |
| GET | `/admin-api/market/version/page` | `market:version:query` |
| POST | `/admin-api/market/version/upload-artifact` | `market:artifact:upload` |
| POST | `/admin-api/market/version/validate?id=` | `market:artifact:validate` |
| PUT | `/admin-api/market/version/publish?id=` | `market:version:publish` |
| PUT | `/admin-api/market/version/offline?id=` | `market:version:publish` |

上传使用 `multipart/form-data`，字段为 `versionId`、`file`。服务端必须在发布前完成：

1. MIME、扩展名和大小检查。
2. 安全解包与结构校验。
3. 计算 SHA-256 与大小。
4. 保存到现有文件服务并记录 `infra_file.id`。
5. 生成验证报告。
6. 使用当前激活密钥签名。

### 8.5 签名密钥

| 方法 | 路径 | 权限 |
|---|---|---|
| POST | `/admin-api/market/signing-key/create` | `market:key:create` |
| GET | `/admin-api/market/signing-key/page` | `market:key:query` |
| PUT | `/admin-api/market/signing-key/activate?id=` | `market:key:update` |
| PUT | `/admin-api/market/signing-key/retire?id=` | `market:key:update` |

接口只接受和返回密钥引用、公钥、key ID 与状态，不返回私钥内容。

## 9. 数据库表设计

市场目录为平台级公共数据，所有业务 DO 使用 `@TenantIgnore`，不增加 `tenant_id`。除访问日志外，表使用现有 `BaseDO` 字段：

```text
creator varchar(64) default ''
create_time datetime not null default current_timestamp
updater varchar(64) default ''
update_time datetime not null default current_timestamp on update current_timestamp
deleted bit(1) not null default b'0'
```

不创建数据库外键，由 Service 层保证引用完整性。

### 9.1 `market_category`

| 字段 | 类型 | 约束/说明 |
|---|---|---|
| `id` | bigint | PK，自增 |
| `type` | varchar(16) | `skill` / `app` |
| `code` | varchar(64) | 对外分类 ID |
| `name` | varchar(128) | 名称 |
| `description` | varchar(500) | 简介 |
| `icon_url` | varchar(1024) | 可空 |
| `sort` | int | 默认 0 |
| `status` | tinyint | 0 启用，1 禁用 |
| BaseDO 字段 | - | 审计与逻辑删除 |

索引：

- `uk_market_category_type_code(type, code)`
- `idx_market_category_type_status_sort(type, status, sort)`

分类 code 不复用；删除后如需恢复使用恢复或改为禁用。

### 9.2 `market_publisher`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | bigint | PK |
| `code` | varchar(64) | 对外发布方 ID |
| `name` | varchar(128) | 名称 |
| `homepage_url` | varchar(1024) | 主页 |
| `avatar_url` | varchar(1024) | 图标 |
| `verified` | bit(1) | 是否认证 |
| `status` | tinyint | 0 启用，1 禁用 |
| `remark` | varchar(500) | 备注 |
| BaseDO 字段 | - | 审计与逻辑删除 |

索引：`uk_market_publisher_code(code)`。

### 9.3 `market_item`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | bigint | PK |
| `market_id` | varchar(200) | 对外稳定 ID；App 必须等于 Manifest ID |
| `type` | varchar(16) | `skill` / `app` |
| `name` | varchar(128) | 名称 |
| `summary` | varchar(500) | 列表摘要 |
| `description` | text | 详情介绍 |
| `category_id` | bigint | 分类 ID |
| `publisher_id` | bigint | 发布方 ID |
| `icon_file_id` | bigint | 可空，关联现有文件服务 |
| `icon_url` | varchar(1024) | 对外同源地址或兼容回退 |
| `tags` | json | 标签数组 |
| `keywords` | varchar(1000) | 搜索冗余字段 |
| `verified` | bit(1) | 认证标记 |
| `featured` | bit(1) | 推荐标记 |
| `sort` | int | 排序 |
| `status` | tinyint | 0 草稿，10 已发布，20 已下架 |
| `latest_stable_version_id` | bigint | 可空 |
| `latest_beta_version_id` | bigint | 可空 |
| `published_at` | datetime | 首次发布时间 |
| BaseDO 字段 | - | 审计与逻辑删除 |

索引：

- `uk_market_item_market_id(market_id)`
- `idx_market_item_type_status_sort(type, status, featured, sort)`
- `idx_market_item_category_status(category_id, status)`
- `idx_market_item_publisher(publisher_id)`

### 9.4 `market_item_version`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | bigint | PK |
| `item_id` | bigint | 条目 ID |
| `version` | varchar(64) | SemVer |
| `channel` | varchar(16) | `stable` / `beta` |
| `release_notes` | text | 更新说明 |
| `compatibility` | json | 完整兼容配置 |
| `permissions` | json | 权限声明数组 |
| `manifest` | json | 服务端解析后的 Skill/App 元数据 |
| `min_client_version` | varchar(64) | 查询冗余字段 |
| `min_runtime_version` | varchar(64) | 查询冗余字段 |
| `platforms` | json | 支持平台数组 |
| `artifact_id` | bigint | 当前制品 ID |
| `status` | tinyint | 0 草稿，5 校验中，10 可发布，20 已发布，30 已下架，40 校验失败 |
| `published_at` | datetime | 发布时间 |
| BaseDO 字段 | - | 审计与逻辑删除 |

索引：

- `uk_market_item_version(item_id, version)`
- `idx_market_version_item_channel_status(item_id, channel, status, published_at)`
- `idx_market_version_artifact(artifact_id)`

### 9.5 `market_artifact`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | bigint | PK |
| `item_version_id` | bigint | 版本 ID |
| `kind` | varchar(32) | `skill_bundle` / `happ` |
| `file_id` | bigint | 关联 `infra_file.id` |
| `artifact_name` | varchar(255) | 原始文件名 |
| `sha256` | char(64) | 小写十六进制 |
| `size_bytes` | bigint | 字节数 |
| `content_type` | varchar(128) | MIME |
| `signature_key_id` | varchar(64) | 签名 key ID |
| `signature_algorithm` | varchar(32) | 固定 `ed25519` |
| `signature_value` | varchar(512) | Base64 签名 |
| `validation_status` | tinyint | 0 待校验，10 通过，20 失败 |
| `validation_report` | json | 结构化报告，不含密钥 |
| `status` | tinyint | 0 可用，1 禁用 |
| BaseDO 字段 | - | 审计与逻辑删除 |

索引：

- `uk_market_artifact_version(item_version_id)`
- `idx_market_artifact_sha256(sha256)`
- `idx_market_artifact_file(file_id)`

第一阶段每个版本只有一个生效制品。重新上传时废弃旧制品并更新版本引用。

### 9.6 `market_signing_key`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | bigint | PK |
| `key_id` | varchar(64) | 对外 key ID |
| `algorithm` | varchar(32) | `ed25519` |
| `public_key_base64` | varchar(256) | 公钥 |
| `secret_ref` | varchar(512) | KMS/Vault/受控配置引用 |
| `activated_at` | datetime | 激活时间 |
| `retired_at` | datetime | 退役时间 |
| `status` | tinyint | 0 待启用，10 已激活，20 已退役 |
| BaseDO 字段 | - | 审计与逻辑删除 |

索引：

- `uk_market_signing_key_key_id(key_id)`
- `idx_market_signing_key_status(status)`

同一时刻只允许一个写签名的激活密钥，旧公钥可以继续保留用于校验历史制品。

### 9.7 `market_download_log`

访问日志为追加写，不使用逻辑删除：

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | bigint | PK |
| `item_id` | bigint | 条目 ID |
| `item_version_id` | bigint | 版本 ID |
| `artifact_id` | bigint | 制品 ID |
| `item_type` | varchar(16) | skill/app |
| `platform` | varchar(32) | 客户端平台 |
| `client_version` | varchar(64) | 桌面端版本 |
| `runtime_version` | varchar(64) | Runtime 版本 |
| `client_ip_hash` | char(64) | 加盐哈希，不保存明文 IP |
| `user_agent_hash` | char(64) | 可空 |
| `result` | tinyint | 0 成功，1 失败 |
| `error_code` | varchar(64) | 可空 |
| `request_id` | varchar(64) | 链路 ID |
| `create_time` | datetime | 创建时间 |

索引：

- `idx_market_download_item_time(item_id, create_time)`
- `idx_market_download_artifact_time(artifact_id, create_time)`
- `idx_market_download_request(request_id)`

日志写入失败不得阻断下载主链路。

## 10. 联调验收标准

1. 桌面端只配置 `marketplace.base_url`、渠道与信任公钥即可浏览两个市场。
2. 列表首次返回 `200 + ETag`，相同条件再次请求可返回 `304`。
3. Skill/App 详情与 resolve 可以按固定版本和渠道查询。
4. Windows x64 与 macOS arm64 可获得对应兼容制品。
5. 下载无重定向，大小、SHA-256、签名全部通过桌面端现有校验。
6. 未知 key、摘要不符、过期 URL、超限制品均被拒绝并返回冻结错误码。
7. App 安装继续显示权限确认并完成两阶段导入。
8. 后台发布后目录缓存失效，下架后新请求不可见。
9. 管理接口使用 `CommonResult`，公开接口不使用该包装。
10. 公共接口契约测试可直接用桌面端 `MarketplaceClient` 作为消费者运行。

## 11. 冻结项

以下内容属于 v1 基础契约，编码后不得单方面修改：

- 公开 API 基础路径与裸 JSON 响应边界。
- Skill/App 列表、详情、resolve 路径。
- `ArtifactDescriptor` 字段与签名原文。
- `skill_bundle`、`happ` kind。
- 同源、无重定向、大小与 SHA-256 校验规则。
- ETag/304 行为。
- 公共错误格式。
- 平台枚举 `windows-x64`、`macos-arm64`。
- App ID 与 `.happ` Manifest ID 一致。
- 信任根不从市场服务动态自举。
