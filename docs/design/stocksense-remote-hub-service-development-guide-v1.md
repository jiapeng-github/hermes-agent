# StockSense 远程 Hub 服务开发指南 v1

> 本指南与 `stocksense-hub-service-api-contract-v1.md` 对应；接口和数据
> 语义以该契约为准。

## 1. 模块边界

在 `/Users/penn/Projects/stocksense-admin` 新增独立 Maven 模块
`stocksense-module-hub`，接入根 `pom` 与 `stocksense-server`。Hub 只负责
官方 Skill/App 的目录、制品校验、签名和下载；不实现远程 Gateway、第三方
发布者、自助注册或签名密钥后台。

```text
stocksense-module-hub/
  controller/admin/{category,item,version,artifact,downloadlog}
  controller/app/hub
  dal/{dataobject,mysql}
  enums
  service/{catalog,artifact,publish,signature}
  resources/mapper/hub
  test
```

公开 Controller 使用 `@PermitAll` 并直接返回 DTO；管理 Controller 使用
`@PreAuthorize` 与 `CommonResult`。管理前端位于
`stocksense-ui-admin-vue3/src/api/hub` 和 `src/views/hub`。

## 2. 数据库与发布

创建五张平台公共表：`hub_category`、`hub_item`、`hub_item_version`、
`hub_artifact`、`hub_download_log`。前四表继承 `BaseDO` 并使用
`@TenantIgnore`，下载日志追加写且不阻断下载。禁止物理外键；由 Service 保证
引用完整性。`hub_item.publisher_name` 是官方展示字段，不能以此扩展出发布方
资源；私钥不入表，Artifact 只记录 `signature_key_id`、算法和签名结果。

版本默认交付方式为 `package`，其流转为：条目草稿 → 版本草稿 → 文件服务上传 →
安全解包和结构校验 → SHA-256 与大小计算 → 验证报告 → 部署侧 Ed25519 签名 →
管理员发布 → 更新 latest stable/beta 指针 → 清理缓存。`external` 仅允许 APP，
不上传制品，版本字段保存 `external_install_message`，创建或草稿切换后直接进入
READY，发布时跳过制品校验与签名。任何失败都不得让版本可见；已发布版本不可修改，
修复通过新版本完成。

## 3. 接口实现

公开路径为 `/app-api/hub/v1`，实现分类、技能/应用列表与详情、resolve 和同源
下载。列表只返回已发布、启用、兼容的条目，支持 `q`、`category`、`page`、
`page_size`、`channel`、`compatible_only`。分类、列表、详情使用稳定 ETag；
命中 `If-None-Match` 返回 `304`，resolve 和下载不缓存。

下载 token 绑定 Artifact、版本、平台和过期时间，建议十分钟。非 loopback 必须
HTTPS，禁止重定向，必须流式返回精确 `Content-Length`。Skill ZIP 限 200 文件、
单文件最大 1 MiB、必须有 UTF-8 `SKILL.md`；`.happ` 复用冻结 Manifest Schema，
不允许携带自定义后端代码。

应用目录与详情返回 `delivery`。当 `delivery.type=external` 时，Desktop 仅显示
“外部安装”与运维提示，不调用 resolve、下载或本地导入；服务端必须对误调用的
`POST /apps/{id}/resolve` 返回 `409 HUB_EXTERNAL_INSTALL_REQUIRED`。

管理路径为 `/admin-api/hub`，权限为 `hub:category:*`、`hub:item:*`、
`hub:version:*`、`hub:artifact:*`、`hub:download-log:query`。版本管理提供
上传、校验、发布和下架，不提供 Publisher 或 Signing Key 页面。

## 4. 测试与联调

测试覆盖状态转换、SemVer、兼容性、签名固定向量、ETag、下载 token、安全解包、
发布事务和逻辑删除。Controller 契约测试验证裸 JSON、管理 `CommonResult`、
HTTP 错误、304 和无重定向下载。消费者契约直接运行 Hermes `HubClient` 和
`.happ` 两阶段导入链路。

Desktop 测试配置使用 `hub.enabled`、`hub.base_url`、`hub.channel`、
`hub.require_artifact_signature` 和 `hub.trusted_keys`。验收平台为
`windows-x64` 和 `macos-arm64`。

## 5. 工作量

| 里程碑 | 内容 | 估算 |
|---|---|---:|
| M1 | 模块、五表、DO/Mapper、基础 CRUD | 2 人日 |
| M2 | 文件适配、制品校验、摘要、签名与向量 | 3 人日 |
| M3 | 分类/目录/详情/兼容过滤、ETag/304、Redis | 2.5 人日 |
| M4 | resolve、下载 token、同源下载、下载日志 | 2 人日 |
| M5 | 管理端、Desktop 契约和安全联调 | 3 人日 |

单人串行预计 12.5 人日；后端与管理前端并行预计 8 至 10 个工作日。生产 KMS、
域名证书、对象存储和运维审批等待不包含在该估算内。
