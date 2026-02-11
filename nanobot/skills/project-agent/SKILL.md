---
name: project-agent
description: "处理项目相关的所有任务：代码修改、项目分析、功能开发、配置查询等。当用户询问项目信息（如查看配置、token等）或要求修改代码、分析项目、开发功能时使用。支持通过项目名自动定位目录，自动创建功能分支开发。"
---

# Project Agent Skill

## 🚀 功能

使用 `cursor-agent` 处理以下任务：
- **查询项目信息**（配置文件、token、环境变量等）
- **修改/优化代码**
- **分析项目结构和功能**
- **开发新功能**
- **编写文档**
- **代码审查**

## 📝 使用方法

### 基本用法（自动识别项目）
```bash
./scripts/cursor-agent-wrapper.sh "<你的指令>" --project <项目名>
```

### 指定工作目录
```bash
./scripts/cursor-agent-wrapper.sh "<你的指令>" --workspace <目录路径>
```

### 传统用法
```bash
cursor-agent -p --force "<你的指令>"
```

## 🎯 示例

1. **查询项目配置（通过项目名）**
```bash
./scripts/cursor-agent-wrapper.sh "查看 GitLab token 配置" --project release-task
```

2. **分析项目（通过项目名）**
```bash
./scripts/cursor-agent-wrapper.sh "总结这个项目的核心功能" --project release-task
```

3. **修改代码（通过项目名）**
```bash
./scripts/cursor-agent-wrapper.sh "优化这个函数的性能" --project ai-task-manager
```

4. **开发功能（自动创建分支）**
```bash
./scripts/cursor-agent-wrapper.sh "添加用户登录功能" --project teacher-desk
```

## ⚙️ 参数说明

- `-p`: 打印输出到控制台
- `--force`: 强制允许所有操作
- `--workspace <path>`: 指定工作目录
- `--project <name>`: 通过项目名自动查找目录（从 ~/.nanobot/projects.json 读取）

## 📌 注意事项

1. **🚨 强制分支开发规范**：
   - **任何代码变更都必须从主分支切出新的功能分支来开发**
   - 在执行任何代码修改前，必须先执行以下步骤：
     ```bash
     cd <项目目录>
     git checkout main  # 或 master
     git pull origin main  # 确保主分支最新
     git checkout -b feature/YYYYMMDD-<功能描述>
     ```
   - **绝对不允许**直接在主分支（main/master）上修改代码
   - 所有开发工作必须在功能分支上完成
   
2. **项目配置**：项目名与目录的映射存储在 `~/.nanobot/projects.json`

3. **自动分支命名**：使用 `feature/YYYYMMDD-<功能描述>` 格式
   - 例如：`feature/20260206-qrcode-tool`

4. 确保 `cursor-agent` 已正确安装

5. 对于大型项目，分析可能需要较长时间

6. 敏感操作前会提示确认