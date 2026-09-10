"""关注状态查询和单次变更：核对用户、显式确认、刷新核验。"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from .errors import NotLoggedInError, XHSError

_SCRIPT = Path(__file__).with_suffix(".js").read_text(encoding="utf-8")


class RelationshipError(XHSError):
    """关注关系读取或变更前校验失败。"""


def _run(page: Any, action: str, **params: Any) -> dict:
    value = page.evaluate(f"({_SCRIPT})({json.dumps({'action': action, **params})})")
    if not isinstance(value, dict):
        raise RelationshipError("无法读取用户主页的关注状态")
    if value.get("not_logged_in"):
        raise NotLoggedInError()
    if value.get("error") or value.get("__xhs_error"):
        raise RelationshipError(value.get("error") or value["__xhs_error"])
    return value


def _wait_profile(page: Any, user_id: str, expected_name: str, timeout: float = 12.0) -> dict:
    deadline = time.monotonic() + timeout
    while True:
        state = _run(page, "read", user_id=user_id, expected_name=expected_name)
        if state.get("ready"):
            return state
        if time.monotonic() >= deadline:
            raise RelationshipError("用户主页或关注按钮未就绪；可能无法访问或网页不支持该操作")
        time.sleep(0.3)


def set_follow(
    page: Any, user_id: str, expected_name: str, state: str,
    *, xsec_token: str = "", confirmed: bool = False, timeout: float = 12.0,
) -> dict:
    """默认只读预览；确认后至多点击一次，刷新确认最终状态，不自动重试。"""
    if not re.fullmatch(r"[0-9a-fA-F]{24}", user_id):
        raise RelationshipError("用户 ID 必须为 24 位十六进制 ID")
    if not expected_name.strip():
        raise RelationshipError("必须提供目标用户完整昵称")
    if state not in ("followed", "not-followed"):
        raise RelationshipError("目标状态必须为 followed 或 not-followed")
    url = f"https://www.xiaohongshu.com/user/profile/{user_id}"
    if xsec_token:
        url += "?" + urlencode({"xsec_token": xsec_token, "xsec_source": "pc_note"})
    page.navigate(url)
    page.wait_for_load()
    current = _wait_profile(page, user_id, expected_name)
    base = {"user_id": user_id, "nickname": expected_name, "desired_state": state}
    if not confirmed:
        return {**base, "success": True, "status": "preview", "changed": False,
                "current_state": current["state"], "would_change": current["state"] != state}
    if current["state"] == state:
        return {**base, "success": True, "status": "unchanged", "changed": False,
                "current_state": current["state"]}
    # 身份、当前状态、目标状态检查和点击在一次脚本中完成；点击后故障不能视为可重试。
    try:
        clicked = _run(page, "set", user_id=user_id, expected_name=expected_name,
                       expected_state=current["state"], desired_state=state)
        if clicked.get("unchanged"):
            return {**base, "success": True, "status": "unchanged", "changed": False,
                    "current_state": state}
        if not clicked.get("clicked"):
            raise RelationshipError("网页未确认已经执行关注操作")
        deadline = time.monotonic() + timeout
        while True:
            after = _run(page, "read", user_id=user_id, expected_name=expected_name)
            if after.get("ready") and after.get("state") == state:
                # 防止把页面乐观更新误当成持久化成功。
                page.navigate(url)
                page.wait_for_load()
                reloaded = _wait_profile(page, user_id, expected_name)
                if reloaded.get("state") == state:
                    return {**base, "success": True, "status": "updated", "changed": True,
                            "current_state": state, "verification": "reloaded_page"}
                break
            if time.monotonic() >= deadline:
                break
            time.sleep(0.3)
    except Exception:
        return {**base, "success": False, "status": "unknown", "changed": None,
                "error": "操作后的状态无法确认；请核对主页，勿直接重试"}
    return {**base, "success": False, "status": "unknown", "changed": None,
            "error": "未能确认刷新后的目标状态；请核对主页，勿直接重试"}
