import os
import random
import re
import time
import datetime
import logging
from rich.console import Console
from rich.prompt import Prompt, IntPrompt
from rich.panel import Panel
from rich.table import Table
from openai import OpenAI

# ----------------- 日志配置模块 -----------------
# 动态获取当前脚本所在目录的绝对路径
script_dir = os.path.dirname(os.path.abspath(__file__))
log_file_path = os.path.join(script_dir, 'game_results_of_LLM.log')

# 配置 logging 模块，将日志写入脚本所在目录的 game_results_of_LLM.log
logging.basicConfig(
    filename=log_file_path,
    level=logging.INFO,
    format='%(asctime)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
# ------------------------------------------------

console = Console()

# 游戏角色配置：3狼，3民，1女巫，1猎人，1预言家
ROLES_POOL = ["狼人", "狼人", "狼人", "平民", "平民", "平民", "女巫", "猎人", "预言家"]
PLAYERS = ["U", "A", "B", "C", "D", "E", "F", "G", "H"]

class WerewolfGame:
    def __init__(self):
        self.alive_players = PLAYERS.copy()
        self.player_roles = {}
        self.ai_llm_configs = {}
        self.llms_status_list = [] # 存储所有LLM的连接状态信息
        self.witch_save_used = False
        self.witch_poison_used = False
        self.seer_vision = [] # 记录U(人类预言家)的验人视野
        self.ai_seer_vision = {p: [] for p in PLAYERS} # 记录AI预言家的验人视野
        self.winner = None
        self.history = [] # 记录游戏公开发生的所有对话、投票与事件

    def test_llm_connection(self, url, name, key):
        """测试大模型连接状态"""
        client = OpenAI(api_key=key, base_url=url)
        try:
            with console.status(f"[cyan]正在测试模型 {name} 连接状态...[/cyan]"):
                client.chat.completions.create(
                    model=name,
                    messages=[{"role": "user", "content": "1"}],
                    max_tokens=1
                )
            return True
        except Exception:
            return False

    def setup(self):
        console.print(Panel.fit("[bold yellow]🐺 终端狼人杀：AI 深度觉醒版 🐺[/bold yellow]", border_style="red"))
        
        # 1. 配置 LLM
        num_llms = IntPrompt.ask("请输入将有几个Chat LLM参与游戏 (最多8个)", choices=[str(i) for i in range(1, 9)])
        llms = []
        for i in range(num_llms):
            console.print(f"\n[bold cyan]▶ 配置第 {i+1} 个模型[/bold cyan]")
            url = Prompt.ask("API 地址", default="https://api.deepseek.com/v1")
            name = Prompt.ask("模型名称", default="deepseek-chat")
            key = Prompt.ask("API Key", password=True)
            
            # 测试连接并立刻反馈
            is_connected = self.test_llm_connection(url, name, key)
            status_color = "green" if is_connected else "red"
            status_text = "连接成功" if is_connected else "连接失败"
            console.print(f"模型 {name} 状态: [{status_color}]{status_text}[/{status_color}]")
            
            llm_info = {"url": url, "name": name, "key": key, "online": is_connected}
            llms.append(llm_info)
            self.llms_status_list.append(llm_info)

        # 2. 分配角色
        roles = ROLES_POOL.copy()
        random.shuffle(roles)
        for i, p in enumerate(PLAYERS):
            self.player_roles[p] = roles[i]
        
        # 3. 随机分配 AI 引擎
        for p in PLAYERS[1:]:
            self.ai_llm_configs[p] = random.choice(llms)
            
        console.print(f"\n[bold green]游戏配置完成！你的代号是 [bold white]U[/bold white]，你的角色是: [bold yellow]{self.player_roles['U']}[/bold yellow][/bold green]\n")
        time.sleep(2)

    def display_hud(self):
        """在每个阶段打印持续显示的全局状态面板"""
        # 1. LLM 状态构建
        llm_lines = []
        for l in self.llms_status_list:
            color = "green" if l["online"] else "red"
            status = "Online" if l["online"] else "Offline"
            llm_lines.append(f"[{color}]• {l['name']} ({status})[/{color}]")
        llm_text = "\n".join(llm_lines)

        # 2. 玩家状态构建
        role = self.player_roles.get('U', '未知')
        is_alive = "[green]存活[/green]" if 'U' in self.alive_players else "[red]已死亡[/red]"
        alive_list = ", ".join(self.alive_players)

        # 3. 视野与队友构建
        vision_text = "无特殊视野"
        if role == "狼人":
            wolves = [p for p in PLAYERS if self.player_roles[p] == "狼人"]
            vision_text = f"[red]狼人队友: {', '.join(wolves)}[/red]"
        elif role == "预言家":
            vision_text = f"[cyan]查验记录: {', '.join(self.seer_vision) if self.seer_vision else '无'}[/cyan]"
        elif role == "女巫":
            vision_text = f"[magenta]解药: {'已使用' if self.witch_save_used else '未使用'}, 毒药: {'已使用' if self.witch_poison_used else '未使用'}[/magenta]"

        hud_content = (
            f"[bold cyan]=== LLM 引擎状态 ===[/bold cyan]\n{llm_text}\n\n"
            f"[bold cyan]=== 游戏全局信息 ===[/bold cyan]\n"
            f"我的代号: [bold white]U[/bold white] | 角色: [bold yellow]{role}[/bold yellow] | 状态: {is_alive}\n"
            f"当前存活: {alive_list}\n"
            f"视野/技能: {vision_text}"
        )
        console.print(Panel(hud_content, title="[bold magenta]🎮 游戏实时状态面板 🎮[/bold magenta]", border_style="cyan"))

    def _call_llm(self, player, system_prompt, user_prompt, require_target=False, valid_targets=None, hide_identity=False):
        config = self.ai_llm_configs[player]
        client = OpenAI(api_key=config["key"], base_url=config["url"])
        
        # 动态构建 AI 视野和全局规则
        role = self.player_roles[player]
        vision_info = ""
        if role == "狼人":
            wolves = [p for p in PLAYERS if self.player_roles[p] == "狼人"]
            vision_info = f"【你的视野】: 你的狼人队友(友方)是 {wolves}。非狼人玩家是你的敌方。其余未知。"
        elif role == "预言家":
            vision_info = f"【你的视野】: 你的历史查验记录为 {self.ai_seer_vision[player]}。找出的狼人是敌方，好人是友方。其余未知。"
        else:
            vision_info = "【你的视野】: 所有人身份未知。你需要判断哪些是友方，哪些是敌方。"

        identity_prefix = (
            f"【绝密身份】: 你的玩家代号是【{player}】，你的秘密角色是【{role}】。\n"
            f"{vision_info}\n"
            f"【核心目标】: 你需要在赢游戏的前提下帮助友方玩家，如果需要你可以适当演戏、伪装、撒谎。你的唯一目标是尽快获得游戏胜利。"
        )
        full_sys_prompt = f"{identity_prefix}\n{system_prompt}"

        # 追加全部游戏历史给 LLM
        history_context = "\n".join(self.history)
        full_user_prompt = f"【全局历史记录】:\n{history_context if history_context else '游戏刚开始'}\n\n【当前需要你作出的回应】:\n{user_prompt}"

        try:
            # 统一提示为 LLM 在思考，如果是夜晚技能阶段则脱敏角色名防止暴露
            status_msg = "[cyan]某玩家正在使用技能 (LLM 在思考...)[/cyan]" if hide_identity else f"[cyan]玩家 {player} 正在行动 (LLM 在思考...)[/cyan]"
            with console.status(status_msg):
                response = client.chat.completions.create(
                    model=config["name"],
                    messages=[
                        {"role": "system", "content": full_sys_prompt},
                        {"role": "user", "content": full_user_prompt}
                    ],
                    temperature=0.8,
                    max_tokens=300
                )
            content = response.choices[0].message.content.strip()
            
            if require_target and valid_targets:
                match = re.search(r'\[TARGET:\s*(.*?)\]', content, re.IGNORECASE)
                if match:
                    target_str = match.group(1).strip()
                    for vt in valid_targets:
                        if vt.lower() == target_str.lower() or re.search(rf'\b{vt}\b', target_str, re.IGNORECASE):
                            return vt
                return random.choice(valid_targets)
            return content
        except Exception:
            return random.choice(valid_targets) if require_target else "（陷入了沉思...）"

    def check_win(self):
        wolves = [p for p in self.alive_players if self.player_roles[p] == "狼人"]
        goods = [p for p in self.alive_players if self.player_roles[p] != "狼人"]
        if not wolves:
            self.winner = "好人阵营"
            return True
        if len(wolves) >= len(goods):
            self.winner = "狼人阵营"
            return True
        return False

    def handle_death(self, p):
        if p in self.alive_players:
            self.alive_players.remove(p)
            self.history.append(f"【系统】玩家 {p} 死亡。")
            if self.player_roles[p] == "猎人":
                console.print(f"💥 [bold red]猎人 {p} 出局，触发开枪技能！[/bold red]")
                others = [target for target in self.alive_players]
                if not others:
                    return
                if p == "U":
                    shot = Prompt.ask("你要带走谁？(严格输入代号或Pass)", choices=others + ["Pass"])
                else:
                    sys_prompt = "你作为猎人被杀，请决定是否带走一人。回复格式：[TARGET: 玩家代号] 或 [TARGET: Pass]"
                    shot = self._call_llm(p, sys_prompt, f"存活玩家: {others}", require_target=True, valid_targets=others+["Pass"])
                
                if shot != "Pass" and shot in self.alive_players:
                    console.print(f"🎯 猎人一枪带走了 {shot}！")
                    self.history.append(f"【系统】猎人 {p} 开枪带走了 {shot}！")
                    self.alive_players.remove(shot)

    def night_phase(self):
        console.print(Panel("🌙 [bold blue]天黑请闭眼[/bold blue]"))
        self.history.append("\n=== 第 N 夜 ===")
        self.display_hud()
        killed_id = None
        
        # 1. 狼人行动 (开启隐藏身份，允许刀所有人包括自己)
        wolves = [p for p in self.alive_players if self.player_roles[p] == "狼人"]
        targets = [p for p in self.alive_players] # 包含所有存活玩家
        if wolves:
            if "U" in wolves:
                killed_id = Prompt.ask(f"[狼人阶段] 你的队友是 {wolves}，你可以刀任何人（包括自己或队友），今晚杀谁？", choices=targets)
            else:
                leader = wolves[0]
                sys_prompt = f"请选择一名玩家杀害（你可以选择刀自己或队友来做身份伪装）。格式: [TARGET: 代号]"
                killed_id = self._call_llm(leader, sys_prompt, f"可选目标: {targets}", require_target=True, valid_targets=targets, hide_identity=True)

        # 2. 预言家行动 (开启隐藏身份)
        seers = [p for p in self.alive_players if self.player_roles[p] == "预言家"]
        if seers:
            s = seers[0]
            targets = [p for p in self.alive_players if p != s]
            if s == "U":
                check = Prompt.ask("[预言家阶段] 你要查验谁？", choices=targets)
                res = "狼人" if self.player_roles[check] == "狼人" else "好人"
                console.print(f"查验结果：{check} 是 {res}")
                self.seer_vision.append(f"{check}({res})")
            else:
                sys_prompt = "请查验一名玩家。格式: [TARGET: 代号]"
                ai_check = self._call_llm(s, sys_prompt, f"可选目标: {targets}", require_target=True, valid_targets=targets, hide_identity=True)
                res = "狼人" if self.player_roles.get(ai_check) == "狼人" else "好人"
                self.ai_seer_vision[s].append(f"{ai_check} 是 {res}")

        # 3. 女巫行动 (AI全面接管，开启隐藏身份)
        witches = [p for p in self.alive_players if self.player_roles[p] == "女巫"]
        dead_this_night = [killed_id] if killed_id else []
        if witches:
            w = witches[0]
            if w == "U":
                console.print(f"[女巫阶段] 今晚被杀的是: {killed_id}")
                if not self.witch_save_used and Prompt.ask("使用救药吗？(Y/N)", choices=["Y", "N"]) == "Y":
                    if killed_id in dead_this_night: dead_this_night.remove(killed_id)
                    self.witch_save_used = True
                if not self.witch_poison_used and Prompt.ask("使用毒药吗？(Y/N)", choices=["Y", "N"]) == "Y":
                    p_target = Prompt.ask("毒杀谁？", choices=[p for p in self.alive_players if p != killed_id])
                    dead_this_night.append(p_target)
                    self.witch_poison_used = True
            else:
                if killed_id and not self.witch_save_used:
                    sys_prompt = "你是女巫。今晚有人被杀。你要使用解药救他吗？回复格式：[TARGET: Y] 或 [TARGET: N]"
                    use_save = self._call_llm(w, sys_prompt, f"今晚被杀的是 {killed_id}。使用解药吗？", require_target=True, valid_targets=["Y", "N"], hide_identity=True)
                    if use_save == "Y":
                        if killed_id in dead_this_night: dead_this_night.remove(killed_id)
                        self.witch_save_used = True
                        
                if not self.witch_poison_used:
                    p_targets = [p for p in self.alive_players if p != w] + ["Pass"]
                    sys_prompt = "你要使用毒药吗？如果不用请回复Pass，如果要毒人请回复目标代号。格式: [TARGET: 代号] 或 [TARGET: Pass]"
                    poison = self._call_llm(w, sys_prompt, f"可选毒杀目标: {p_targets}", require_target=True, valid_targets=p_targets, hide_identity=True)
                    if poison != "Pass" and poison in p_targets:
                        dead_this_night.append(poison)
                        self.witch_poison_used = True

        console.print("\n☀️ [bold yellow]天亮了[/bold yellow]")
        if not dead_this_night:
            console.print("昨晚是平安夜。")
            self.history.append("【系统】昨晚是平安夜。")
        else:
            for d in list(set(dead_this_night)):
                console.print(f"💀 [bold red]玩家 {d}[/bold red] 死了。")
            for d in list(set(dead_this_night)):
                self.handle_death(d)

    def day_phase(self):
        console.print(Panel("[bold green]白天发言与投票[/bold green]"))
        self.history.append("\n=== 白天发言环节 ===")
        self.display_hud()
        
        # 发言
        for p in self.alive_players:
            if p == "U":
                speech = Prompt.ask(f"轮到你发言了(U)")
                self.history.append(f"【发言】 U: {speech}")
            else:
                sys_prompt = "现在是白天发言。请分析局势并伪装或指控。不要说自己是AI。你的发言应该基于上面的历史记录展开。"
                speech = self._call_llm(p, sys_prompt, "请输出你的发言:")
                console.print(f"[bold magenta]玩家 {p}[/bold magenta]: {speech}")
                self.history.append(f"【发言】 {p}: {speech}")
            time.sleep(0.5)

        self.history.append("\n=== 白天投票环节 ===")
        # 投票
        votes = {p: 0 for p in self.alive_players}
        for p in self.alive_players:
            v_targets = [t for t in self.alive_players if t != p] + ["Pass"]
            if p == "U":
                v = Prompt.ask("你要投票给谁？(严格输入代号或Pass)", choices=v_targets)
            else:
                sys_prompt = "投票环节。投给你认为最像敌对阵营的人以获取胜利。格式: [TARGET: 代号] 或 [TARGET: Pass]"
                v = self._call_llm(p, sys_prompt, f"请从候选人中投票: {v_targets}", require_target=True, valid_targets=v_targets)
            
            console.print(f"🗳️  {p} -> {v}")
            self.history.append(f"【投票】 {p} 投给了 {v}")
            if v != "Pass": votes[v] += 1
        
        # 结算投票
        if any(votes.values()):
            max_v = max(votes.values())
            winners = [k for k, v in votes.items() if v == max_v]
            if len(winners) == 1:
                console.print(f"💀 [bold red]玩家 {winners[0]}[/bold red] 被最高票处决。")
                self.handle_death(winners[0])
            else:
                console.print("平票，无人被处决。")
                self.history.append("【系统】平票，无人被处决。")

    def save_stats(self):
        """使用 logging 模块保存并在界面显示 LLM 比赛胜率与存活率统计"""
        model_stats = {}
        # 初始化模型统计
        for config in self.ai_llm_configs.values():
            m_name = config["name"]
            if m_name not in model_stats:
                model_stats[m_name] = {"total": 0, "win": 0, "survive": 0}
        
        # 统计每个AI玩家的结果
        for p, config in self.ai_llm_configs.items():
            m_name = config["name"]
            role = self.player_roles[p]
            # 判断阵营是否胜利
            is_win = (self.winner == "狼人阵营" and role == "狼人") or (self.winner == "好人阵营" and role != "狼人")
            is_survive = p in self.alive_players
            
            model_stats[m_name]["total"] += 1
            if is_win:
                model_stats[m_name]["win"] += 1
            if is_survive:
                model_stats[m_name]["survive"] += 1

        # 界面显示统计表格
        stats_table = Table(title="大模型表现统计 (本次游戏结算)")
        stats_table.add_column("模型名称", style="cyan")
        stats_table.add_column("出场数", style="white")
        stats_table.add_column("胜率", style="yellow")
        stats_table.add_column("存活率", style="green")

        try:
            # 记录基础游戏信息到日志
            logging.info(f"=== 新的对局结束 ===")
            logging.info(f"Winner Faction: {self.winner}")
            
            for m_name, stats in model_stats.items():
                win_rate = (stats["win"] / stats["total"]) * 100
                survive_rate = (stats["survive"] / stats["total"]) * 100
                
                # 添加到富文本表格
                stats_table.add_row(m_name, str(stats["total"]), f"{win_rate:.2f}%", f"{survive_rate:.2f}%")
                
                # 使用 logging 写入统计数据
                logging.info(f"Model: {m_name: <20} | Instances: {stats['total']} | Win Rate: {win_rate:6.2f}% | Survival Rate: {survive_rate:6.2f}%")
                
            console.print(stats_table)
            console.print(f"\n[bold green]✅ 游戏模型统计已通过 logging 保存至 {log_file_path}[/bold green]")
        except Exception as e:
            console.print(f"[bold red]❌ 保存日志失败: {e}[/bold red]")

    def run(self):
        self.setup()
        while not self.winner:
            self.night_phase()
            if self.check_win(): break
            self.day_phase()
            if self.check_win(): break
        
        console.print(Panel(f"[bold red]🏆 游戏结束！{self.winner} 获胜！ 🏆[/bold red]"))
        # 展示结果表
        res_table = Table(title="玩家大揭秘")
        res_table.add_column("代号", style="cyan")
        res_table.add_column("角色", style="yellow")
        res_table.add_column("使用的 LLM 引擎", style="magenta")
        res_table.add_column("状态", style="green")
        
        for p in PLAYERS:
            status = "[green]存活[/green]" if p in self.alive_players else "[red]死亡[/red]"
            engine = "（人类玩家）" if p == "U" else self.ai_llm_configs[p]["name"]
            res_table.add_row(p, self.player_roles[p], engine, status)
        
        console.print(res_table)
        
        # 结算并写入统计信息，控制台展示图表
        self.save_stats()
        
        console.print("\n[dim]程序已休眠，将在 86400 秒后自动关闭。你可以直接关闭窗口退出。[/dim]")
        time.sleep(86400) # 休眠86400秒

if __name__ == "__main__":
    WerewolfGame().run()
