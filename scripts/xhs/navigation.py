"""为日常管理命令保护网页中尚未处理的编辑内容。"""

from __future__ import annotations

from .errors import XHSError

_GUARD = """
(() => {
    const visible = el => {
        const rect = el.getBoundingClientRect();
        const style = getComputedStyle(el);
        return rect.width > 0 && rect.height > 0 && style.display !== 'none' &&
            style.visibility !== 'hidden' && Number(style.opacity || 1) > 0.1;
    };
    if (location.hostname === 'www.xiaohongshu.com' && /^\\/chat/.test(location.pathname)) {
        const editors = [...document.querySelectorAll('.xhs-im-input-bar-editor')].filter(visible);
        if (editors.some(el => el.textContent.trim() || el.querySelector('img,video,audio'))) {
            return {safe: false, reason: '当前私信存在草稿，请先处理后再切换页面'};
        }
    }
    if (location.hostname === 'creator.xiaohongshu.com' &&
        /^\\/publish\\//.test(location.pathname)) {
        const outsideDraftList = el => !el.closest('.draft-drawer, .draft-list, .draft-item');
        const editors = [...document.querySelectorAll(
            'textarea,input:not([type]),input[type="text"],[contenteditable="true"]'
        )].filter(el => visible(el) && outsideDraftList(el));
        const content = editors.some(el => String(el.value || el.textContent || '').trim() ||
            el.querySelector('img,video,audio'));
        const files = [...document.querySelectorAll('input[type="file"]')]
            .some(el => outsideDraftList(el) && el.files && el.files.length);
        const loadedMedia = [...document.querySelectorAll(
            '.upload-preview,.image-item,.uploaded-item,.video-preview,.img-preview,' +
            '.img-preview-area .pr,video[src],audio[src]'
        )].some(el => visible(el) && outsideDraftList(el));
        if (content || files || loadedMedia) {
            return {safe: false, reason: '当前创作编辑器已有内容，请先保存或处理后再切换页面'};
        }
    }
    return {safe: true};
})()
"""


class GuardedPage:
    """复用 BridgePage，导航前检查现有草稿；不保存或删除网页内容。"""

    def __init__(self, page):
        self._page = page

    def __getattr__(self, name):
        return getattr(self._page, name)

    def navigate(self, url):
        state = self._page.evaluate(_GUARD)
        if not isinstance(state, dict) or state.get("safe") is not True:
            reason = state.get("reason") if isinstance(state, dict) else None
            raise XHSError(reason or "无法确认现有编辑内容是否可安全离开，未导航")
        return self._page.navigate(url)
