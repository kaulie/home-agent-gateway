"""DLNA AVTransport 传输控制的公共小工具（小度音箱 / 小米电视共用）。

只做一件事：把用户/规划器给的 `action`（中文或英文）规范化成 `pause` / `resume` / `stop`，
并给出文案与 UPnP/SOAP 动作名。两个插件各自负责「怎么发」（小度走 UPnP POST、电视走
SOAP SetAVTransportURI 那套），这里只管**语义**，避免两份别名表各写一遍。
"""

from __future__ import annotations

ACTION_PAUSE = "pause"
ACTION_RESUME = "resume"
ACTION_STOP = "stop"
ACTIONS = (ACTION_PAUSE, ACTION_RESUME, ACTION_STOP)

# 中文口语 → 规范动作（「停一下/暂停」都算 pause；「别放了/关掉」按 stop 处理）
_ALIASES: dict[str, str] = {
    "pause": ACTION_PAUSE,
    "暂停": ACTION_PAUSE,
    "暂停播放": ACTION_PAUSE,
    "停一下": ACTION_PAUSE,
    "先停一下": ACTION_PAUSE,
    "resume": ACTION_RESUME,
    "继续": ACTION_RESUME,
    "继续播放": ACTION_RESUME,
    "接着放": ACTION_RESUME,
    "接着播": ACTION_RESUME,
    "恢复": ACTION_RESUME,
    "恢复播放": ACTION_RESUME,
    "stop": ACTION_STOP,
    "停止": ACTION_STOP,
    "停止播放": ACTION_STOP,
    "别放了": ACTION_STOP,
    "关掉": ACTION_STOP,
    "不听了": ACTION_STOP,
}

LABELS: dict[str, str] = {
    ACTION_PAUSE: "已暂停",
    ACTION_RESUME: "继续播放",
    ACTION_STOP: "已停止",
}


class TransportActionError(ValueError):
    """action 不认识（中文/英文之外的说法）。"""


def parse_action(raw: object) -> str:
    """规范化 action；不认识就抛 TransportActionError（调用方翻成自己的错误类型）。"""
    text = str(raw or "").strip().lower().replace(" ", "")
    if not text:
        return ACTION_PAUSE  # 缺省：最常见的诉求就是「暂停」
    action = _ALIASES.get(text) or _ALIASES.get(str(raw or "").strip())
    if action is None:
        raise TransportActionError(
            f"不认识的播放控制动作 {raw!r}（支持 pause/暂停、resume/继续、stop/停止）"
        )
    return action


def label_for(action: str) -> str:
    return LABELS.get(action, action)
