"""FDE Fabric — Runtime / A2A / MCP / Task / 管控 全链路运行时。

技术栈：Python 3.11+ · FastAPI · LangGraph · SQLAlchemy(SQLite 先行)
目录结构（文档附录 §11）：
  app/api          # FastAPI：创建、查询、取消任务
  app/domain       # Run / Task / Plan / 状态转换
  app/ports        # Model / Tool / Agent / Repository 接口
  app/adapters     # storage(models/tools/agents) 具体实现
  app/planner      # 计划生成与 DAG 校验
  app/scheduler    # 就绪调度与并发
  app/executor     # local_react / remote_a2a / deterministic 执行器
  app/runtime      # LangGraph 全局状态图与运行时服务
  workers/         # 任务工人与恢复工人
  console/         # 精简控制台（纯静态）
"""

__version__ = "0.1.0"