# GitHub + Render 上线清单

这份清单的目标只有一个：把 `TeachAgent` 推到 GitHub，并在 Render 上拿到一个别人可以直接访问的公网 URL。

## 推 GitHub 前

确认这些文件不要提交：

- `.env`
- `app/data/*.session.json`
- `app/data/students/`
- `data/student_memory/student_memory_events.jsonl`
- `build/`
- `dist/`
- `scratch/mineru_runs/`
- `scratch/ocr_uploads/`

这些规则已经写进根目录 `.gitignore`。

## 建议保留在仓库里的部署文件

- `Dockerfile`
- `docker-compose.yml`
- `render.yaml`
- `app/requirements-web.txt`
- `docs/deploy_web.md`

## 推送步骤

在项目根目录执行：

```bash
git init
git add .
git commit -m "Prepare TeachAgent for Docker and Render deployment"
git branch -M main
git remote add origin <你的 GitHub 仓库地址>
git push -u origin main
```

如果仓库已经存在，只需要：

```bash
git add .
git commit -m "Prepare TeachAgent for Docker and Render deployment"
git push
```

## Render 部署

1. 登录 Render
2. 选择 `New +`
3. 选择 `Blueprint`
4. 连接你的 GitHub 仓库
5. 让 Render 读取根目录 `render.yaml`

## 在 Render 控制台补的环境变量

必须填写：

- `TEACHAGENT_DATABASE_URL`
- `AZURE_AI_PROJECT_ENDPOINT`
- `AZURE_AI_MODEL_DEPLOYMENT`

如果容器里要直接调 Azure AI，通常还需要：

- `AZURE_CLIENT_ID`
- `AZURE_TENANT_ID`
- `AZURE_CLIENT_SECRET`

## 部署完成后检查

打开：

- 首页 `/`
- 健康检查 `/healthz`

至少确认：

- `/healthz` 返回 `status=ok`
- 左侧学生卡显示 `PostgreSQL`
- 新增错题后刷新仍保留
- `诊断` 和 `引导` 不报 Azure 凭证错误

## 对“别人外网浏览器能不能访问”的判断标准

只有在 Render 部署成功，并且拿到一个 `https://...onrender.com` 的地址后，才算真正能让别人外网访问。
