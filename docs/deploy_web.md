# TeachAgent 网页部署

这套 app 现在可以作为一个普通网页服务部署，不再只限于本机 `127.0.0.1`。

## 先决条件

- Python 3.10+
- 建议使用 PostgreSQL
- 诊断 / coach 若要在云端可用，需提供 Azure 可用凭证

## 必要环境变量

### 服务启动

```bash
TEACHAGENT_HOST=0.0.0.0
TEACHAGENT_PORT=8765
```

大多数云平台会直接注入 `PORT`，当前代码也会自动读取。

### 数据库

```bash
TEACHAGENT_DATABASE_URL='postgresql://USER:PASSWORD@HOST:5432/DBNAME?sslmode=require'
```

也支持平台常见的 `DATABASE_URL`。

如果不接 PostgreSQL，服务会退回到本地 JSON。对云平台来说，这通常意味着实例重启或重部署后数据可能丢失。

### Azure 模型调用

```bash
AZURE_AI_PROJECT_ENDPOINT='https://YOUR_PROJECT.services.ai.azure.com/api/projects/proj-default'
AZURE_AI_MODEL_DEPLOYMENT='gpt-4o-mini'
TEACHAGENT_USE_DEFAULT_CREDENTIAL='1'
```

云端推荐：

- 使用 Managed Identity
- 或使用服务主体环境变量：

```bash
AZURE_CLIENT_ID='...'
AZURE_TENANT_ID='...'
AZURE_CLIENT_SECRET='...'
```

本地开发如果已经 `az login`，可把 `TEACHAGENT_USE_DEFAULT_CREDENTIAL` 留空或设为 `0`。

注意：

- Docker 容器里通常不能直接复用你宿主机上的 `az login`
- 如果诊断 / coach / 答案整理要在容器内工作，推荐设置服务主体环境变量，或使用云平台托管身份

## 本地按网页方式运行

```bash
python3 -m pip install -r app/requirements-web.txt
python3 app/server.py --host 0.0.0.0 --port 8765
```

打开：

```text
http://127.0.0.1:8765
```

健康检查：

```text
http://127.0.0.1:8765/healthz
```

## Docker 运行

项目根目录已经提供 `Dockerfile`。

构建镜像：

```bash
docker build -t teachagent-web .
```

运行：

```bash
docker run --rm -p 8765:8765 --env-file .env teachagent-web
```

如果想长期跑，推荐直接用 `docker compose`：

```bash
cp .env.example .env
docker compose up -d --build
```

查看状态：

```bash
docker compose ps
```

查看日志：

```bash
docker compose logs -f teachagent-web
```

停止：

```bash
docker compose down
```

`docker-compose.yml` 已经挂载了这些目录，便于保留运行数据和 OCR 临时文件：

- `app/data`
- `data`
- `scratch`

## 云平台部署建议

可选两种方式：

1. 直接用 Dockerfile 部署
2. 让平台执行 `python app/server.py`

若不用 Docker，启动命令建议：

```bash
python3 -m pip install -r app/requirements-web.txt
python3 app/server.py
```

## 上线前检查

- `/healthz` 返回 `status=ok`
- 左侧学生卡显示 `PostgreSQL`
- 切换学生后数据隔离正常
- 诊断 / coach 在云端凭证下可正常调用
