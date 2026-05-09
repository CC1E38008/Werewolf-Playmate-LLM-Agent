
# 🐺 终端狼人杀：AI 深度觉醒版 (LLM Agent Werewolf)

![License](https://img.shields.io/badge/License-MIT-blue.svg)
![Python](https://img.shields.io/badge/Python-3.8+-green.svg)

这是一个基于终端的纯文本狼人杀游戏，由人类玩家与多个大语言模型（LLM）共同参与。本项目利用深度定制的 System Prompt，赋予 AI 真实的隐藏身份、视野以及逻辑推理能力，让 LLM 可以在游戏中“思考、伪装、撒谎甚至背叛”。

<img width="610" height="461" alt="e537d14ee261500d96a980f5dd9c7e38" src="https://github.com/user-attachments/assets/f312cf9e-161a-4041-b6af-e797df667875" />


 ✨ 核心特性

- 🤖 多模型混合竞技：支持同时接入最多 8 个不同的 LLM（兼容 OpenAI API 格式，如 DeepSeek、ChatGPT 等），你可以观察不同模型在欺诈与逻辑推理上的能力差异。
- 📈 智能体能力基准：可直观对比各家大语言模型的逻辑推理与伪装能力，系统将自动统计并记录不同 LLM 的胜率与存活率。
- 🎭 完整角色体系：9人标准局配置（3狼人、3平民、1预言家、1女巫、1猎人）。
- 🕶️ 隐藏身份与视野：AI 的提示词由系统动态生成，狼人知道队友，预言家知道查验记录，AI 必须在有限视野下伪装自己。
- 📊 战绩自动统计：内置 `logging` 系统，每次游戏结束后自动结算，生成各个大模型的“出场数、胜率与存活率”统计面板，并保存至本地日志。
- 💻 极致终端体验：基于 `rich` 库构建的实时 HUD 状态面板与高亮文本，提供极佳的沉浸式游玩体验。


🎮 游玩指南
- 配置引擎：运行脚本后，系统会提示输入参与游戏的 LLM 数量。你需要准备好兼容 OpenAI 格式的 API URL 和 API Key（例如 DeepSeek 的 https://api.deepseek.com/v1） 。所有的 Key 仅在你的本地内存中运行，不会被上传或保存。
- 你的身份：你是玩家代号 U，系统会随机为你分配一个身份。
- 黑夜阶段：根据你的身份执行动作（狼人刀人、女巫救/毒、预言家查验）。如果是 AI 拿到神职或狼人，它们会在后台静默思考并作出决定。
- 白天阶段：分析局势，通过终端输入你的发言。AI 也会根据历史发言记录进行推理和辩论。
- 投票处决：票选出你认为的狼人。

📝 日志与数据统计
游戏过程中的所有胜负结算数据会自动保存在脚本同目录下的 game_results_of_LLM.log 文件中。你可以借此分析哪一款大语言模型是真正的“逻辑大师”或“伪装大师”。

🤝 贡献指南
欢迎提交 Pull Request 或发布 Issue 来完善这个游戏！你可以尝试：
- 增加新的角色（如守卫、丘比特、白痴）。
- 优化 AI 的 System Prompt，让其发言更具“人味”。
- 接入不同的 API 调用方式（如本地部署的 Ollama）。

📄 开源协议
本项目基于 MIT License 开源。请自由享受代码的乐趣！


🛠️ 安装与运行

```bash
1. 克隆仓库
Bash
git clone https://github.com/CC1E38008/Werewolf-Playmate-Agent.git
cd Werewolf-Playmate-Agent
chmod +x Werewolf_Playmate_Agent_Ver_1.py
"""

```bash
2. 安装依赖
建议使用虚拟环境（venv或conda），然后安装必要的 Python 库：
Bash
pip install -r requirements.txt
"""

```bash
3. 开始游戏
Bash
python Werewolf_Playmate_Agent_Ver_1.py
"""

