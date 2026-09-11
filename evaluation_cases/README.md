# IRO_agent Industrial Diagnosis Benchmark Cases

本目录为工业软件智能诊断套件 (IRO_agent) 的标准基准评测数据集。

## 目录分层规范

1. **`dev/` (开发集)**
   - 开放给本地开发与 Coding Agent，用于算法调优、Next-Best-Evidence Planner 策略迭代与工具链验证。
   - 涵盖系统应用报错、PLC信号边界、机器人调度、配置漂移、数据库状态机异常等典型工业场景。

2. **`regression/` (回归集)**
   - 用于拦截历史已修复缺陷重新劣化，包含高难度“反直觉案例” (如用户主观误导、时序非因果、历史遗留日志噪声、真假物理升级、观测缺口等)。
   - 回归集必须保持 100% 通过率硬门槛。

3. **`blind/` (外部盲测集)**
   - **严格禁止提交至本仓库！**
   - 仅能存在于外部离线私有目录或独立评测仓，通过命令行隔离挂载运行：
     ```bash
     iro-agent eval external --dataset "D:\IRO_eval_private"
     ```

## 运行评测命令

```bash
# 运行全部开发集
iro-agent eval dev

# 仅运行 PLC 类别开发集
iro-agent eval dev --category plc

# 运行回归集
iro-agent eval regression

# 运行指定单一案例
iro-agent eval regression --case counter_01_user_misleading
```
