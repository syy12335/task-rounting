# task-router-graph

内部任务路由项目。单配置文件运行，支持两套后端：

- `aliyun`：阿里云百炼
- `sglang`：本地 SGLang（OpenAI-compatible）

## 30 秒上手

```bash
pip install -r requirements.txt
export MODEL_PROVIDER=aliyun            # 或 sglang
export API_KEY_Qwen=<your_key>          # aliyun 需要
export SGLANG_API_KEY=EMPTY             # sglang 需要
python scripts/run_case.py --config configs/graph.yaml --case data/cases/case_01.json
```

## 运行命令

单 case：

```bash
python scripts/run_case.py --config configs/graph.yaml --case data/cases/case_01.json
```

批量：

```bash
python scripts/run_cases.py --config configs/graph.yaml
```

可视化：

```bash
streamlit run app/streamlit_app.py
```

## Provider 切换规则

配置文件：`configs/graph.yaml`

- 默认 provider：`model.provider`
- 环境变量覆盖：`MODEL_PROVIDER`
- provider 详情：`model.providers.<name>`

常用切换：

```bash
# 走阿里云百炼
export MODEL_PROVIDER=aliyun
export API_KEY_Qwen=<your_key>

# 走本地 sglang
export MODEL_PROVIDER=sglang
export SGLANG_API_KEY=EMPTY
```

## 本地 SGLang 启动（示例）

```bash
source /opt/conda/bin/activate task-routing-clean
python -m sglang.launch_server \
  --model-path /model/default/Qwen3.5-4B \
  --served-model-name qwen35-4b \
  --host 127.0.0.1 \
  --port 30000 \
  --api-key EMPTY
```

健康检查：

```bash
curl -s http://127.0.0.1:30000/v1/models -H "Authorization: Bearer EMPTY"
```

## Notebook（测 sglang 模型效果）

- `notebooks/sglang_model_eval.ipynb`
- 支持覆盖：`SGLANG_BASE_URL`、`SGLANG_API_KEY`、`SGLANG_MODEL`

## 常见问题

1. 报错 `Missing required environment variable`
- 按 provider 补齐 key：
- `aliyun` -> `API_KEY_Qwen`
- `sglang` -> `SGLANG_API_KEY`

2. sglang 返回 401
- 请求没带 `Authorization: Bearer <SGLANG_API_KEY>`

3. 固定默认 provider
- 改 `configs/graph.yaml` 的 `model.provider`

## 代码位置

- 入口：`scripts/run_case.py`、`scripts/run_cases.py`
- 配置：`configs/graph.yaml`
- 核心：`src/task_router_graph/`
- 设计文档：`docs/environment.md`、`docs/design.md`、`docs/data_format.md`
