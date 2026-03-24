# moldmain/backend 与 moldCost 同名代码文件差异报告

生成时间: 2026-03-21 14:53:45

## 说明

- `moldCost` 视为最新版。
- 本报告提供两种视角：
  1. “同文件名”视角：按纯文件名匹配；若能一对一匹配，则直接比较。
  2. “同相对路径 + 文件名”视角：更严格，避免 `__init__.py` 这类重名文件误配。
- 只统计常见代码/脚本文件扩展名：`.py .js .ts .tsx .jsx .java .go .rb .php .cs .cpp .c .h .hpp .vue .html .css .scss .sql .sh .bat`。
- “仅换行符差异”表示代码文本在统一换行符后完全一致，不属于实质代码差异。

## 视角一：同文件名匹配（更贴近原始需求）

| 指标 | 数量 |
| --- | ---: |
| 双方都有的文件名 | 118 |
| 可一对一匹配的文件名 | 109 |
| 存在歧义的文件名 | 9 |
| 一对一中的实质代码差异 | 58 |
| 一对一中的仅换行符差异 | 51 |

### 同文件名且存在实质代码差异的一对一文件

| 文件名 | moldmain/backend 路径 | moldCost 路径 | backend 行数 | moldCost 行数 | diff 统计 (`+新增 / -删除`) | 最新版 |
| --- | --- | --- | ---: | ---: | --- | --- |
| `audit_repository.py` | `api_gateway/repositories/audit_repository.py` | `api_gateway/repositories/audit_repository.py` | 66 | 57 | +1 / -10 | `moldCost` |
| `base_agent.py` | `agents/base_agent.py` | `agents/base_agent.py` | 309 | 52 | +13 / -270 | `moldCost` |
| `base_handler.py` | `agents/action_handlers/base_handler.py` | `agents/action_handlers/base_handler.py` | 381 | 383 | +4 / -2 | `moldCost` |
| `business_validator.py` | `shared/validators/business_validator.py` | `shared/validators/business_validator.py` | 180 | 179 | +1 / -2 | `moldCost` |
| `cad_agent.py` | `agents/cad_agent.py` | `agents/cad_agent.py` | 889 | 42 | +23 / -870 | `moldCost` |
| `chat_history_repository.py` | `api_gateway/repositories/chat_history_repository.py` | `api_gateway/repositories/chat_history_repository.py` | 437 | 428 | +1 / -10 | `moldCost` |
| `chat_logger.py` | `api_gateway/utils/chat_logger.py` | `api_gateway/utils/chat_logger.py` | 156 | 147 | +1 / -10 | `moldCost` |
| `chat_router.py` | `api_gateway/routers/chat_router.py` | `api_gateway/routers/chat_router.py` | 468 | 459 | +1 / -10 | `moldCost` |
| `completeness_validator.py` | `shared/validators/completeness_validator.py` | `shared/validators/completeness_validator.py` | 194 | 193 | +1 / -2 | `moldCost` |
| `confirm_handler.py` | `agents/confirm_handler.py` | `agents/confirm_handler.py` | 671 | 630 | +77 / -118 | `moldCost` |
| `data_modification_handler.py` | `agents/action_handlers/data_modification_handler.py` | `agents/action_handlers/data_modification_handler.py` | 694 | 1010 | +342 / -26 | `moldCost` |
| `data_view_builder.py` | `agents/data_view_builder.py` | `agents/data_view_builder.py` | 578 | 591 | +21 / -8 | `moldCost` |
| `encryption.py` | `api_gateway/utils/encryption.py` | `api_gateway/utils/encryption.py` | 120 | 113 | +1 / -8 | `moldCost` |
| `feature_recognition_handler.py` | `agents/action_handlers/feature_recognition_handler.py` | `agents/action_handlers/feature_recognition_handler.py` | 210 | 209 | +1 / -2 | `moldCost` |
| `field_validator.py` | `shared/validators/field_validator.py` | `shared/validators/field_validator.py` | 255 | 254 | +1 / -2 | `moldCost` |
| `file_router.py` | `api_gateway/routers/file_router.py` | `api_gateway/routers/file_router.py` | 275 | 200 | +1 / -76 | `moldCost` |
| `file_service.py` | `api_gateway/services/file_service.py` | `api_gateway/services/file_service.py` | 196 | 187 | +1 / -10 | `moldCost` |
| `general_chat_handler.py` | `agents/action_handlers/general_chat_handler.py` | `agents/action_handlers/general_chat_handler.py` | 182 | 181 | +2 / -3 | `moldCost` |
| `intent_recognizer.py` | `agents/intent_recognizer.py` | `agents/intent_recognizer.py` | 825 | 936 | +121 / -10 | `moldCost` |
| `intent_types.py` | `agents/intent_types.py` | `agents/intent_types.py` | 123 | 125 | +3 / -1 | `moldCost` |
| `interaction_agent.py` | `agents/interaction_agent.py` | `agents/interaction_agent.py` | 1723 | 1775 | +103 / -51 | `moldCost` |
| `interaction_models.py` | `api_gateway/models/interaction_models.py` | `api_gateway/models/interaction_models.py` | 115 | 107 | +0 / -8 | `moldCost` |
| `interaction_repository.py` | `api_gateway/repositories/interaction_repository.py` | `api_gateway/repositories/interaction_repository.py` | 164 | 155 | +1 / -10 | `moldCost` |
| `interaction_service.py` | `api_gateway/services/interaction_service.py` | `api_gateway/services/interaction_service.py` | 282 | 273 | +1 / -10 | `moldCost` |
| `interactions.py` | `api_gateway/routers/interactions.py` | `api_gateway/routers/interactions.py` | 141 | 132 | +1 / -10 | `moldCost` |
| `job_repository.py` | `api_gateway/repositories/job_repository.py` | `api_gateway/repositories/job_repository.py` | 143 | 134 | +1 / -10 | `moldCost` |
| `job_service.py` | `api_gateway/services/job_service.py` | `api_gateway/services/job_service.py` | 504 | 489 | +1 / -16 | `moldCost` |
| `jobs.py` | `api_gateway/routers/jobs.py` | `api_gateway/routers/jobs.py` | 585 | 306 | +1 / -280 | `moldCost` |
| `logging_config.py` | `shared/logging_config.py` | `shared/logging_config.py` | 557 | 399 | +23 / -181 | `moldCost` |
| `message_formatter.py` | `api_gateway/utils/message_formatter.py` | `api_gateway/utils/message_formatter.py` | 537 | 527 | +1 / -11 | `moldCost` |
| `message_persistence_manager.py` | `agents/message_persistence_manager.py` | `agents/message_persistence_manager.py` | 162 | 161 | +1 / -2 | `moldCost` |
| `message_queue.py` | `shared/message_queue.py` | `shared/message_queue.py` | 234 | 58 | +12 / -188 | `moldCost` |
| `models.py` | `shared/models.py` | `shared/models.py` | 589 | 549 | +20 / -60 | `moldCost` |
| `modification_validator.py` | `shared/validators/modification_validator.py` | `shared/validators/modification_validator.py` | 375 | 374 | +2 / -3 | `moldCost` |
| `nc_time_agent.py` | `agents/nc_time_agent.py` | `agents/nc_time_agent.py` | 986 | 77 | +46 / -955 | `moldCost` |
| `nlp_parser.py` | `agents/nlp_parser.py` | `agents/nlp_parser.py` | 2188 | 3211 | +1264 / -241 | `moldCost` |
| `orchestrator_agent.py` | `agents/orchestrator_agent.py` | `agents/orchestrator_agent.py` | 818 | 245 | +196 / -769 | `moldCost` |
| `phase2.py` | `api_gateway/routers/phase2.py` | `api_gateway/routers/phase2.py` | 69 | 58 | +0 / -11 | `moldCost` |
| `price_calculation_handler.py` | `agents/action_handlers/price_calculation_handler.py` | `agents/action_handlers/price_calculation_handler.py` | 209 | 208 | +1 / -2 | `moldCost` |
| `pricing_agent.py` | `agents/pricing_agent.py` | `agents/pricing_agent.py` | 918 | 38 | +19 / -899 | `moldCost` |
| `process_code_mapping.py` | `shared/process_code_mapping.py` | `shared/process_code_mapping.py` | 357 | 293 | +10 / -74 | `moldCost` |
| `process_rules_repository.py` | `api_gateway/repositories/process_rules_repository.py` | `api_gateway/repositories/process_rules_repository.py` | 161 | 152 | +1 / -10 | `moldCost` |
| `query_details_handler.py` | `agents/action_handlers/query_details_handler.py` | `agents/action_handlers/query_details_handler.py` | 1872 | 1879 | +56 / -49 | `moldCost` |
| `rabbitmq_client.py` | `api_gateway/utils/rabbitmq_client.py` | `api_gateway/utils/rabbitmq_client.py` | 156 | 147 | +0 / -9 | `moldCost` |
| `recalculations.py` | `api_gateway/routers/recalculations.py` | `api_gateway/routers/recalculations.py` | 100 | 36 | +2 / -66 | `moldCost` |
| `redis_client.py` | `api_gateway/utils/redis_client.py` | `api_gateway/utils/redis_client.py` | 194 | 185 | +0 / -9 | `moldCost` |
| `review_repository.py` | `api_gateway/repositories/review_repository.py` | `api_gateway/repositories/review_repository.py` | 697 | 698 | +29 / -28 | `moldCost` |
| `review_router.py` | `api_gateway/routers/review_router.py` | `api_gateway/routers/review_router.py` | 676 | 1020 | +397 / -53 | `moldCost` |
| `security.py` | `shared/security.py` | `shared/security.py` | 309 | 308 | +1 / -2 | `moldCost` |
| `snapshot_manager.py` | `api_gateway/utils/snapshot_manager.py` | `api_gateway/utils/snapshot_manager.py` | 278 | 268 | +1 / -11 | `moldCost` |
| `snapshot_repository.py` | `api_gateway/repositories/snapshot_repository.py` | `api_gateway/repositories/snapshot_repository.py` | 169 | 160 | +1 / -10 | `moldCost` |
| `start_api_gateway.sh` | `start_api_gateway.sh` | `start_api_gateway.sh` | 55 | 55 | +14 / -14 | `moldCost` |
| `test_upload_with_chat_session.py` | `examples/test_upload_with_chat_session.py` | `examples/test_upload_with_chat_session.py` | 129 | 127 | +2 / -4 | `moldCost` |
| `validators.py` | `api_gateway/utils/validators.py` | `api_gateway/utils/validators.py` | 180 | 170 | +1 / -11 | `moldCost` |
| `websocket.py` | `api_gateway/websocket.py` | `api_gateway/websocket.py` | 287 | 276 | +0 / -11 | `moldCost` |
| `websocket_router.py` | `api_gateway/routers/websocket_router.py` | `api_gateway/routers/websocket_router.py` | 147 | 138 | +2 / -11 | `moldCost` |
| `weight_price_calculation_handler.py` | `agents/action_handlers/weight_price_calculation_handler.py` | `agents/action_handlers/weight_price_calculation_handler.py` | 215 | 209 | +2 / -8 | `moldCost` |
| `weight_price_query_handler.py` | `agents/action_handlers/weight_price_query_handler.py` | `agents/action_handlers/weight_price_query_handler.py` | 665 | 664 | +3 / -4 | `moldCost` |

### 同文件名中的歧义项（需人工确认配对）

#### __init__.py

- `moldmain/backend`：
  - `__init__.py`
  - `agents/__init__.py`
  - `agents/action_handlers/__init__.py`
  - `agents/phase2/__init__.py`
  - `api_gateway/models/__init__.py`
  - `api_gateway/models/account/__init__.py`
  - `api_gateway/repositories/__init__.py`
  - `api_gateway/routers/__init__.py`
  - `api_gateway/routers/account/__init__.py`
  - `api_gateway/services/__init__.py`
  - `api_gateway/services/account/__init__.py`
  - `api_gateway/utils/account/__init__.py`
  - `consumers/__init__.py`
  - `scripts/__init__.py`
  - `scripts/cad_chaitu/__init__.py`
  - `scripts/calculate/__init__.py`
  - `scripts/feature_recognition/__init__.py`
  - `scripts/search/__init__.py`
  - `shared/__init__.py`
  - `shared/validators/__init__.py`
  - `speech_services/core/__init__.py`
  - `workers/__init__.py`
- `moldCost`：
  - `__init__.py`
  - `agents/action_handlers/__init__.py`
  - `agents/phase2/__init__.py`
  - `api_gateway/models/__init__.py`
  - `api_gateway/repositories/__init__.py`
  - `api_gateway/routers/__init__.py`
  - `api_gateway/services/__init__.py`
  - `consumers/__init__.py`
  - `shared/__init__.py`
  - `shared/validators/__init__.py`

#### auth.py

- `moldmain/backend`：
  - `api_gateway/auth.py`
  - `api_gateway/routers/account/auth.py`
- `moldCost`：
  - `api_gateway/auth.py`

#### config.py

- `moldmain/backend`：
  - `api_gateway/config.py`
  - `shared/config.py`
- `moldCost`：
  - `api_gateway/config.py`

#### database.py

- `moldmain/backend`：
  - `api_gateway/database.py`
  - `scripts/cad_chaitu/database.py`
  - `shared/database.py`
- `moldCost`：
  - `shared/database.py`

#### main.py

- `moldmain/backend`：
  - `main.py`
  - `api_gateway/main.py`
  - `mcp_services/main.py`
  - `scripts/cad_chaitu/main.py`
  - `speech_services/main.py`
- `moldCost`：
  - `api_gateway/main.py`

#### minio_client.py

- `moldmain/backend`：
  - `api_gateway/utils/minio_client.py`
  - `scripts/minio_client.py`
- `moldCost`：
  - `api_gateway/utils/minio_client.py`

#### server.py

- `moldmain/backend`：
  - `mcp_services/cad_price_search_mcp/server.py`
- `moldCost`：
  - `mcp_services/cad_parser_mcp/server.py`
  - `mcp_services/pricing_server_mcp/server.py`

#### test_nlp_parser.py

- `moldmain/backend`：
  - `examples/test_nlp_parser.py`
- `moldCost`：
  - `examples/test_nlp_parser.py`
  - `tests/test_nlp_parser.py`

#### test_validators.py

- `moldmain/backend`：
  - `examples/test_validators.py`
- `moldCost`：
  - `examples/test_validators.py`
  - `tests/test_validators.py`

## 视角二：同相对路径 + 文件名精确匹配

| 指标 | 数量 |
| --- | ---: |
| 参与比较的同相对路径代码文件 | 126 |
| 实质代码差异文件 | 68 |
| 仅换行符差异文件 | 58 |

### (root)

| 相对路径 | backend 行数 | moldCost 行数 | diff 统计 (`+新增 / -删除`) | 最新版 |
| --- | ---: | ---: | --- | --- |
| `start_api_gateway.sh` | 55 | 55 | +14 / -14 | `moldCost` |

### agents

| 相对路径 | backend 行数 | moldCost 行数 | diff 统计 (`+新增 / -删除`) | 最新版 |
| --- | ---: | ---: | --- | --- |
| `agents/action_handlers/__init__.py` | 16 | 20 | +4 / -0 | `moldCost` |
| `agents/action_handlers/base_handler.py` | 381 | 383 | +4 / -2 | `moldCost` |
| `agents/action_handlers/data_modification_handler.py` | 694 | 1010 | +342 / -26 | `moldCost` |
| `agents/action_handlers/feature_recognition_handler.py` | 210 | 209 | +1 / -2 | `moldCost` |
| `agents/action_handlers/general_chat_handler.py` | 182 | 181 | +2 / -3 | `moldCost` |
| `agents/action_handlers/price_calculation_handler.py` | 209 | 208 | +1 / -2 | `moldCost` |
| `agents/action_handlers/query_details_handler.py` | 1872 | 1879 | +56 / -49 | `moldCost` |
| `agents/action_handlers/weight_price_calculation_handler.py` | 215 | 209 | +2 / -8 | `moldCost` |
| `agents/action_handlers/weight_price_query_handler.py` | 665 | 664 | +3 / -4 | `moldCost` |
| `agents/base_agent.py` | 309 | 52 | +13 / -270 | `moldCost` |
| `agents/cad_agent.py` | 889 | 42 | +23 / -870 | `moldCost` |
| `agents/confirm_handler.py` | 671 | 630 | +77 / -118 | `moldCost` |
| `agents/data_view_builder.py` | 578 | 591 | +21 / -8 | `moldCost` |
| `agents/intent_recognizer.py` | 825 | 936 | +121 / -10 | `moldCost` |
| `agents/intent_types.py` | 123 | 125 | +3 / -1 | `moldCost` |
| `agents/interaction_agent.py` | 1723 | 1775 | +103 / -51 | `moldCost` |
| `agents/message_persistence_manager.py` | 162 | 161 | +1 / -2 | `moldCost` |
| `agents/nc_time_agent.py` | 986 | 77 | +46 / -955 | `moldCost` |
| `agents/nlp_parser.py` | 2188 | 3211 | +1264 / -241 | `moldCost` |
| `agents/orchestrator_agent.py` | 818 | 245 | +196 / -769 | `moldCost` |
| `agents/pricing_agent.py` | 918 | 38 | +19 / -899 | `moldCost` |

### api_gateway

| 相对路径 | backend 行数 | moldCost 行数 | diff 统计 (`+新增 / -删除`) | 最新版 |
| --- | ---: | ---: | --- | --- |
| `api_gateway/auth.py` | 280 | 269 | +1 / -12 | `moldCost` |
| `api_gateway/config.py` | 11 | 119 | +116 / -8 | `moldCost` |
| `api_gateway/main.py` | 238 | 204 | +46 / -80 | `moldCost` |
| `api_gateway/models/__init__.py` | 24 | 16 | +0 / -8 | `moldCost` |
| `api_gateway/models/interaction_models.py` | 115 | 107 | +0 / -8 | `moldCost` |
| `api_gateway/repositories/__init__.py` | 12 | 4 | +0 / -8 | `moldCost` |
| `api_gateway/repositories/audit_repository.py` | 66 | 57 | +1 / -10 | `moldCost` |
| `api_gateway/repositories/chat_history_repository.py` | 437 | 428 | +1 / -10 | `moldCost` |
| `api_gateway/repositories/interaction_repository.py` | 164 | 155 | +1 / -10 | `moldCost` |
| `api_gateway/repositories/job_repository.py` | 143 | 134 | +1 / -10 | `moldCost` |
| `api_gateway/repositories/process_rules_repository.py` | 161 | 152 | +1 / -10 | `moldCost` |
| `api_gateway/repositories/review_repository.py` | 697 | 698 | +29 / -28 | `moldCost` |
| `api_gateway/repositories/snapshot_repository.py` | 169 | 160 | +1 / -10 | `moldCost` |
| `api_gateway/routers/__init__.py` | 9 | 3 | +0 / -6 | `moldCost` |
| `api_gateway/routers/chat_router.py` | 468 | 459 | +1 / -10 | `moldCost` |
| `api_gateway/routers/file_router.py` | 275 | 200 | +1 / -76 | `moldCost` |
| `api_gateway/routers/interactions.py` | 141 | 132 | +1 / -10 | `moldCost` |
| `api_gateway/routers/jobs.py` | 585 | 306 | +1 / -280 | `moldCost` |
| `api_gateway/routers/phase2.py` | 69 | 58 | +0 / -11 | `moldCost` |
| `api_gateway/routers/recalculations.py` | 100 | 36 | +2 / -66 | `moldCost` |
| `api_gateway/routers/review_router.py` | 676 | 1020 | +397 / -53 | `moldCost` |
| `api_gateway/routers/websocket_router.py` | 147 | 138 | +2 / -11 | `moldCost` |
| `api_gateway/services/__init__.py` | 12 | 4 | +0 / -8 | `moldCost` |
| `api_gateway/services/file_service.py` | 196 | 187 | +1 / -10 | `moldCost` |
| `api_gateway/services/interaction_service.py` | 282 | 273 | +1 / -10 | `moldCost` |
| `api_gateway/services/job_service.py` | 504 | 489 | +1 / -16 | `moldCost` |
| `api_gateway/utils/chat_logger.py` | 156 | 147 | +1 / -10 | `moldCost` |
| `api_gateway/utils/encryption.py` | 120 | 113 | +1 / -8 | `moldCost` |
| `api_gateway/utils/message_formatter.py` | 537 | 527 | +1 / -11 | `moldCost` |
| `api_gateway/utils/minio_client.py` | 455 | 193 | +1 / -263 | `moldCost` |
| `api_gateway/utils/rabbitmq_client.py` | 156 | 147 | +0 / -9 | `moldCost` |
| `api_gateway/utils/redis_client.py` | 194 | 185 | +0 / -9 | `moldCost` |
| `api_gateway/utils/snapshot_manager.py` | 278 | 268 | +1 / -11 | `moldCost` |
| `api_gateway/utils/validators.py` | 180 | 170 | +1 / -11 | `moldCost` |
| `api_gateway/websocket.py` | 287 | 276 | +0 / -11 | `moldCost` |

### examples

| 相对路径 | backend 行数 | moldCost 行数 | diff 统计 (`+新增 / -删除`) | 最新版 |
| --- | ---: | ---: | --- | --- |
| `examples/test_upload_with_chat_session.py` | 129 | 127 | +2 / -4 | `moldCost` |

### shared

| 相对路径 | backend 行数 | moldCost 行数 | diff 统计 (`+新增 / -删除`) | 最新版 |
| --- | ---: | ---: | --- | --- |
| `shared/database.py` | 50 | 42 | +17 / -25 | `moldCost` |
| `shared/logging_config.py` | 557 | 399 | +23 / -181 | `moldCost` |
| `shared/message_queue.py` | 234 | 58 | +12 / -188 | `moldCost` |
| `shared/models.py` | 589 | 549 | +20 / -60 | `moldCost` |
| `shared/process_code_mapping.py` | 357 | 293 | +10 / -74 | `moldCost` |
| `shared/security.py` | 309 | 308 | +1 / -2 | `moldCost` |
| `shared/validators/business_validator.py` | 180 | 179 | +1 / -2 | `moldCost` |
| `shared/validators/completeness_validator.py` | 194 | 193 | +1 / -2 | `moldCost` |
| `shared/validators/field_validator.py` | 255 | 254 | +1 / -2 | `moldCost` |
| `shared/validators/modification_validator.py` | 375 | 374 | +2 / -3 | `moldCost` |

## 同相对路径中的仅换行符差异

以下文件原始字节不同，但统一为 LF 换行后内容一致：

### (root)

- `__init__.py`
- `conftest.py`

### agents

- `agents/decision_agent.py`
- `agents/phase2/__init__.py`
- `agents/phase2/sheet_line_agent.py`
- `agents/review_status.py`

### consumers

- `consumers/__init__.py`
- `consumers/review_consumer.py`

### examples

- `examples/chat_logger_usage.py`
- `examples/check_api_gateway.py`
- `examples/interaction_agent_example.py`
- `examples/logging_example.py`
- `examples/orchestrator_interaction_example.py`
- `examples/setup_test_token.py`
- `examples/sse_chat_demo.html`
- `examples/test_all_modification.py`
- `examples/test_all_process_modification.py`
- `examples/test_batch_modification.py`
- `examples/test_chat_history.py`
- `examples/test_chat_history_simple.py`
- `examples/test_completeness_check.py`
- `examples/test_confirm_timeout.py`
- `examples/test_db_connection_fix.py`
- `examples/test_display_view_flow.py`
- `examples/test_entity_extraction.py`
- `examples/test_intent_integration.py`
- `examples/test_intent_recognition_basic.py`
- `examples/test_llm_api.py`
- `examples/test_llm_fix.py`
- `examples/test_material_extraction.py`
- `examples/test_material_field_mapping.py`
- `examples/test_material_price_fix.py`
- `examples/test_multi_part_process.py`
- `examples/test_nlp_parser.py`
- `examples/test_optimistic_lock_manual.py`
- `examples/test_presigned_url.py`
- `examples/test_process_batch_modification.py`
- `examples/test_process_code_mapping.py`
- `examples/test_process_id_mapping.py`
- `examples/test_process_modification.py`
- `examples/test_process_modification_fix.py`
- `examples/test_process_part_code.py`
- `examples/test_process_rules_query.py`
- `examples/test_rabbitmq_message.py`
- `examples/test_sse_chat.py`
- `examples/test_stage2_api.py`
- `examples/test_stage2_api_mock.py`
- `examples/test_stage3_e2e.py`
- `examples/test_stage3_quick.py`
- `examples/test_subgraph_extraction.py`
- `examples/test_validators.py`

### scripts

- `scripts/monitor_redis_websocket.py`

### shared

- `shared/__init__.py`
- `shared/logging_middleware.py`
- `shared/permissions.py`
- `shared/schemas.py`
- `shared/timezone_utils.py`
- `shared/validators/__init__.py`

