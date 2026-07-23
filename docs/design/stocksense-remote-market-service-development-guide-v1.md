# StockSense 远程市场服务工程开发指南 v1

> 状态：开发基线
> 更新日期：2026-07-23
> 工程路径：`/Users/penn/Projects/stocksense-admin`
> 配套契约：《StockSense 市场服务 API 契约 v1》

## 1. 文档目的

本文面向远程服务工程的独立开发任务，描述后端模块、管理前端、数据库迁移、制品发布、安全、测试和联调实施方式。接口字段、错误码、签名规范以配套 API 契约为准。

## 2. 现有工程基线

当前工程基于 RuoYi-Vue-Pro 风格脚手架：

- Java 25、Spring Boot 4.1.0、Maven 多模块。
- 已启用模块：`stocksense-module-system`、`stocksense-module-infra`。
- 启动模块：`stocksense-server`。
- 管理接口使用 `CommonResult<T>`、`PageResult<T>`。
- DO 继承 `BaseDO`，包含 creator/createTime/updater/updateTime/deleted。
- MyBatis Plus Mapper、Service、Controller、VO 分层。
- 管理 API 自动使用 `/admin-api` 前缀。
- app controller 自动使用 `/app-api` 前缀。
- 管理前端骨架位于 `stocksense-ui/stocksense-ui-admin-vue3/src/api` 与 `src/views`。
- 文件元数据使用现有 `infra_file`，市场模块不重复保存二进制内容。

## 3. 总体架构

```text
StockSense Desktop
  -> /app-api/market/v1/*       公开市场协议，裸 JSON
       -> MarketPublicController
       -> CatalogQueryService
       -> ResolveService
       -> ArtifactDownloadService

Admin Web
  -> /admin-api/market/*        RuoYi 管理协议，CommonResult
       -> Category/Publisher/Item/Version/Key AdminController
       -> PublishService
       -> ArtifactValidationService
       -> SignatureService

MySQL
  -> market_*                   市场元数据
File Service
  -> infra_file                 Skill ZIP / .happ / icon
Redis
  -> catalog ETag/cache
KMS/Vault/Controlled Secret
  -> Ed25519 private key
```

公开市场查询和后台管理共享 Service 与 Mapper，不共享 Controller 响应包装。

## 4. Maven 模块

新增独立模块：

```text
stocksense-module-market/
├── pom.xml
└── src/
    ├── main/
    │   ├── java/cn/iocoder/stocksense/module/market/
    │   │   ├── controller/
    │   │   │   ├── admin/
    │   │   │   │   ├── category/
    │   │   │   │   ├── publisher/
    │   │   │   │   ├── item/
    │   │   │   │   ├── version/
    │   │   │   │   └── signingkey/
    │   │   │   └── app/
    │   │   │       └── marketplace/
    │   │   ├── dal/
    │   │   │   ├── dataobject/
    │   │   │   └── mysql/
    │   │   ├── enums/
    │   │   ├── service/
    │   │   │   ├── catalog/
    │   │   │   ├── artifact/
    │   │   │   ├── publish/
    │   │   │   └── signature/
    │   │   └── util/
    │   └── resources/mapper/market/
    └── test/
```

工程接入点：

1. 根 `pom.xml` 添加 `<module>stocksense-module-market</module>`。
2. `stocksense-dependencies/pom.xml` 管理模块版本。
3. `stocksense-server/pom.xml` 添加 market module 依赖。
4. 模块依赖 `stocksense-module-infra-api` 或工程现有文件服务 API，不直接跨模块访问 Infra Mapper。
5. 不把市场业务写入 `stocksense-module-system`。

如当前工程尚未拆分 `infra-api`，先定义最小内部 `FileStorageApi` 适配层，后续再映射现有文件服务，不允许从市场模块直接操作 `infra_file`。

## 5. 包与类职责

### 5.1 Controller

- `MarketCategoryController`：后台分类 CRUD。
- `MarketPublisherController`：后台发布方 CRUD。
- `MarketItemController`：后台条目 CRUD、下架。
- `MarketVersionController`：版本、上传、校验、发布、下架。
- `MarketSigningKeyController`：签名 key 元数据与轮换。
- `MarketCatalogController`：公开分类、Skill/App 列表、详情。
- `MarketResolveController`：公开 resolve。
- `MarketArtifactController`：受 token 保护的同源下载。

公开 Controller：

- 放在 `controller.app` 下，以获得 `/app-api` 前缀。
- `@RequestMapping("/market/v1")`。
- 使用 `@PermitAll`。
- 直接返回公开 DTO 或 `ResponseEntity<?>`。
- 不返回 `CommonResult`。

后台 Controller：

- 放在 `controller.admin` 下。
- 遵循现有 `create/update/delete/get/page` 命名。
- 使用 `@PreAuthorize`。
- 返回 `CommonResult`。

### 5.2 Service

- `MarketCatalogQueryService`
  - 读取已发布条目和版本。
  - 处理搜索、分类、渠道、兼容过滤。
  - 生成列表/详情 DTO、ETag。
- `MarketResolveService`
  - 校验条目、版本、渠道、平台和客户端兼容性。
  - 生成短期下载 token。
  - 返回已签名的 ArtifactDescriptor。
- `MarketArtifactValidationService`
  - Skill ZIP 与 `.happ` 安全验证。
  - 计算 SHA-256、大小、结构报告。
- `MarketPublishService`
  - 串联上传、校验、签名、发布和缓存清理。
  - 使用事务保证版本发布原子性。
- `MarketSignatureService`
  - 读取受控私钥引用。
  - 按冻结的 5 行 canonical payload 签名。
  - 不向调用方暴露私钥。
- `MarketDownloadTokenService`
  - 生成和验证短期 token。
  - token 绑定 artifact/version/platform/expiry。

## 6. DO、Mapper 与 JSON 字段

创建：

- `MarketCategoryDO`
- `MarketPublisherDO`
- `MarketItemDO`
- `MarketItemVersionDO`
- `MarketArtifactDO`
- `MarketSigningKeyDO`
- `MarketDownloadLogDO`

除下载日志外继承 `BaseDO`，并标注 `@TenantIgnore`。市场目录是平台级公共数据。

JSON 字段：

- `tags`
- `compatibility`
- `permissions`
- `manifest`
- `platforms`
- `validation_report`

使用工程已有 Jackson JSON TypeHandler；禁止 Controller 或 Mapper 手写字符串拼接 JSON。

Mapper 优先继承 `BaseMapperX`，使用 Lambda 查询。只有搜索排序或兼容过滤无法表达时才新增 XML SQL。

## 7. 数据库迁移

新增：

```text
sql/mysql/market.sql
```

包含：

- `market_category`
- `market_publisher`
- `market_item`
- `market_item_version`
- `market_artifact`
- `market_signing_key`
- `market_download_log`
- 市场菜单、按钮权限。
- 必要的字典类型和字典数据。
- 一个官方 Publisher 与基础 Skill/App 分类。

数据库规范：

- MySQL `utf8mb4`、现有工程排序规则。
- 不创建物理外键。
- 索引名称使用 `uk_`、`idx_`。
- 金额与统计本阶段不涉及。
- 私钥不得写入 SQL 或数据库明文字段。
- `market_download_log` 后续按月归档；日志失败不阻断下载。

状态枚举建议：

```text
MarketItemStatus:       DRAFT=0, PUBLISHED=10, OFFLINE=20
MarketVersionStatus:    DRAFT=0, VALIDATING=5, READY=10,
                        PUBLISHED=20, OFFLINE=30, INVALID=40
ArtifactValidateStatus: PENDING=0, PASSED=10, FAILED=20
SigningKeyStatus:       PENDING=0, ACTIVE=10, RETIRED=20
```

这些业务状态使用独立枚举，不复用只能表达“启用/禁用”的通用状态。

## 8. 管理前端

在裁剪后的 Vue3 管理端补充：

```text
stocksense-ui/stocksense-ui-admin-vue3/src/
├── api/market/
│   ├── category.ts
│   ├── publisher.ts
│   ├── item.ts
│   ├── version.ts
│   └── signing-key.ts
└── views/market/
    ├── category/index.vue
    ├── publisher/index.vue
    ├── item/index.vue
    ├── item/ItemForm.vue
    ├── version/index.vue
    ├── version/ArtifactUpload.vue
    └── signing-key/index.vue
```

管理页面：

1. 分类管理。
2. 发布方管理。
3. 市场条目列表，支持 Skill/App、状态、分类和发布方过滤。
4. 条目编辑。
5. 版本与制品页，展示校验报告、摘要、签名 key、发布时间。
6. 密钥页只展示 public key、secret ref、状态和轮换时间，不显示私钥。

发布按钮只有版本状态为 READY、制品验证通过、签名成功时可用。所有不可发布原因必须在 UI 中逐项显示。

## 9. 制品发布流程

```text
创建条目草稿
  -> 创建版本草稿
  -> 上传 Skill ZIP 或 .happ
  -> 文件服务落盘
  -> 安全校验
  -> 计算 size + SHA-256
  -> 保存验证报告
  -> 使用 ACTIVE Ed25519 key 签名
  -> 管理员确认发布
  -> 事务更新 version/item latest pointer
  -> 清理 Redis 目录缓存
  -> 公开市场可见
```

发布事务必须检查：

- 条目未删除且状态允许。
- 版本号在同一条目中唯一。
- 制品类型与条目类型匹配。
- 验证状态 PASSED。
- SHA-256、size、签名已生成。
- 存在激活签名 key。
- App Manifest ID 等于 `market_item.market_id`。
- 平台仅包含 `windows-x64`、`macos-arm64`。

发布后不得修改 version、artifact digest、signature。需要修正时创建新版本。

## 10. 制品安全校验

### 10.1 通用

- 最大 50 MiB。
- 扩展名、MIME 和文件魔数一致。
- 解包在独立临时目录。
- 限制总文件数、总展开大小和压缩比。
- 拒绝绝对路径、`..`、符号链接、硬链接和设备文件。
- 失败后清理临时目录。
- 验证报告只保存结构化错误，不保存文件内容或密钥。

### 10.2 Skill

- `kind=skill_bundle`。
- ZIP 文件最多 200 个。
- 单文件最大 1 MiB。
- 必须包含 UTF-8 `SKILL.md`。
- 校验 Skill 引用的支持文件存在。
- 不执行压缩包中的脚本。

### 10.3 App

- `kind=happ`。
- 复用已冻结 Manifest JSON Schema。
- 不允许自定义后端代码。
- App ID 必须匹配市场 ID。
- 权限声明与市场版本记录一致。
- 服务端校验不替代桌面端两阶段导入。

## 11. 下载与签名实现

### 11.1 下载 URL

第一阶段优先使用市场服务同源下载接口，不返回对象存储重定向：

```text
GET /app-api/market/v1/artifacts/{artifactId}/download?token=...
```

服务端从文件服务读取并流式输出，设置准确 `Content-Length`。若未来改为对象存储直链，必须先升级桌面端“禁止重定向/同源”契约，不能服务端单方面切换。

### 11.2 签名

签名 canonical payload：

```text
kind\nartifact_id\nversion\nsha256\nsize_bytes
```

实现必须使用 UTF-8、LF、末尾无换行。添加固定测试向量，Java 与 Python 客户端应得到一致验证结果。

### 11.3 密钥轮换

1. 生成新 key 和公钥。
2. 先在下一版桌面端预置信任新公钥，保留旧公钥。
3. 发布桌面端。
4. 服务端激活新 key。
5. 观察一段兼容窗口。
6. 停止旧 key 签名，但保留旧公钥验证历史版本。

## 12. 缓存与 ETag

Redis key 建议：

```text
market:v1:categories:{type}
market:v1:list:{type}:{queryHash}
market:v1:detail:{type}:{marketId}:{channel}:{version}
```

ETag 推荐由规范化响应 JSON 的 SHA-256 生成并加引号。生成 JSON 时字段顺序固定，时间字段不能每次请求动态变化，否则会导致 ETag 永远变化。

清理触发：

- 分类创建、更新、禁用。
- 条目可见字段更新。
- 版本发布或下架。
- Publisher 公开字段更新。
- 图标替换。

## 13. 公开 API 防护

- 按 IP、客户端版本和路径限流。
- 列表最大 `page_size=50`。
- 搜索关键词长度上限 100。
- 详情 ID 长度上限 200。
- resolve 每 IP/条目限流。
- 下载 token 一次或短期有效，最大 10 分钟。
- 日志不记录 token、API key、私钥或完整 IP。
- `MARKET_DISABLED` 由 `config.yaml`/数据库配置控制，不使用新的非密钥环境变量作为用户配置。

## 14. 配置项

服务端使用现有 Spring 配置体系，例如：

```yaml
stocksense:
  market:
    enabled: true
    public-base-url: https://market.example.com/app-api/market/v1
    catalog-cache-minutes: 5
    download-token-minutes: 10
    max-artifact-bytes: 52428800
    signing-key-id: stocksense-market-2026-01
```

私钥值不进入 YAML；YAML 只包含 secret reference。生产环境由 KMS/Vault/部署密钥提供者解析。

## 15. 测试策略

### 15.1 单元测试

- 条目和版本状态转换。
- SemVer 与兼容性判断。
- canonical payload。
- 固定 Ed25519 测试向量。
- ETag 稳定性。
- 下载 token 生成、过期、篡改。
- Skill/App 校验规则。

### 15.2 Mapper 与 Service 集成测试

- 使用临时数据库或 Testcontainers。
- 发布事务回滚。
- latest stable/beta 指针。
- 逻辑删除与 `@TenantIgnore`。
- 搜索、分页、分类、渠道过滤。

### 15.3 Controller 契约测试

- 公开接口返回裸 JSON。
- 管理接口返回 `CommonResult`。
- ETag 与 304。
- 错误码与 HTTP 状态。
- 文件下载无重定向且 Content-Length 正确。

### 15.4 消费者契约测试

在 CI 中直接运行或复用 Hermes 侧的 Python `MarketplaceClient`：

- `/categories`
- `/skills`、`/skills/{id}`、resolve、下载、安装。
- `/apps`、`/apps/{id}`、resolve、下载、两阶段导入。
- Windows x64、macOS arm64。
- 过期 URL、未知 key、错误 digest、超大制品、无兼容版本。

消费者契约测试是发布门禁，Java MockMvc 通过不能替代真实客户端验证。

## 16. 本地联调

远程服务：

```text
http://127.0.0.1:48080/app-api/market/v1
```

桌面端配置：

```yaml
marketplace:
  enabled: true
  base_url: http://127.0.0.1:48080/app-api/market/v1
  channel: stable
  require_artifact_signature: true
  trusted_keys:
    stocksense-market-dev: <base64-public-key>
```

开发环境仅允许 loopback HTTP。非 loopback 地址必须 HTTPS。

推荐准备两个固定测试条目：

- Skill：最小合法 `skill_bundle`。
- App：最小合法 `.happ`。

## 17. 目录级开发任务拆分

### M1：工程与数据库，2 人日

- 新增 module、POM 依赖、SQL。
- DO、Mapper、枚举。
- 基础 Service 和管理 CRUD。

### M2：制品验证与签名，3 人日

- 文件服务适配。
- Skill/App 验证。
- SHA-256、Ed25519、密钥轮换基础。
- 固定签名测试向量。

### M3：公开目录与缓存，2.5 人日

- 分类、列表、详情。
- 搜索、分页、兼容过滤。
- ETag/304、Redis 缓存与失效。

### M4：resolve 与下载，2 人日

- 版本解析。
- 下载 token。
- 同源流式下载。
- 下载日志。

### M5：管理前端，3 人日

- 分类、Publisher、条目、版本、上传、验证报告、发布和 key 页面。

### M6：联调与安全测试，3 人日

- Desktop 消费者契约测试。
- Windows/macOS 安装链路。
- 恶意压缩包、签名、摘要、过期和限流测试。

单人串行约 15.5 人日；后端与前端并行约 10 到 12 个工作日。以上不包含生产 KMS、域名证书、对象存储和运维审批等待时间。

## 18. 提交顺序

1. 数据库与模块骨架。
2. DO/Mapper/Service/Admin CRUD。
3. 验证与签名。
4. Public catalog。
5. resolve/download。
6. 管理前端。
7. 消费者契约测试。
8. 生产配置与部署说明。

每个阶段保持独立可回滚提交，不把脚手架、业务、前端和大批格式化混在一个提交中。

## 19. Definition of Done

- 配套 API 契约冻结项全部满足。
- SQL 可在空库执行，重复迁移策略明确。
- 管理端可完成从草稿到发布、下架的完整流程。
- 公开目录支持 ETag/304。
- Skill 与 App 可由真实桌面端安装。
- SHA-256 和 Ed25519 通过跨语言固定测试向量。
- 私钥、token 和明文 IP 不进入日志。
- 恶意压缩包安全测试通过。
- Windows x64、macOS arm64 消费者契约测试通过。
- OpenAPI 中明确区分 `/app-api/market/v1` 裸 JSON与 `/admin-api/market` CommonResult。
