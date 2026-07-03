# TeachAgent 部署到 Azure App Service

这条路径适合你现在的情况：

- 代码已经在 GitHub
- 你想让别人通过公网访问
- 你又不想继续折腾 `AZURE_CLIENT_SECRET`

推荐方案：

- `Azure App Service`
- `System assigned managed identity`
- `GitHub` 持续部署
- `PostgreSQL` 继续用你现有的 Neon 连接串

## 这套仓库现在的 App Service 入口

- 根目录 `requirements.txt`
  - 给 Azure Oryx 构建用
- 根目录 `startup.sh`
  - 给 App Service 启动用
- `app/server.py`
  - 已兼容 `WEBSITE_HOSTNAME` / `WEBSITES_PORT`

## 部署前准备

你至少要准备好这些值：

```env
TEACHAGENT_DATABASE_URL=postgresql://...
AZURE_AI_PROJECT_ENDPOINT=https://YOUR_PROJECT.services.ai.azure.com/api/projects/proj-default
AZURE_AI_MODEL_DEPLOYMENT=你的聊天模型 deployment 名
```

如果后面要做 embedding，再补：

```env
AZURE_AI_EMBEDDING_DEPLOYMENT=你的 embedding deployment 名
```

## 一、创建 App Service

建议走 Azure 门户：

1. 进入 `App Services`
2. 点击 `Create`
3. 选择：
   - `Publish`: `Code`
   - `Runtime stack`: `Python 3.11`
   - `Operating System`: `Linux`
4. 选择你的订阅、资源组、应用名和区域
5. `App Service Plan` 先选你能接受的最低可用规格

说明：

- 如果只是演示，低配也能先跑
- 如果你要让别人稳定访问，建议别用太弱的计划

官方文档：

- https://learn.microsoft.com/en-us/azure/app-service/quickstart-python

## 二、打开托管身份

1. 进入这个 Web App
2. 左侧 `Identity`
3. `System assigned` -> `On`
4. 保存

这是关键，因为我们要让 App Service 自己去拿 Azure 身份，不再手填 `AZURE_CLIENT_SECRET`。

官方文档：

- https://learn.microsoft.com/en-us/azure/app-service/overview-managed-identity

## 三、给这个身份 Azure AI Foundry 权限

1. 打开你的 `Azure AI Foundry` 项目或对应资源
2. 进入 `Access control (IAM)`
3. `Add role assignment`
4. 给刚才那个 Web App 的托管身份分配可调用 Foundry 的角色

常见是下面之一：

- `Azure AI User`
- `Azure AI Developer`
- Foundry 项目里等价的推理调用角色

如果你不确定，就先在项目或资源的 IAM 里搜索这几个名字。

官方文档：

- https://learn.microsoft.com/en-us/azure/ai-foundry/concepts/rbac-azure-ai-foundry

## 四、配置环境变量

进入 Web App：

1. 左侧 `Settings` -> `Environment variables`
2. 在 `App settings` 里添加这些键值

```env
SCM_DO_BUILD_DURING_DEPLOYMENT=1
TEACHAGENT_USE_DEFAULT_CREDENTIAL=1
TEACHAGENT_HOST=0.0.0.0
TEACHAGENT_PORT=8000
TEACHAGENT_DATABASE_URL=postgresql://...
AZURE_AI_PROJECT_ENDPOINT=https://YOUR_PROJECT.services.ai.azure.com/api/projects/proj-default
AZURE_AI_MODEL_DEPLOYMENT=你的聊天模型 deployment 名
```

可选：

```env
AZURE_AI_EMBEDDING_DEPLOYMENT=你的 embedding deployment 名
```

说明：

- `SCM_DO_BUILD_DURING_DEPLOYMENT=1`
  - 让 Azure 在部署时执行 Python 依赖安装
- `TEACHAGENT_USE_DEFAULT_CREDENTIAL=1`
  - 强制代码走托管身份
- `TEACHAGENT_PORT=8000`
  - 配合 `startup.sh`

## 五、设置启动命令

进入 Web App：

1. 左侧 `Settings` -> `Configuration`
2. 找到 `Startup Command`
3. 填：

```sh
sh startup.sh
```

这个脚本会启动：

```sh
python app/server.py
```

官方文档：

- https://learn.microsoft.com/en-us/azure/app-service/configure-language-python

## 六、连接 GitHub 自动部署

进入 Web App：

1. 左侧 `Deployment Center`
2. Source 选 `GitHub`
3. 登录 GitHub
4. 选择：
   - 你的仓库 `xumuchixu-star/Teachagent`
   - branch: `main`
5. 保存

这样之后每次你 push 到 `main`，Azure 会自动拉代码重建。

## 七、部署完成后检查

先看：

1. `Log stream`
2. 首页能否打开
3. 健康检查地址：

```text
https://你的域名/healthz
```

正常应返回类似：

```json
{"status":"ok","student_id":"demo_student", ...}
```

再检查 4 件事：

1. 页面能打开
2. 数据库状态不是本地 JSON
3. 诊断 / coach 能正常回包
4. 切换学生后数据是隔离的

## 常见问题

### 1. 启动后 500 / 容器没起来

优先检查：

- `requirements.txt` 是否在仓库根目录
- `Startup Command` 是否填了 `sh startup.sh`
- `SCM_DO_BUILD_DURING_DEPLOYMENT` 是否为 `1`

### 2. 页面能开，但诊断 / coach 报 Azure 权限错误

通常是：

- 托管身份没打开
- Foundry IAM 没给角色
- `AZURE_AI_PROJECT_ENDPOINT` 填错
- `AZURE_AI_MODEL_DEPLOYMENT` 填成了不能聊天的 deployment

### 3. 数据刷新后丢失

说明你没接 PostgreSQL，或者连接串错误，程序退回了本地 JSON。

### 4. 日志里说端口绑定失败

检查：

- `TEACHAGENT_PORT` 是否被填成非法值
- `Startup Command` 是否重复启动了两个进程

## 推荐你现在就用的最小配置

```env
SCM_DO_BUILD_DURING_DEPLOYMENT=1
TEACHAGENT_USE_DEFAULT_CREDENTIAL=1
TEACHAGENT_HOST=0.0.0.0
TEACHAGENT_PORT=8000
TEACHAGENT_DATABASE_URL=postgresql://...
AZURE_AI_PROJECT_ENDPOINT=https://YOUR_PROJECT.services.ai.azure.com/api/projects/proj-default
AZURE_AI_MODEL_DEPLOYMENT=gpt-4o-mini
```

如果你只是先把网页挂出去，这套就够了。
