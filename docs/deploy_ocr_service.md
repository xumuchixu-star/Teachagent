# TeachAgent 独立 OCR 服务部署

这个服务是给 TeachAgent 主站单独拆出来的 OCR 层。

作用很简单：

- 接收图片 / PDF
- 调 `MinerU`
- 返回 OCR 原始文本和产物摘要

主站继续负责：

- OCR 文本拆题
- 回填到诊断 / 引导 / 错题本
- 学生交互和数据库写入

## 一、为什么单独拆

因为主站现在跑在 Azure App Service，上面直接装 `MinerU` 不稳：

- 依赖重
- 首次模型下载慢
- 冷启动长
- 会拖慢主站

所以更合理的是：

- 主站继续放在 Azure App Service
- OCR 放到单独一台机器 / 单独一个容器

## 二、仓库里现在已有的文件

- `ocr_service/server.py`
  - 独立 OCR HTTP 服务
- `ocr_service/requirements.txt`
  - OCR 依赖
- `ocr_service/Dockerfile`
  - 容器化部署入口
- `scripts/run_mineru_extract.py`
  - 复用现有 MinerU wrapper

## 三、接口

### 1. 健康检查

```text
GET /healthz
```

返回示例：

```json
{
  "status": "ok",
  "provider": "MinerU",
  "available": true,
  "message": "独立 OCR 服务已就绪。"
}
```

### 2. OCR 提取

```text
POST /extract
Content-Type: multipart/form-data
```

表单字段：

- `file`
  - 图片或 PDF
- `target`
  - 可选，`wrongbook / diagnosis / coach`
  - 目前主要用于 run name 标记

返回示例：

```json
{
  "filename": "demo.png",
  "summary": {
    "run_dir": "...",
    "generated_files": ["..."],
    "preview_text_path": "..."
  },
  "preview_text": "OCR 文本..."
}
```

## 四、本机直接运行

前提：

- 你的本机已经有可用 `MinerU`
- 也就是下面二选一：
  - 仓库里存在 `.venv_mineru/bin/mineru`
  - 或者系统 `PATH` 里有 `mineru`

启动：

```bash
python3 ocr_service/server.py --host 0.0.0.0 --port 8890
```

测试：

```bash
curl http://127.0.0.1:8890/healthz
```

## 五、Docker 部署

在仓库根目录执行：

```bash
docker build -f ocr_service/Dockerfile -t teachagent-ocr:latest .
```

启动：

```bash
docker run -d \
  --name teachagent-ocr \
  -p 8890:8890 \
  -v $(pwd)/scratch:/app/scratch \
  -v $(pwd)/ocr-model-cache:/app/model-cache \
  teachagent-ocr:latest
```

说明：

- `scratch`
  - 保存 OCR 产物
- `ocr-model-cache`
  - 保存 MinerU / Torch / HuggingFace / ModelScope 模型缓存
- 第一次启动后，第一次真正 OCR 时通常会下载较大模型

健康检查：

```bash
curl http://127.0.0.1:8890/healthz
```

## 六、可配环境变量

OCR 服务自身支持这些环境变量：

```env
OCR_SERVICE_HOST=0.0.0.0
OCR_SERVICE_PORT=8890
OCR_SERVICE_OUTPUT_ROOT=/app/scratch/mineru_runs
OCR_SERVICE_MINERU_BACKEND=pipeline
OCR_SERVICE_MINERU_LANG=ch
OCR_SERVICE_ENABLE_FORMULA=1
OCR_SERVICE_ENABLE_TABLE=0
MINERU_MODEL_SOURCE=modelscope
HF_HOME=/app/model-cache/huggingface
MODELSCOPE_CACHE=/app/model-cache/modelscope
TORCH_HOME=/app/model-cache/torch
```

默认就够用，不一定都要手配。

## 七、让 TeachAgent 主站接这个服务

主站只要加两个环境变量：

```env
TEACHAGENT_OCR_SERVICE_URL=http://你的OCR服务域名或IP:8890
TEACHAGENT_OCR_SERVICE_TIMEOUT_SECONDS=120
```

例如：

```env
TEACHAGENT_OCR_SERVICE_URL=http://123.123.123.123:8890
```

如果 OCR 服务挂了，主站会返回远端 OCR 错误，不会静默无响应。

## 八、Azure 主站怎么配

如果你的 TeachAgent 主站继续放在 Azure App Service：

1. 打开 `Environment variables`
2. 增加：

```env
TEACHAGENT_OCR_SERVICE_URL=http://你的OCR服务地址:8890
TEACHAGENT_OCR_SERVICE_TIMEOUT_SECONDS=120
```

3. 保存
4. 重启主站

之后主站会自动从“本地 MinerU 模式”切成“远端 OCR 服务模式”。

## 九、当前最推荐的实际部署方式

对你现在最稳的是：

1. TeachAgent 主站继续放 Azure App Service
2. OCR 服务单独放一台 Linux 机器或单独容器
3. 先确认 OCR 服务 `healthz` 通
4. 再把 `TEACHAGENT_OCR_SERVICE_URL` 配到主站

## 十、已知限制

- 当前独立 OCR 服务只负责 OCR，不负责拆题逻辑
- 多图导入仍由主站逐张调用，再在主站里合并
- 第一次 OCR 很可能比较慢，因为要下模型
- 如果你把 OCR 服务放到很弱的机器上，首轮响应会比较长
