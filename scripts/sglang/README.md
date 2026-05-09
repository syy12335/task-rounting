# SGLang Scripts

这个目录放本地 SGLang 服务相关入口：

- `start.sh`：启动本地 SGLang 服务。
- `status.sh`：查看服务状态。
- `stop.sh`：停止服务。
- `sglang_model_eval.ipynb`：通过 OpenAI-compatible `/v1` 接口快速检查模型效果、JSON 输出和基础延迟。

常用环境变量：

```bash
export SGLANG_BASE_URL=http://127.0.0.1:30000/v1
export SGLANG_MODEL=qwen3-4b
export SGLANG_API_KEY=EMPTY
export SGLANG_MODEL_PATH=path/to/local/model
```

常用启动方式：

```bash
./scripts/sglang/start.sh

# 显式指定 conda 环境；不传时优先使用当前 CONDA_DEFAULT_ENV
./scripts/sglang/start.sh --conda-env task-routing-online

# 覆盖环境变量并继续透传 SGLang 原生参数
./scripts/sglang/start.sh \
  --base-url http://127.0.0.1:30000/v1 \
  --model qwen3-4b \
  --model-path path/to/local/model \
  -- --tp-size 1

# 只查看解析后的配置，不启动服务
./scripts/sglang/start.sh --dry-run
```

兼容旧变量：`SGLANG_HOST`、`SGLANG_PORT`、`SGLANG_SERVED_MODEL_NAME`。新旧变量同时存在时，新口径优先。
