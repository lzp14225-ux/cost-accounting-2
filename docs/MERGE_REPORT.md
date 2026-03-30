# mold_main 合并说明

## 目录来源

- `mold_main/backend/agents`、`api_gateway`、`consumers`、`shared`
  - 基线来自 `moldCost`
  - 原因：这是你明确说明的最新主后端，聊天、审核、文件、作业主链路都在这里
- `mold_main/backend/workers`、`scripts`、`api_gateway/database.py`
  - 来自 `mold_cost-main`
  - 原因：这里保留了报价、图纸拆分、报表、权重价格和 worker 能力
- `mold_main/backend/app`、`config`
  - 来自 `mold_cost_account_python`
  - 原因：账号、工艺规则、价格项、会话管理都在这里

## 重复代码处理

- 主业务同名代码优先保留 `moldCost`
- `/api/v1/jobs/*` 保留 `moldCost` 的主业务路由
- `/api/jobs/{job_id}` 保留 `mold_cost_account_python` 的轻量详情查询，供前端历史会话使用
- 账号接口通过 `api_gateway/routers/account_router.py` 接入统一 FastAPI 网关

## 当前统一结果

- 新统一后端目录：`mold_main/backend`
- 对外统一端口：`8211`
- 主启动入口：`mold_main/backend/main.py`
- 统一环境文件：`mold_main/backend/.env`

## 前端需要同步的配置

- `VITE_API_BASE_URL` 指向 `http://<你的IP>:8211`
- `VITE_AUTH_BASE_URL` 也指向 `http://<你的IP>:8211`

## 现阶段说明

- 这次已经把公开网关端口收成一个
- RabbitMQ、Redis、MCP 仍然是内部依赖端口，不影响前端统一接入
- `mold_cost-main` 的部分 worker/MCP 仍依赖内部服务协同，目录已并入，但完整联调还需要按你的运行环境继续收尾
