"""
============================================================
🐺 终端狼人杀：AI 深度觉醒版 v7.3 — 正式发布版
============================================================
v7.2 → v7.3:
  [遗言修复] AI遗言prompt注入死因(狼杀/票死)，不再混淆自己的死亡方式
  [发言tokens] 发言/遗言/竞选 max_tokens=3000，技能调用保持300
"""

import os
import random
import re
import time
import datetime
import logging
import textwrap
from collections import Counter
from rich.console import Console
from rich.prompt import Prompt, IntPrompt
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.live import Live
from rich.layout import Layout
from rich.spinner import Spinner
from openai import OpenAI

# ----------------- 日志配置模块 -----------------
try:
    script_dir = os.path.dirname(os.path.abspath(__file__))
except NameError:
    script_dir = os.getcwd()
log_file_path = os.path.join(script_dir, 'game_results_of_LLM.log')

logging.basicConfig(
    filename=log_file_path,
    level=logging.INFO,
    format='%(asctime)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
# ------------------------------------------------

console = Console()

# ─────────────────────────────────────────────
# 游戏基础配置
# ─────────────────────────────────────────────
ROLES_POOL = ["狼人", "狼人", "狼人", "平民", "平民", "平民", "女巫", "猎人", "预言家"]
PLAYERS = ["U", "A", "B", "C", "D", "E", "F", "G", "H"]

# ─────────────────────────────────────────────
# 🎨 视觉配置 — 玩家专属颜色 + emoji
# ─────────────────────────────────────────────
PLAYER_COLORS = {
    "U": "bold white",
    "A": "red",
    "B": "green",
    "C": "yellow",
    "D": "blue",
    "E": "magenta",
    "F": "cyan",
    "G": "bright_yellow",
    "H": "bright_blue",
}
PLAYER_EMOJIS = {
    "U": "👤",
    "A": "🔴",
    "B": "🟢",
    "C": "🟡",
    "D": "🔵",
    "E": "🟣",
    "F": "💠",
    "G": "🟠",
    "H": "🧊",
}
ROLE_EMOJIS = {
    "狼人": "🐺",
    "平民": "🌾",
    "女巫": "🧪",
    "猎人": "🔫",
    "预言家": "🔮",
}

ASCII_NIGHT = r"""
                    ╭─────────────────────╮
                    │  🌙  月 黑 风 高    │
                    │  🐺 狼 群 出 没 🐺  │
                    ╰─────────────────────╯
                          /\
                         /  \
                        /_oo_\
                       ( 嗷~  )
                        ¯¯¯¯¯¯
"""

ASCII_DAWN = r"""
         ☀  ️
  ╔═══════════════════════╗
  ║    天   亮   了       ║
  ╚═══════════════════════╝
"""


def get_player_label(player: str) -> str:
    """获取玩家带颜色+emoji的标签文本 (Rich markup)"""
    color = PLAYER_COLORS.get(player, "white")
    emoji = PLAYER_EMOJIS.get(player, "?")
    return f"{emoji} [{color}]【{player}】[/{color}]"


def get_role_emoji(role: str) -> str:
    """获取角色对应emoji"""
    return ROLE_EMOJIS.get(role, "❓")


# ─────────────────────────────────────────────
# 🔧 思考内容过滤
# ─────────────────────────────────────────────
THINK_TAG_PATTERN = re.compile(
    r'<think(?:ing)?\s*>.*?</think(?:ing)?\s*>', re.IGNORECASE | re.DOTALL
)
THINK_XML_PATTERN = re.compile(
    r'<thinking\s*>.*?</thinking\s*>', re.IGNORECASE | re.DOTALL
)
THINK_PATTERN = re.compile(r'</?think(?:ing)?>', re.IGNORECASE)


def strip_thinking(content: str) -> str:
    if not content:
        return content
    content = THINK_TAG_PATTERN.sub('', content)
    content = THINK_XML_PATTERN.sub('', content)
    content = THINK_PATTERN.sub('', content)
    return content.strip()


def extract_reasoning_content(response) -> str:
    try:
        msg = response.choices[0].message
        rc = getattr(msg, 'reasoning_content', None)
        if rc:
            return rc
        if hasattr(msg, 'model_extra'):
            rc = msg.model_extra.get('reasoning_content')
            if rc:
                return rc
    except Exception:
        pass
    return ""


def sanitize_history_for_ai(history: list, human_player: str = "U") -> list:
    sanitized = []
    for entry in history:
        if "【绝密身份】" in entry or "【你的视野】" in entry:
            continue
        if "【核心目标】" in entry:
            continue
        sanitized.append(entry)
    return sanitized


def truncate_history(history: list, max_entries: int = 50) -> list:
    if len(history) <= max_entries:
        return history
    truncated = history[-max_entries:]
    summary = f"【系统】……（更早的历史记录已省略，共 {len(history) - max_entries} 条）……"
    return [summary] + truncated


# ═══════════════════════════════════════════════════
class WerewolfGame:
    """狼人杀游戏主类 (v7.3 正式发布版)"""

    def __init__(self):
        self.alive_players = PLAYERS.copy()
        self.player_roles = {}
        self.ai_llm_configs = {}
        self.llms_status_list = []
        self.witch_save_used = False
        self.witch_poison_used = False
        self.seer_vision = []
        self.ai_seer_vision = {p: [] for p in PLAYERS}
        self.winner = None
        self.history = []
        self.tie_count = 0
        self.night_number = 0
        self.day_number = 0
        self.human_alive = True
        self.fast_forward = False  # 观战快进模式
        self.sheriff = None            # 当前警长 (玩家代号 或 None)
        self.sheriff_election_done = False
        self.night_zero_done = False   # 第0夜是否已完成
        self.first_death_spoken = False  # 首夜死者遗言是否已触发

    # ═══════════════════════════════════════════════
    # 🌙 第0夜 — 预言家单独查验（无狼刀/无女巫）
    # ═══════════════════════════════════════════════
    def night_zero(self):
        """第0夜: 仅预言家查验，不杀人、不用药。为警长竞选提供信息基础。"""
        self.night_zero_done = True
        u_role = self.player_roles.get("U", "")

        # ── 仅预言家看到查验界面，其他人看到模糊提示 ──
        if u_role == "预言家":
            console.print()
            console.print(Panel(
                "[bold blue]🌙 第 0 夜 — 预言家单独查验[/bold blue]\n"
                "[dim]仅预言家行动，无狼刀，无女巫技能[/dim]",
                border_style="blue"
            ))
        else:
            console.print()
            console.print(Panel(
                "[bold blue]🌙 第 0 夜[/bold blue]\n"
                "[dim]所有人闭眼...（预言家单独查验，此信息仅预言家可见）[/dim]",
                border_style="blue"
            ))

        seers = [p for p in self.alive_players if self.player_roles[p] == "预言家"]
        if not seers:
            if u_role == "预言家":
                console.print("[dim]无存活的预言家。[/dim]")
            return

        s = seers[0]
        check_targets = [p for p in self.alive_players if p != s]

        if s == "U":
            check = self._human_input(
                "[预言家] 第0夜免费查验，你要查验谁？",
                choices=check_targets
            )
            res = "🐺 狼人" if self.player_roles[check] == "狼人" else "🌾 好人"
            console.print(Panel(
                f"{get_player_label(check)} 的身份是：[bold]{res}[/bold]",
                border_style="cyan",
                title="🔮 查验结果"
            ))
            self.seer_vision.append(f"{check}({res})")
        else:
            sys_prompt = "第0夜，你可以查验一名玩家。格式: [TARGET: 代号]"
            ai_check = self._call_llm(
                s, sys_prompt,
                f"可选目标: {check_targets}",
                require_target=True,
                valid_targets=check_targets,
                hide_identity=True,
                max_tokens=300
            )
            if ai_check and ai_check in check_targets:
                res = "狼人" if self.player_roles.get(ai_check) == "狼人" else "好人"
                self.ai_seer_vision[s].append(f"{ai_check} 是 {res}")
            else:
                fallback = random.choice(check_targets)
                res = "狼人" if self.player_roles.get(fallback) == "狼人" else "好人"
                self.ai_seer_vision[s].append(f"{fallback} 是 {res}")

        time.sleep(1.0)
        if u_role == "预言家":
            console.print("[dim]第0夜结束，进入警长竞选...[/dim]\n")
        else:
            console.print("[dim]天亮了，进入警长竞选...[/dim]\n")
        time.sleep(0.5)

    # ═══════════════════════════════════════════════
    # 🎖️ 警长竞选
    # ═══════════════════════════════════════════════
    def sheriff_election(self):
        """警长竞选 — 上警/发言/退水/投票"""
        console.print()
        console.print(Panel(
            "[bold yellow]🎖️ 警长竞选环节 🎖️[/bold yellow]\n"
            "[dim]上警玩家发表竞选演说 → 退水 → 在警下玩家投票选出警长[/dim]",
            border_style="yellow"
        ))
        self.history.append("\n=== 警长竞选 ===")
        self.display_hud()

        # ═══════════════════════════════════════════
        # Phase 1: 上警 / 在警下 声明
        # ═══════════════════════════════════════════
        console.print("\n[bold]📋 第一阶段: 上警声明[/bold]")
        candidates = []
        voters = []

        for p in self.alive_players:
            if p == "U":
                choice = self._human_input(
                    f"{get_player_label('U')} 是否上警竞选警长？(Y/N)",
                    choices=["Y", "N"]
                )
            else:
                role = self.player_roles[p]
                if role == "预言家":
                    hint = "你作为预言家，必须上警抢夺警徽打出警徽流，否则狼人拿警徽好人大劣。建议上警。"
                elif role == "狼人":
                    hint = "你可以选择上警悍跳预言家抢夺警徽，或在警下投票支持队友。策略自定。"
                elif role == "平民":
                    hint = "你可以上警为预言家挡刀或分析局势，或在警下投票。策略自定。"
                elif role == "女巫":
                    hint = "你有双药在手，可以上警分享信息，或在警下隐藏身份。策略自定。"
                elif role == "猎人":
                    hint = "你可以上警带队分析，或在警下隐藏身份。策略自定。"
                else:
                    hint = "请根据你的角色和阵营决定是否上警。"

                sys_prompt = (
                    f"现在是警长竞选环节。{hint}\n"
                    f"回复格式：[TARGET: Y] 表示上警，[TARGET: N] 表示在警下。"
                )
                choice = self._call_llm(
                    p, sys_prompt,
                    "是否上警竞选警长？",
                    require_target=True,
                    valid_targets=["Y", "N"],
                    hide_identity=True,
                    max_tokens=300
                )

            label = get_player_label(p)
            if choice == "Y":
                candidates.append(p)
                console.print(f"  {label} → [bold yellow]🎖️ 上警[/bold yellow]")
                self.history.append(f"【上警】 {p} 参加警长竞选")
            else:
                voters.append(p)
                console.print(f"  {label} → [dim]在警下[/dim]")
                self.history.append(f"【上警】 {p} 在警下")

        # Edge case: 无人上警
        if not candidates:
            console.print(Panel(
                "[dim]无人上警，本轮无警长。[/dim]",
                border_style="grey50"
            ))
            self.history.append("【系统】无人上警，无警长产生。")
            self.sheriff_election_done = True
            return

        # Edge case: 仅1人上警 → 自动当选
        if len(candidates) == 1:
            self.sheriff = candidates[0]
            console.print(Panel(
                f"🎖️ {get_player_label(candidates[0])} 是唯一候选人，自动当选警长！",
                border_style="yellow"
            ))
            self.history.append(f"【系统】{candidates[0]} 自动当选警长。")
            self.sheriff_election_done = True
            return

        # ═══════════════════════════════════════════
        # Phase 2: 竞选发言 (随机顺序)
        # ═══════════════════════════════════════════
        console.print(f"\n[bold]🗣️ 第二阶段: 竞选发言 ({len(candidates)}人)[/bold]")
        random.shuffle(candidates)

        for p in candidates:
            console.print()
            if p == "U":
                speech = self._human_input(
                    f"🎤 你的竞选发言 ({get_player_label('U')})",
                    allow_commands=False
                )
            else:
                role = self.player_roles[p]
                if role == "预言家":
                    hint = "报出你的查验信息和警徽流。"
                elif role == "狼人":
                    hint = "悍跳预言家，报出虚假查验和警徽流，抢夺警徽。"
                else:
                    hint = "分析局势，说明你为何适合当警长。"
                sys_prompt = (
                    f"现在是竞选发言环节。{hint}\n"
                    f"你的发言应该说服在警下的玩家投票给你。注意伪装和策略。"
                )
                speech = self._call_llm(p, sys_prompt, "请发表你的竞选演说:")

            bubble = self._speech_bubble(p, speech)
            bubble.title = f"🎤 {get_player_label(p)} [竞选发言]"
            console.print(bubble)
            self.history.append(f"【竞选发言】 {p}: {speech}")
            time.sleep(0.5)

        # ═══════════════════════════════════════════
        # Phase 3: 退水
        # ═══════════════════════════════════════════
        console.print(f"\n[bold]💧 第三阶段: 退水声明[/bold]")
        withdrew = []
        for p in candidates[:]:  # iterate copy
            if p == "U":
                if self._human_input(
                    f"{get_player_label('U')} 是否退水？(Y/N)",
                    choices=["Y", "N"]
                ) == "Y":
                    candidates.remove(p)
                    withdrew.append(p)
                    console.print(f"  {get_player_label(p)} → [dim]退水[/dim]")
            else:
                sys_prompt = (
                    "听完了所有候选人的发言。根据局势判断，你是否要退水（退出竞选）？"
                    "回复格式：[TARGET: Y] 或 [TARGET: N]"
                )
                choice = self._call_llm(
                    p, sys_prompt,
                    "是否退水？",
                    require_target=True,
                    valid_targets=["Y", "N"],
                    max_tokens=300
                )
                if choice == "Y":
                    candidates.remove(p)
                    withdrew.append(p)
                    console.print(f"  {get_player_label(p)} → [dim]退水[/dim]")
            time.sleep(0.2)

        if withdrew:
            self.history.append(f"【退水】 {', '.join(withdrew)} 退出竞选。")

        if not candidates:
            console.print(Panel(
                "[dim]所有候选人退水，本轮无警长。[/dim]",
                border_style="grey50"
            ))
            self.history.append("【系统】所有候选人退水，无警长产生。")
            self.sheriff_election_done = True
            return

        if len(candidates) == 1:
            self.sheriff = candidates[0]
            console.print(Panel(
                f"🎖️ 其他候选人退水，{get_player_label(candidates[0])} 自动当选警长！",
                border_style="yellow"
            ))
            self.history.append(f"【系统】{candidates[0]} 经退水后自动当选警长。")
            self.sheriff_election_done = True
            return

        # ═══════════════════════════════════════════
        # Phase 4: 投票
        # ═══════════════════════════════════════════
        console.print(f"\n[bold]🗳️ 第四阶段: 警长投票[/bold]")
        console.print(f"候选人: {', '.join([get_player_label(c) for c in candidates])}")

        # 如果所有玩家都上警且无人退水 → 全体投票
        if not voters:
            voters = [p for p in self.alive_players]
            console.print("[dim]全员上警，所有玩家参与投票。[/dim]")

        election_votes = {c: 0 for c in candidates}
        for v in voters:
            if v == "U":
                vote = self._human_input(
                    f"{get_player_label('U')} 投票给谁？",
                    choices=candidates
                )
            else:
                sys_prompt = (
                    "请投票给最适合当警长的候选人。考虑发言内容和阵营利益。"
                    "格式: [TARGET: 代号]"
                )
                vote = self._call_llm(
                    v, sys_prompt,
                    f"候选人: {candidates}",
                    require_target=True,
                    valid_targets=candidates,
                    max_tokens=300
                )
            election_votes[vote] += 1
            console.print(f"  {get_player_label(v)} → {get_player_label(vote)}")
            self.history.append(f"【警长投票】 {v} 投给了 {vote}")
            time.sleep(0.2)

        # ── 结果 ──
        max_v = max(election_votes.values())
        winners = [c for c, v in election_votes.items() if v == max_v]

        if len(winners) == 1:
            self.sheriff = winners[0]
            console.print(Panel(
                f"🎖️ [bold yellow]{get_player_label(winners[0])} 当选警长！[/bold yellow]\n"
                f"[dim]得票: {max_v} 票 | 特权: 归票权 + 1.5票 + 警徽流[/dim]",
                border_style="yellow"
            ))
            self.history.append(f"【系统】{winners[0]} 以 {max_v} 票当选警长。")
        else:
            # 平票 → 无人当选（简化处理）
            console.print(Panel(
                f"[dim]平票 ({max_v}票)，无人当选警长。[/dim]",
                border_style="grey50"
            ))
            self.history.append(f"【系统】警长投票平票，无警长产生。")

        self.sheriff_election_done = True

    # ═══════════════════════════════════════════════
    # 🎨 UI 工具方法
    # ═══════════════════════════════════════════════
    def _speech_bubble(self, player: str, text: str) -> Panel:
        """生成发言气泡面板"""
        color = PLAYER_COLORS.get(player, "white")
        label = get_player_label(player)
        return Panel(text, title=label, border_style=color, padding=(0, 1))

    def _show_vote_result(self, votes: dict, executed: str = None):
        """显示投票结果 — 柱状图 + 表格"""
        if not votes:
            return

        max_v = max(votes.values()) if max(votes.values()) > 0 else 1
        bar_width = 25

        table = Table(title="📊 投票结果", border_style="cyan")
        table.add_column("玩家", style="cyan", width=6)
        table.add_column("票数", style="yellow", width=4)
        table.add_column("票型", style="white")
        table.add_column("标记", style="red", width=6)

        for player, count in sorted(votes.items(), key=lambda x: -x[1]):
            bar_len = int(count / max_v * bar_width) if max_v > 0 else 0
            bar = "█" * bar_len + "░" * (bar_width - bar_len)
            marker = "🎯 被放逐" if player == executed else ""
            label = get_player_label(player)
            count_str = f"{count:.1f}" if count != int(count) else str(int(count))
            table.add_row(label, count_str, bar, marker)

        console.print(table)

    def _show_night_banner(self):
        """夜晚 ASCII 艺术"""
        if self.night_number <= 2:  # 前两夜展示，之后省略节省空间
            console.print(Text(ASCII_NIGHT, style="dim blue"))

    def _show_dawn_banner(self):
        """天亮 ASCII 艺术"""
        if self.night_number <= 2:
            console.print(Text(ASCII_DAWN, style="bold yellow"))

    def _show_night_section(self, title: str, emoji: str, color: str):
        """夜晚阶段小节标题"""
        console.print(f"\n{emoji} [bold {color}]{'━' * 40}[/bold {color}]")
        console.print(f"{emoji} [bold {color}]{title}[/bold {color}]")
        console.print(f"{emoji} [bold {color}]{'━' * 40}[/bold {color}]\n")

    def _show_dead_notice(self):
        """人类玩家死亡后的观战提示"""
        if not self.human_alive:
            console.print(Panel(
                "[dim]👻 你已死亡，正在观战中...[/dim]\n"
                "[dim]输入 /status 查看游戏状态 | /alive 查看存活玩家[/dim]",
                border_style="grey50",
                title="[dim]观战模式[/dim]"
            ))

    def _show_mini_hud(self):
        """迷你存活面板（观战模式用）"""
        alive_table = Table(title="存活玩家", border_style="grey50", show_header=False)
        alive_table.add_column(style="white")
        for p in self.alive_players:
            label = get_player_label(p)
            alive_table.add_row(label)
        console.print(alive_table)

    def _show_death_reveal(self, player: str, cause: str, reveal_role: bool = False):
        """死亡播报。reveal_role=True 时揭晓身份（仅猎人开枪），否则身份未知。"""
        role = self.player_roles.get(player, "???")
        emoji = get_role_emoji(role)
        label = get_player_label(player)

        cause_texts = {
            "wolf": "被狼人撕碎了喉咙",
            "poison": "口吐白沫——女巫的毒药",
            "vote": "被村民投票处决",
            "hunter": "被猎人一枪带走",
            "forced": "成了平票僵局的牺牲品",
            "unknown": "意外身亡",
        }
        cause_text = cause_texts.get(cause, "死亡")

        if reveal_role:
            identity_line = f"{emoji} 身份揭晓：[bold yellow]{role}[/bold yellow]"
            border = "yellow"
        else:
            identity_line = "[dim]身份未知[/dim]"
            border = "red"

        console.print(Panel(
            f"{label}\n"
            f"💀 [bold red]{cause_text}[/bold red]\n"
            f"{identity_line}",
            border_style=border,
            padding=(1, 2)
        ))

    def _draw_divider(self, text: str = "", style: str = "dim"):
        """画一条分隔线"""
        width = 50
        if text:
            console.print(f"[{style}]── {text} {'─' * (width - len(text) - 4)}[/{style}]")
        else:
            console.print(f"[{style}]{'─' * width}[/{style}]")

    # ═══════════════════════════════════════════════
    # ⌨️ 命令系统
    # ═══════════════════════════════════════════════
    def _handle_command(self, cmd: str) -> bool:
        """
        处理 / 命令。返回 True 表示命令已处理(继续提示)，False 表示未识别。
        """
        cmd = cmd.strip().lower()

        if cmd in ("/help", "/h"):
            console.print(Panel(
                "[bold]可用命令:[/bold]\n"
                "  [cyan]/status[/cyan]   — 显示完整游戏状态面板\n"
                "  [cyan]/alive[/cyan]    — 显示存活玩家列表\n"
                "  [cyan]/last[/cyan]     — 显示上一轮发言摘要\n"
                "  [cyan]/help[/cyan]     — 显示此帮助\n"
                "  [cyan]/fast[/cyan]     — 切换快进模式(观战用)",
                title="❓ 帮助",
                border_style="cyan"
            ))
            return True

        elif cmd in ("/status", "/s"):
            self.display_hud()
            return True

        elif cmd in ("/alive", "/a"):
            self._show_mini_hud()
            return True

        elif cmd in ("/last", "/l"):
            # 提取最近几轮发言
            speeches = [h for h in self.history if h.startswith("【发言】")]
            recent = speeches[-6:] if len(speeches) >= 6 else speeches
            if recent:
                console.print(Panel(
                    "\n".join(recent),
                    title="💬 最近发言",
                    border_style="magenta"
                ))
            else:
                console.print("[dim]尚无发言记录[/dim]")
            return True

        elif cmd == "/fast":
            self.fast_forward = not self.fast_forward
            status = "[green]已开启[/green]" if self.fast_forward else "[yellow]已关闭[/yellow]"
            console.print(f"⚡ 快进模式 {status}")
            return True

        return False

    def _human_input(self, prompt_text: str, choices: list = None, allow_commands: bool = True) -> str:
        """
        人类玩家输入（带命令支持）。

        如果用户输入 / 开头的命令，处理命令后重新提示。
        如果 choices 提供，手动验证输入。
        """
        while True:
            if allow_commands:
                console.print("[dim]┃ 💡 /status  /alive  /last  /help  /fast[/dim]")

            raw = Prompt.ask(prompt_text)

            # 命令拦截
            if allow_commands and raw.strip().startswith('/'):
                handled = self._handle_command(raw.strip())
                if handled:
                    continue  # 命令已处理，重新提示
                else:
                    console.print(f"[red]未知命令: {raw}。输入 /help 查看可用命令。[/red]")
                    continue

            # choices 验证
            if choices:
                if raw in choices:
                    return raw
                # 模糊匹配
                raw_upper = raw.strip().upper()
                for c in choices:
                    if c.upper() == raw_upper:
                        return c
                console.print(f"[red]无效输入。可选: {', '.join(choices)}[/red]")
                continue

            return raw

    # ═══════════════════════════════════════════════
    # 赛前演出
    # ═══════════════════════════════════════════════
    def _pre_game_animation(self):
        """赛前洗牌→分配→唤醒动画"""
        steps = [
            ("🎭 正在洗牌...", 1.0),
            ("🎭 正在分配身份...", 1.5),
            ("🎭 正在唤醒 AI 灵魂...", 2.0),
            ("🐺 狼人杀即将开始！", 1.0),
        ]
        for msg, delay in steps:
            console.print(f"  {msg}")
            time.sleep(delay)
        console.print()

    # ═══════════════════════════════════════════════
    # 配置阶段
    # ═══════════════════════════════════════════════
    def test_llm_connection(self, url: str, name: str, key: str) -> bool:
        client = OpenAI(api_key=key, base_url=url)
        try:
            with console.status(f"[cyan]正在测试模型 {name} 连接状态...[/cyan]"):
                client.chat.completions.create(
                    model=name,
                    messages=[{"role": "user", "content": "1"}],
                    max_tokens=1,
                    timeout=30
                )
            return True
        except Exception:
            return False

    def setup(self):
        console.print(Panel.fit(
            "[bold yellow]🐺 终端狼人杀 v7.3 — 正式发布版 🐺[/bold yellow]\n"
            "[dim]AI 深度觉醒 | 玩家专属配色 | 发言气泡 | 投票可视化 | 观战模式[/dim]",
            border_style="red"
        ))

        # ── 1. 配置 LLM ──
        num_llms = IntPrompt.ask(
            "请输入将有几个Chat LLM参与游戏 (最多8个)",
            choices=[str(i) for i in range(1, 9)]
        )
        llms = []
        for i in range(num_llms):
            console.print(f"\n[bold cyan]▶ 配置第 {i+1} 个模型[/bold cyan]")
            url = Prompt.ask("API 地址", default="https://api.deepseek.com/v1")
            name = Prompt.ask("模型名称", default="deepseek-chat")
            key = Prompt.ask("API Key", password=True)

            is_connected = self.test_llm_connection(url, name, key)
            status_color = "green" if is_connected else "red"
            status_text = "连接成功" if is_connected else "连接失败"
            console.print(f"模型 {name} 状态: [{status_color}]{status_text}[/{status_color}]")

            llm_info = {"url": url, "name": name, "key": key, "online": is_connected, "idx": i + 1}
            llms.append(llm_info)
            self.llms_status_list.append(llm_info)

        # ── 2. 赛前动画 ──
        self._pre_game_animation()

        # ── 3. 分配角色 ──
        roles = ROLES_POOL.copy()
        random.shuffle(roles)
        for i, p in enumerate(PLAYERS):
            self.player_roles[p] = roles[i]

        # ── 4. 均衡分配 AI 引擎 ──
        llm_usage = Counter()
        for p in PLAYERS[1:]:
            # 对所有 LLM 取最小使用次数（含未入选的默认 0），而非只看 Counter 已有的
            min_count = min(llm_usage.get(l["idx"], 0) for l in llms)
            candidates = [l for l in llms if llm_usage.get(l["idx"], 0) == min_count]
            chosen = random.choice(candidates)
            self.ai_llm_configs[p] = chosen
            llm_usage[chosen["idx"]] += 1

        alloc_table = Table(title="🔗 AI 模型分配结果")
        alloc_table.add_column("玩家", style="cyan")
        alloc_table.add_column("模型", style="yellow")
        for p in PLAYERS[1:]:
            cfg = self.ai_llm_configs[p]
            alloc_table.add_row(
                get_player_label(p),
                f"{cfg['name']} (#{cfg['idx']})"
            )
        console.print(alloc_table)

        # 分配统计摘要
        dist_summary = []
        for l in llms:
            count = llm_usage.get(l["idx"], 0)
            dist_summary.append(f"{l['name']} (#{l['idx']}): {count}人")
        console.print(f"[dim]分配统计: {' | '.join(dist_summary)}[/dim]")

        console.print(
            f"\n[bold green]✅ 游戏配置完成！[/bold green]\n"
            f"你的代号: {get_player_label('U')}\n"
            f"你的角色: [bold yellow]{self.player_roles['U']} "
            f"{get_role_emoji(self.player_roles['U'])}[/bold yellow]\n"
        )
        time.sleep(2)

    # ═══════════════════════════════════════════════
    # HUD 显示模块
    # ═══════════════════════════════════════════════
    def display_hud(self):
        """全局状态面板（v4.0 增强版 — 含 LLM 状态 + 玩家配色图例）"""
        # ── LLM 状态 ──
        llm_lines = []
        for l in self.llms_status_list:
            color = "green" if l["online"] else "red"
            status = "● Online" if l["online"] else "○ Offline"
            llm_lines.append(f"[{color}]{status}[/{color}]  {l['name']}")
        llm_text = "\n".join(llm_lines)

        # ── 玩家状态 ──
        role = self.player_roles.get('U', '未知')
        role_emoji = get_role_emoji(role)
        is_alive = "[green]● 存活[/green]" if self.human_alive else "[red]✕ 已死亡[/red]"
        alive_list = ", ".join(self.alive_players)

        # ── 视野 ──
        vision_text = "无特殊视野"
        if role == "狼人":
            wolves = [p for p in PLAYERS if self.player_roles[p] == "狼人"]
            wolves_labels = [get_player_label(p) for p in wolves]
            vision_text = f"[red]狼人队友: {', '.join(wolves_labels)}[/red]"
        elif role == "预言家":
            records = self.seer_vision if self.seer_vision else ['无']
            vision_text = f"[cyan]查验记录: {', '.join(records)}[/cyan]"
        elif role == "女巫":
            vision_text = (
                f"[magenta]解药: {'[green]✓ 可用[/green]' if not self.witch_save_used else '[red]✕ 已用[/red]'}, "
                f"毒药: {'[green]✓ 可用[/green]' if not self.witch_poison_used else '[red]✕ 已用[/red]'}[/magenta]"
            )

        # ── 警长 ──
        sheriff_info = ""
        if self.sheriff:
            sheriff_info = f"\n🎖️ 警长: {get_player_label(self.sheriff)}  |  特权: 归票权 + 1.5票 + 警徽流"

        # ── 玩家配色图例 ──
        legend_parts = [get_player_label(p) for p in self.alive_players]
        dead_parts = [f"[dim]{get_player_label(p)}[/dim]" for p in PLAYERS if p not in self.alive_players]
        legend = " | ".join(legend_parts + dead_parts)

        hud_content = (
            f"[bold cyan]═══ LLM 引擎状态 ═══[/bold cyan]\n{llm_text}\n\n"
            f"[bold cyan]═══ 游戏全局信息 ═══[/bold cyan]\n"
            f"代号: {get_player_label('U')}  |  角色: [bold yellow]{role} {role_emoji}[/bold yellow]  |  {is_alive}\n"
            f"存活: {alive_list}\n"
            f"视野: {vision_text}{sheriff_info}\n\n"
            f"[bold cyan]═══ 玩家图例 ═══[/bold cyan]\n{legend}"
        )
        console.print(Panel(
            hud_content,
            title=f"[bold magenta]🎮 游戏状态 — 第 {self.night_number} 夜 / 第 {self.day_number} 天[/bold magenta]",
            border_style="cyan"
        ))

    # ═══════════════════════════════════════════════
    # LLM 调用模块
    # ═══════════════════════════════════════════════
    def _call_llm(
        self, player: str, system_prompt: str, user_prompt: str,
        require_target: bool = False, valid_targets: list = None,
        hide_identity: bool = False, timeout: int = 120,
        max_tokens: int = 3000
    ):
        config = self.ai_llm_configs[player]
        client = OpenAI(api_key=config["key"], base_url=config["url"])

        role = self.player_roles[player]
        vision_info = ""
        if role == "狼人":
            wolves = [p for p in PLAYERS if self.player_roles[p] == "狼人"]
            vision_info = (
                f"【你的视野】: 你的狼人队友(友方)是 {wolves}。"
                f"非狼人玩家是你的敌方。其余未知。"
            )
        elif role == "预言家":
            checked_players = set()
            records = []
            for entry in self.ai_seer_vision[player]:
                records.append(entry)
                name = entry.split(" ")[0] if entry else ""
                if name:
                    checked_players.add(name)
            records_display = records if records else ['暂无查验记录']
            vision_info = (
                f"【你的视野】: 你的历史查验记录为 {records_display}。"
                f"找出的狼人是敌方，好人是友方。其余未知。\n"
                f"【重要】: 你已经查验过的玩家有 {list(checked_players)}，"
                f"不要重复查验他们，应该查验新的玩家。"
            )
        else:
            vision_info = "【你的视野】: 所有人身份未知。你需要判断哪些是友方，哪些是敌方。"

        identity_prefix = (
            f"【绝密身份】: 你的玩家代号是【{player}】，你的秘密角色是【{role}】。\n"
            f"{vision_info}\n"
            f"【核心目标】: 你需要在赢游戏的前提下帮助友方玩家，"
            f"如果需要你可以适当演戏、伪装、撒谎。你的唯一目标是尽快获得游戏胜利。\n"
            f"【重要规则】: 绝对不要在你的输出中暴露你的身份、角色、或任何推理过程。"
            f"你的发言必须像一个真正的人类玩家，不要使用'作为AI'、'我认为我应该'这类暴露身份的措辞。"
        )
        full_sys_prompt = f"{identity_prefix}\n{system_prompt}"

        sanitized = sanitize_history_for_ai(self.history, human_player="U")
        truncated = truncate_history(sanitized, max_entries=50)
        history_context = "\n".join(truncated)
        full_user_prompt = (
            f"【全局历史记录】:\n{history_context if history_context else '游戏刚开始'}\n\n"
            f"【当前需要你作出的回应】:\n{user_prompt}"
        )

        try:
            label = get_player_label(player)
            if hide_identity:
                status_msg = "[cyan]某玩家正在使用技能...[/cyan]"
            else:
                status_msg = f"[cyan]{label} 正在思考...[/cyan]"

            with console.status(status_msg):
                response = client.chat.completions.create(
                    model=config["name"],
                    messages=[
                        {"role": "system", "content": full_sys_prompt},
                        {"role": "user", "content": full_user_prompt}
                    ],
                    temperature=0.8,
                    max_tokens=max_tokens,
                    timeout=timeout
                )

            raw_content = response.choices[0].message.content or ""
            reasoning = extract_reasoning_content(response)
            if reasoning:
                logging.debug(f"[{player}] Reasoning: {reasoning[:200]}...")

            content = strip_thinking(raw_content)

            if not content:
                if require_target and valid_targets:
                    return random.choice(valid_targets)
                return "（陷入了沉思...）"

            if require_target and valid_targets:
                match = re.search(r'\[TARGET:\s*(.*?)\]', content, re.IGNORECASE)
                if match:
                    target_str = match.group(1).strip()
                    for vt in valid_targets:
                        if vt.upper() == target_str.upper():
                            return vt
                        if re.search(rf'\b{vt}\b', target_str, re.IGNORECASE):
                            return vt

                fallback = random.choice(valid_targets)
                logging.info(
                    f"[{player}] TARGET 解析失败, content='{content[:100]}...', "
                    f"兜底随机选择: {fallback}"
                )
                return fallback

            return content

        except Exception as e:
            logging.error(f"[{player}] LLM 调用异常: {e}")
            config["online"] = False
            if require_target and valid_targets:
                return random.choice(valid_targets)
            return "（陷入了沉思...）"

    # ═══════════════════════════════════════════════
    # 胜负判定
    # ═══════════════════════════════════════════════
    def check_win(self) -> bool:
        wolves = [p for p in self.alive_players if self.player_roles[p] == "狼人"]
        goods = [p for p in self.alive_players if self.player_roles[p] != "狼人"]
        if not wolves:
            self.winner = "好人阵营"
            return True
        if len(wolves) >= len(goods):
            self.winner = "狼人阵营"
            return True
        return False

    # ═══════════════════════════════════════════════
    # 死亡处理
    # ═══════════════════════════════════════════════
    def handle_death(self, p: str, cause: str = "unknown"):
        if p not in self.alive_players:
            return

        self.alive_players.remove(p)

        # ── 💬 遗言判定 ──
        # 标准规则: 首夜狼杀有遗言 + 白天被投票放逐有遗言
        # 被毒杀、被猎人带走、系统强制放逐 → 无遗言
        allow_last_words = False
        if cause == "wolf" and not self.first_death_spoken:
            allow_last_words = True
            self.first_death_spoken = True
        elif cause == "vote":
            allow_last_words = True

        if allow_last_words:
            label = get_player_label(p)
            console.print(Panel(
                f"💬 [bold yellow]遗言环节 — {label}[/bold yellow]",
                border_style="yellow"
            ))
            if p == "U":
                last_speech = self._human_input(
                    "📝 请留下遗言:",
                    allow_commands=False
                )
            else:
                death_reason = {"wolf": "你被狼人杀害", "vote": "你被投票放逐"}.get(cause, "你即将死亡")
                sys_prompt = (
                    f"{death_reason}，这是你最后的发言机会。请留下遗言。"
                    "你可以揭露信息、指认狼人、或给队友提示。"
                    "不要暴露你作为AI的身份。"
                )
                last_speech = self._call_llm(p, sys_prompt, "请说出你的遗言:")
            bubble = self._speech_bubble(p, last_speech)
            bubble.title = f"💬 {label} [遗言]"
            console.print(bubble)
            self.history.append(f"【遗言】 {p}: {last_speech}")

        # ── 判定是否亮身份：仅猎人不被毒时亮身份证明开枪权 ──
        reveal_role = (
            self.player_roles.get(p) == "猎人" and cause != "poison"
        )

        # ── 死亡播报 ──
        self._show_death_reveal(p, cause, reveal_role=reveal_role)

        cause_map = {
            "wolf": "被狼人杀害",
            "poison": "被女巫毒杀",
            "vote": "被投票放逐",
            "hunter": "被猎人带走",
            "forced": "被系统强制放逐",
            "unknown": "死亡"
        }
        cause_text = cause_map.get(cause, "死亡")
        if reveal_role:
            self.history.append(f"【系统】玩家 {p} {cause_text}（身份：{self.player_roles[p]}）。")
        else:
            self.history.append(f"【系统】玩家 {p} {cause_text}。")

        if p == "U":
            self.human_alive = False
            if Prompt.ask(
                "\n⚡ 是否开启快进模式？(Y/N)",
                choices=["Y", "N"],
                default="N"
            ) == "Y":
                self.fast_forward = True
                console.print("[green]✓ 快进模式已开启[/green]\n")

        # ── 🎖️ 警徽流：警长死亡时传递警徽 ──
        if self.sheriff == p:
            console.print(f"\n🎖️ [bold yellow]警长 {get_player_label(p)} 死亡！传递警徽...[/bold yellow]")
            others = [t for t in self.alive_players]
            if others:
                if p == "U":
                    heir = self._human_input(
                        "🎖️ 警徽传给谁？(输入代号)",
                        choices=others
                    )
                else:
                    sys_prompt = (
                        "你是警长，即将死亡。请选择一位玩家传递警徽。\n"
                        "警徽传递会公开信息——如果你是预言家，传警徽可以暗示你的查验结果。\n"
                        "回复格式：[TARGET: 代号]"
                    )
                    heir = self._call_llm(
                        p, sys_prompt,
                        f"可选对象: {others}",
                        require_target=True,
                        valid_targets=others,
                        max_tokens=300
                    )
                self.sheriff = heir
                console.print(f"🎖️ 警徽已传给 {get_player_label(heir)}！")
                self.history.append(f"【系统】警徽从 {p} 传给 {heir}。")
            else:
                self.sheriff = None
                console.print("[dim]无存活玩家可传递警徽。[/dim]")
                self.history.append("【系统】警徽无人可传，收回。")

        # ── 猎人开枪 ──
        if self.player_roles[p] == "猎人":
            if cause == "poison":
                console.print(Panel(
                    f"🔇 [dim]{get_player_label(p)} 被毒杀，无法亮身份，不能开枪。[/dim]",
                    border_style="grey50"
                ))
                self.history.append(f"【系统】{p} 被毒杀，猎人技能失效。")
                return

            # 猎人亮身份，证明合法开枪权
            console.print(Panel(
                f"🔫 [bold yellow]{get_player_label(p)} 亮出猎人身份！触发开枪！[/bold yellow]",
                border_style="yellow"
            ))
            others = [t for t in self.alive_players]
            if not others:
                return

            if p == "U":
                shot = self._human_input(
                    "🔫 你要带走谁？(输入代号或 Pass)",
                    choices=others + ["Pass"],
                    allow_commands=False
                )
            else:
                sys_prompt = (
                    "你作为猎人被杀，请决定是否带走一人。"
                    "回复格式：[TARGET: 玩家代号] 或 [TARGET: Pass]"
                )
                shot = self._call_llm(
                    p, sys_prompt,
                    f"存活玩家: {others}",
                    require_target=True,
                    valid_targets=others + ["Pass"],
                    max_tokens=300
                )

            if shot != "Pass" and shot in self.alive_players:
                console.print(f"🎯 猎人一枪带走了 {get_player_label(shot)}！")
                # 被猎人带走 → 不亮身份
                self._show_death_reveal(shot, "hunter", reveal_role=False)
                self.history.append(
                    f"【系统】猎人 {p} 开枪带走了 {shot}。"
                )
                self.alive_players.remove(shot)
                if shot == "U":
                    self.human_alive = False

                # ── 🔧 修复: 猎人带走警长 → 警徽随机传递 ──
                if self.sheriff == shot:
                    remaining = [t for t in self.alive_players]
                    if remaining:
                        heir = random.choice(remaining)
                        self.sheriff = heir
                        console.print(
                            f"🎖️ 被带走的警长无法指定继承人，"
                            f"警徽随机传给 {get_player_label(heir)}"
                        )
                        self.history.append(
                            f"【系统】警长 {shot} 被猎人带走，"
                            f"警徽随机传给 {heir}。"
                        )
                    else:
                        self.sheriff = None
                        console.print("[dim]警徽无人可传，收回。[/dim]")
                        self.history.append("【系统】警徽无人可传，收回。")

    # ═══════════════════════════════════════════════
    # 夜晚阶段
    # ═══════════════════════════════════════════════
    def night_phase(self):
        self.night_number += 1
        night_header = f"\n=== 第 {self.night_number} 夜 ==="

        console.print()
        console.print(Panel(
            f"🌙 [bold blue]第 {self.night_number} 夜 — 天黑请闭眼[/bold blue]",
            border_style="blue"
        ))
        self._show_night_banner()
        self.history.append(night_header)
        self.display_hud()
        self._show_dead_notice()
        if not self.human_alive:
            self._show_mini_hud()

        killed_id = None
        is_first_night = (self.night_number == 1)
        delay = 0.3 if (self.fast_forward or not self.human_alive) else 1.5

        # ═══════════════════════════════════════════
        # 1. 狼人行动
        # ═══════════════════════════════════════════
        u_role = self.player_roles.get("U", "")
        if u_role == "狼人":
            self._show_night_section("狼人出击", "🐺", "red")
        else:
            console.print(f"\n[dim]夜色深沉，远处传来低沉的嗥叫...[/dim]")

        wolves = [p for p in self.alive_players if self.player_roles[p] == "狼人"]
        targets = [p for p in self.alive_players]

        if wolves:
            if "U" in wolves:
                wolves_labels = [get_player_label(p) for p in wolves]
                console.print(f"你的狼人队友: {' '.join(wolves_labels)}")
                killed_id = self._human_input(
                    "今晚杀谁？(输入代号，可选择刀自己/队友)",
                    choices=targets
                )
            else:
                leader = wolves[0]
                sys_prompt = (
                    "请选择一名玩家杀害（你可以选择刀自己或队友来做身份伪装）。"
                    "格式: [TARGET: 代号]"
                )
                killed_id = self._call_llm(
                    leader, sys_prompt,
                    f"可选目标: {targets}",
                    require_target=True,
                    valid_targets=targets,
                    hide_identity=True,
                    max_tokens=300
                )
            if killed_id and u_role == "狼人":
                console.print("🐺 狼人选择了目标...")
        elif u_role == "狼人":
            console.print("[dim]没有存活的狼人。[/dim]")

        if not self.fast_forward:
            time.sleep(delay)

        # ═══════════════════════════════════════════
        # 2. 预言家行动
        # ═══════════════════════════════════════════
        if u_role == "预言家":
            self._show_night_section("预言家查验", "🔮", "cyan")
        else:
            console.print(f"\n[dim]月光洒落，有人在窥探命运...[/dim]")

        seers = [p for p in self.alive_players if self.player_roles[p] == "预言家"]
        if seers:
            s = seers[0]
            check_targets = [p for p in self.alive_players if p != s]
            # 过滤已查验
            already_checked = set()
            records = self.seer_vision if s == "U" else self.ai_seer_vision.get(s, [])
            for entry in records:
                name = entry.split(" ")[0] if entry else ""
                if name:
                    already_checked.add(name)
            fresh_targets = [p for p in check_targets if p not in already_checked]
            if not fresh_targets:
                fresh_targets = check_targets

            if s == "U":
                if already_checked:
                    console.print(f"已查过: [dim]{', '.join(sorted(already_checked))}[/dim]")
                check = self._human_input(
                    "你要查验谁？",
                    choices=fresh_targets
                )
                res = "🐺 狼人" if self.player_roles[check] == "狼人" else "🌾 好人"
                console.print(Panel(
                    f"{get_player_label(check)} 的身份是：[bold]{res}[/bold]",
                    border_style="cyan",
                    title="🔮 查验结果"
                ))
                self.seer_vision.append(f"{check}({res})")
            else:
                sys_prompt = "请查验一名玩家。不要查验已经查过的人。格式: [TARGET: 代号]"
                ai_check = self._call_llm(
                    s, sys_prompt,
                    f"可选目标: {fresh_targets} (已查过: {list(already_checked)}，不要再查)",
                    require_target=True,
                    valid_targets=fresh_targets,
                    hide_identity=True,
                    max_tokens=300
                )
                if ai_check and ai_check in check_targets:
                    res = "狼人" if self.player_roles.get(ai_check) == "狼人" else "好人"
                    self.ai_seer_vision[s].append(f"{ai_check} 是 {res}")
                else:
                    fallback = random.choice(fresh_targets)
                    res = "狼人" if self.player_roles.get(fallback) == "狼人" else "好人"
                    self.ai_seer_vision[s].append(f"{fallback} 是 {res}")
        elif u_role == "预言家":
            console.print("[dim]没有存活的预言家。[/dim]")

        if not self.fast_forward:
            time.sleep(delay)

        # ═══════════════════════════════════════════
        # 3. 女巫行动
        # ═══════════════════════════════════════════
        if u_role == "女巫":
            self._show_night_section("女巫抉择", "🧪", "magenta")
        else:
            console.print(f"\n[dim]药瓶轻响，有人在调配生死...[/dim]")
        witches = [p for p in self.alive_players if self.player_roles[p] == "女巫"]
        dead_this_night = [killed_id] if killed_id else []

        if witches:
            w = witches[0]
            if w == "U":
                # ── 人类女巫 ──
                if killed_id:
                    console.print(f"今晚被杀的是：[bold red]{get_player_label(killed_id)}[/bold red]")
                else:
                    console.print("[dim]今晚无人被杀。[/dim]")

                # 解药
                if not self.witch_save_used:
                    if self._human_input("使用解药吗？(Y/N)", choices=["Y", "N"]) == "Y":
                        if killed_id and killed_id in dead_this_night:
                            dead_this_night.remove(killed_id)
                        self.witch_save_used = True
                        console.print("[green]✓ 已使用解药，该玩家存活[/green]")
                    else:
                        console.print("[dim]未使用解药[/dim]")

                # 毒药
                if not self.witch_poison_used:
                    if is_first_night:
                        console.print("[dim]首夜不可使用毒药（标准规则）[/dim]")
                    elif self._human_input("使用毒药吗？(Y/N)", choices=["Y", "N"]) == "Y":
                        poison_candidates = [p for p in self.alive_players if p != w]
                        poison_target = self._human_input("毒杀谁？", choices=poison_candidates)
                        dead_this_night.append(poison_target)
                        self.witch_poison_used = True
                        console.print(f"[red]✓ 已毒杀 {get_player_label(poison_target)}[/red]")
            else:
                # ── AI 女巫 — 解药 ──
                if killed_id and not self.witch_save_used:
                    sys_prompt = (
                        "你是女巫。今晚有人被杀。你要使用解药救他吗？"
                        "回复格式：[TARGET: Y] 或 [TARGET: N]"
                    )
                    use_save = self._call_llm(
                        w, sys_prompt,
                        f"今晚被杀的是 {killed_id}。使用解药吗？",
                        require_target=True,
                        valid_targets=["Y", "N"],
                        hide_identity=True,
                        max_tokens=300
                    )
                    if use_save == "Y":
                        if killed_id in dead_this_night:
                            dead_this_night.remove(killed_id)
                        self.witch_save_used = True

                # ── AI 女巫 — 毒药 ──
                if not self.witch_poison_used:
                    if is_first_night:
                        pass
                    else:
                        poison_targets = [p for p in self.alive_players if p != w] + ["Pass"]
                        sys_prompt = (
                            "你要使用毒药吗？如果不用请回复Pass，如果要毒人请回复目标代号。"
                            "格式: [TARGET: 代号] 或 [TARGET: Pass]"
                        )
                        poison = self._call_llm(
                            w, sys_prompt,
                            f"可选毒杀目标: {poison_targets}",
                            require_target=True,
                            valid_targets=poison_targets,
                            hide_identity=True,
                            max_tokens=300
                        )
                        if poison != "Pass" and poison in poison_targets:
                            dead_this_night.append(poison)
                            self.witch_poison_used = True

        if not self.fast_forward:
            time.sleep(delay)

        # ═══════════════════════════════════════════
        # 天亮结算
        # ═══════════════════════════════════════════
        console.print()
        self._show_dawn_banner()
        console.print(f"☀️ [bold yellow]第 {self.night_number} 夜结束，天亮了！[/bold yellow]")

        if not dead_this_night:
            console.print(Panel("✨ [green]昨晚是平安夜，无人死亡。[/green]", border_style="green"))
            self.history.append("【系统】昨晚是平安夜。")
        else:
            unique_dead = list(set(dead_this_night))
            console.print(f"\n💀 [bold red]{len(unique_dead)} 人死于昨夜...[/bold red]\n")

            for d in unique_dead:
                was_killed_by_wolf = (d == killed_id)
                was_poisoned = any(
                    d == item for item in dead_this_night
                    if item != killed_id
                )
                if was_poisoned:
                    self.handle_death(d, cause="poison")
                elif was_killed_by_wolf:
                    self.handle_death(d, cause="wolf")
                else:
                    self.handle_death(d, cause="unknown")
                self._draw_divider(style="dim")
                time.sleep(0.5)

    # ═══════════════════════════════════════════════
    # 白天阶段
    # ═══════════════════════════════════════════════
    def day_phase(self):
        self.day_number += 1

        # ── 边界检查 ──
        if len(self.alive_players) <= 1:
            console.print(Panel(
                f"[dim]存活人数不足 ({len(self.alive_players)}人)，跳过第 {self.day_number} 天白天。[/dim]",
                border_style="grey50"
            ))
            return

        console.print()
        console.print(Panel(
            f"☀️ [bold green]第 {self.day_number} 天 — 自由讨论与投票[/bold green]",
            border_style="green"
        ))
        self.history.append(f"\n=== 第 {self.day_number} 天 发言环节 ===")
        self.display_hud()
        self._show_dead_notice()
        if not self.human_alive:
            self._show_mini_hud()

        # ═══════════════════════════════════════════
        # 🗣️ 发言环节
        # ═══════════════════════════════════════════
        console.print("\n[bold cyan]🗣️  发言环节[/bold cyan]")
        self._draw_divider()

        shuffled_players = random.sample(
            self.alive_players, len(self.alive_players)
        )

        # ── 警长归票权：警长最后发言 ──
        if self.sheriff and self.sheriff in shuffled_players:
            shuffled_players.remove(self.sheriff)
            shuffled_players.append(self.sheriff)

        # 显示发言顺序
        order_text = " → ".join([get_player_label(p) for p in shuffled_players])
        console.print(f"[dim]发言顺序: {order_text}[/dim]\n")

        for p in shuffled_players:
            if p == "U":
                speech = self._human_input(
                    f"轮到你发言了 ({get_player_label('U')})",
                    allow_commands=False
                )
                self.history.append(f"【发言】 U: {speech}")
                console.print(self._speech_bubble("U", speech))
            else:
                sys_prompt = (
                    "现在是白天发言。请分析局势并伪装或指控。"
                    "不要说自己是AI。你的发言应该基于上面的历史记录展开。"
                )
                speech = self._call_llm(p, sys_prompt, "请输出你的发言:")
                self.history.append(f"【发言】 {p}: {speech}")
                console.print(self._speech_bubble(p, speech))

            if not self.fast_forward:
                time.sleep(0.3)
            self._draw_divider(style="dim")

        # ── 边界检查 ──
        if len(self.alive_players) <= 1:
            return

        # ═══════════════════════════════════════════
        # 🗳️ 投票环节
        # ═══════════════════════════════════════════
        console.print(f"\n[bold cyan]🗳️  投票环节[/bold cyan]")
        self._draw_divider()

        self.history.append(f"\n=== 第 {self.day_number} 天 投票环节 ===")
        votes = {p: 0 for p in self.alive_players}

        for p in self.alive_players:
            v_targets = [t for t in self.alive_players if t != p] + ["Pass"]
            if p == "U":
                v = self._human_input(
                    f"你要投票给谁？({get_player_label('U')})",
                    choices=v_targets,
                    allow_commands=False
                )
            else:
                sys_prompt = (
                    "投票环节。投给你认为最像敌对阵营的人以获取胜利。"
                    "格式: [TARGET: 代号] 或 [TARGET: Pass]"
                )
                v = self._call_llm(
                    p, sys_prompt,
                    f"请从候选人中投票: {v_targets}",
                    require_target=True,
                    valid_targets=v_targets,
                    max_tokens=300
                )

            if v != "Pass" and v in votes:
                # ── 警长 1.5 票特权 ──
                vote_weight = 1.5 if (self.sheriff and p == self.sheriff) else 1.0
                votes[v] += vote_weight
                weight_label = " [1.5票]" if vote_weight == 1.5 else ""
                console.print(f"  {get_player_label(p)} → {get_player_label(v)}{weight_label}")
            else:
                console.print(f"  {get_player_label(p)} → [dim]弃权[/dim]")

            self.history.append(f"【投票】 {p} 投给了 {v}")
            if not self.fast_forward:
                time.sleep(0.2)

        console.print()

        # ── 结算投票 ──
        if any(votes.values()):
            max_v = max(votes.values())
            winners = [k for k, v in votes.items() if v == max_v]

            if len(winners) == 1:
                executed = winners[0]
            else:
                executed = None

            self._show_vote_result(votes, executed)

            if len(winners) == 1:
                console.print(f"\n💀 [bold red]{get_player_label(winners[0])} 被投票放逐！[/bold red]")
                self.handle_death(winners[0], cause="vote")
                self.tie_count = 0
            else:
                self.tie_count += 1
                console.print(f"\n⚖️ 平票！(连续: {self.tie_count} 轮)")

                if self.tie_count >= 3:
                    forced = random.choice(winners)
                    console.print(
                        f"⚠️ [bold yellow]连续{self.tie_count}轮平票，系统随机放逐 "
                        f"{get_player_label(forced)}[/bold yellow]"
                    )
                    self.history.append(
                        f"【系统】连续{self.tie_count}轮平票，系统随机放逐 {forced}。"
                    )
                    self.handle_death(forced, cause="forced")
                    self.tie_count = 0
                else:
                    self.history.append("【系统】平票，无人被处决。")
        else:
            console.print("[dim]本轮无人投票，无人被处决。[/dim]")
            self.history.append("【系统】无人投票，无人被处决。")

    # ═══════════════════════════════════════════════
    # 统计与回放
    # ═══════════════════════════════════════════════
    def save_stats(self):
        model_stats = {}
        for config in self.ai_llm_configs.values():
            m_name = config["name"]
            if m_name not in model_stats:
                model_stats[m_name] = {"total": 0, "win": 0, "survive": 0}

        for p, config in self.ai_llm_configs.items():
            m_name = config["name"]
            role = self.player_roles[p]
            is_win = (
                (self.winner == "狼人阵营" and role == "狼人")
                or (self.winner == "好人阵营" and role != "狼人")
            )
            is_survive = p in self.alive_players

            model_stats[m_name]["total"] += 1
            if is_win:
                model_stats[m_name]["win"] += 1
            if is_survive:
                model_stats[m_name]["survive"] += 1

        stats_table = Table(title="📈 大模型表现统计")
        stats_table.add_column("模型名称", style="cyan", min_width=28, max_width=40)
        stats_table.add_column("出场", style="white", justify="center")
        stats_table.add_column("胜率", style="yellow", justify="right", min_width=8)
        stats_table.add_column("存活率", style="green", justify="right", min_width=8)

        try:
            logging.info("=== 新的对局结束 ===")
            logging.info(f"Winner Faction: {self.winner}")

            for m_name, stats in model_stats.items():
                win_rate = (stats["win"] / stats["total"]) * 100
                survive_rate = (stats["survive"] / stats["total"]) * 100

                stats_table.add_row(
                    m_name, str(stats["total"]),
                    f"{win_rate:.1f}%", f"{survive_rate:.1f}%"
                )
                logging.info(
                    f"Model: {m_name: <20} | Instances: {stats['total']} | "
                    f"Win Rate: {win_rate:6.2f}% | Survival Rate: {survive_rate:6.2f}%"
                )

            console.print(stats_table)
            console.print(
                f"\n[bold green]✅ 统计已保存至 {log_file_path}[/bold green]"
            )
        except Exception as e:
            console.print(f"[bold red]❌ 保存日志失败: {e}[/bold red]")

    def _replay_history(self):
        """赛后回放：按时间线展示关键事件"""
        console.print("\n")
        console.print(Panel(
            "[bold cyan]📜 游戏回放 — 关键事件时间线[/bold cyan]",
            border_style="cyan"
        ))

        # 过滤关键事件
        key_events = []
        for entry in self.history:
            text = entry.strip()
            if not text:
                continue
            # 分类着色
            if text.startswith("【系统】"):
                style = "dim"
            elif text.startswith("【发言】"):
                # 提取玩家代号并着色
                parts = text.split(":", 1)
                if len(parts) == 2:
                    player_code = parts[0].replace("【发言】", "").strip().split(" ")[0]
                    color = PLAYER_COLORS.get(player_code, "white")
                    emoji = PLAYER_EMOJIS.get(player_code, "")
                    text = f"[{color}]{emoji}{text}[/{color}]"
                    style = None
                else:
                    style = "white"
            elif text.startswith("【投票】"):
                style = "yellow"
            elif text.startswith("==="):
                style = "bold cyan"
            else:
                style = "white"

            if style:
                key_events.append(f"[{style}]{text}[/{style}]")
            else:
                key_events.append(text)

        # 只显示关键节点，省略纯发言细节中的长文本
        simplified = []
        for event in key_events:
            if len(event) > 120 and "【发言】" in event:
                # 截断长发言
                bracket_end = event.find("】")
                simplified.append(event[:bracket_end + 1] + " " + event[bracket_end + 1:bracket_end + 101] + "...[/" + event.split("[")[-1].split("]")[0] + "]")
            else:
                simplified.append(event)

        # 分页显示（每20条一页）
        page_size = 20
        for i in range(0, len(simplified), page_size):
            page = simplified[i:i + page_size]
            for line in page:
                console.print(line)
            if i + page_size < len(simplified):
                if Prompt.ask(
                    f"\n[dim]按 Enter 继续 (第 {i//page_size + 1} 页) ...[/dim]",
                    default=""
                ) == "q":
                    break

    # ═══════════════════════════════════════════════
    # 主循环
    # ═══════════════════════════════════════════════
    def run(self):
        self.setup()

        # ── 🌙 第0夜：预言家单独查验 ──
        self.night_zero()

        # ── 🎖️ 警长竞选（预言家已有验人信息） ──
        self.sheriff_election()

        while not self.winner:
            # ── 夜晚 ──
            self.night_phase()
            if self.check_win():
                break

            # ── 白天 ──
            self.day_phase()
            if self.check_win():
                break

            if len(self.alive_players) <= 1:
                self.check_win()
                break

        # ═══════════════════════════════════════════
        # 🏆 游戏结束
        # ═══════════════════════════════════════════
        console.print("\n")
        winner_style = "red" if "狼人" in (self.winner or "") else "green"
        console.print(Panel.fit(
            f"[bold {winner_style}]🏆 游戏结束！{self.winner} 获胜！ 🏆[/bold {winner_style}]\n"
            f"[dim]共经过 {self.night_number} 夜 {self.day_number} 天[/dim]",
            border_style=winner_style
        ))

        # 结果表
        res_table = Table(title="📋 玩家大揭秘")
        res_table.add_column("玩家", style="cyan", min_width=10, max_width=12)
        res_table.add_column("身份", style="yellow", min_width=10, max_width=12)
        res_table.add_column("LLM 引擎", style="magenta", min_width=28, max_width=40)
        res_table.add_column("结局", style="green", min_width=12, max_width=16)

        for p in PLAYERS:
            label = get_player_label(p)
            role = self.player_roles[p]
            role_display = f"{get_role_emoji(role)} {role}"
            status = "[green]● 存活[/green]" if p in self.alive_players else "[red]✕ 死亡[/red]"
            engine = "👤 人类" if p == "U" else (
                f"{cfg['name']} (#{cfg['idx']})"
                if (cfg := self.ai_llm_configs.get(p, {})) else "N/A"
            )
            res_table.add_row(label, role_display, engine, status)

        console.print(res_table)

        # 统计
        self.save_stats()

        # ── 历史回放选项 ──
        if Prompt.ask(
            "\n📜 要查看游戏回放吗？(Y/N)",
            choices=["Y", "N"],
            default="N"
        ) == "Y":
            self._replay_history()

        console.print(
            "\n[dim]程序已休眠，将在 86400 秒后自动关闭。你可以直接关闭窗口退出。[/dim]"
        )
        time.sleep(86400)


# ═══════════════════════════════════════════════════
if __name__ == "__main__":
    WerewolfGame().run()
