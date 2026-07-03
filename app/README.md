# TeachAgent App MVP

这是当前本地可交互版本，既可以当浏览器里的 web app，也可以进一步包成桌面 app。

## 当前能做什么

- 切换 `知识点优先` / `题目优先` / `混合自动`
- 展示当前复习单元
- 题目答案默认隐藏
- 点击反馈按钮后，立即刷新下一轮推荐
- 读取一份示例 `student_memory_profile`，把长期画像摘要显示出来
- 展示知识树、树上例题与笔记
- 运行 `diagnosis -> 确认/反驳 -> 进入 coach`
- 在 `coach` 里做多轮聊天式追问

## 浏览器模式

在项目根目录执行：

```bash
python3 -m pip install -r app/requirements-web.txt
python3 app/server.py
```

然后打开：

```text
http://127.0.0.1:8765
```

如果你要让同一局域网内的手机访问，可以这样启动：

```bash
python3 app/server.py --host 0.0.0.0 --port 8765
```

## 网页部署

现在已经支持按网页服务部署：

- 支持 `TEACHAGENT_HOST` / `TEACHAGENT_PORT`
- 支持平台注入的 `PORT`
- 提供健康检查接口 `/healthz`
- 云端可通过 `TEACHAGENT_USE_DEFAULT_CREDENTIAL=1` 切到 `DefaultAzureCredential`

部署说明见：

```text
docs/deploy_web.md
```

## PostgreSQL 模式

先安装依赖：

```bash
python3 -m pip install -r app/requirements-web.txt
```

配置数据库 URL：

```bash
export TEACHAGENT_DATABASE_URL='postgresql://USER:PASSWORD@HOST:5432/DBNAME?sslmode=require'
```

或者在项目根目录新建 `.env`，内容可参考：

```bash
cp .env.example .env
```

初始化 schema、写入系统知识树，并把本地学生数据导入 PostgreSQL：

```bash
python3 teachagent_postgres_cli.py bootstrap --all-students
```

只检查连通性：

```bash
python3 teachagent_postgres_cli.py ping
```

完成后照常启动：

```bash
python3 app/server.py
```

启动后左侧学生卡的存储方式会显示为 `PostgreSQL`。

## 桌面模式

当前采用 `本地 server + pywebview 窗口壳` 的结构。

开发启动：

```bash
python3 app/desktop_app.py
```

如果本机还没安装 `pywebview`，它会自动退回到浏览器打开本地页面。

## 打包 macOS `.app`

先安装依赖：

```bash
python3 -m pip install -r app/requirements-desktop.txt
```

然后执行：

```bash
bash app/build_macos_app.sh
```

产物位置：

```text
dist/TeachAgent.app
```

## 当前默认数据

- review state
  - `scratch/student_annotation_merged/student_annotation_merged_review_state.json`
- memory profile
  - `scratch/teachagent_system_overview/student_memory_profile_demo.json`

## 说明

- 当前点击反馈会直接修改内存中的 session state
- 同时会把当前会话状态写到：
  - `app/data/review_state.session.json`
- diagnosis / coach 当前也是 app 进程内会话，不会持久化成长期聊天记录
- 重置按钮会回到默认样例状态
