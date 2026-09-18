from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

import cli
from xhs import publish, publish_long_article, publish_video
from xhs.errors import PublishError


@pytest.mark.parametrize(('content', 'tags', 'expected'), [
    ('正文\n\n#旅行 #周末\n#摄影#旅行\n', [' #旅行 ', ''], ('正文', ['旅行', '周末', '摄影'])),
    ('# Markdown 标题\n正文中提到 #旅行，不作转换。', [],
     ('# Markdown 标题\n正文中提到 #旅行，不作转换。', [])),
    ('正文\n\n', ['#旅行', '旅行'], ('正文\n\n', ['旅行'])),
    ('#旅行', [], ('', ['旅行'])),
])
def test_extract_topics(content, tags, expected):
    assert publish._extract_hashtags_from_content(content, tags) == expected


def test_merged_topics_limit_does_not_silently_drop_requested_topics():
    with pytest.raises(PublishError, match='超过10个'):
        publish._extract_hashtags_from_content('正文\n#额外话题', [str(i) for i in range(10)])


def test_missing_suggestion_stops_instead_of_completing_plain_hashtag(monkeypatch):
    page = Mock()
    page.has_element.return_value = False
    ticks = iter([0, 0, 4])
    monkeypatch.setattr(publish.time, 'monotonic', lambda: next(ticks))
    monkeypatch.setattr(publish.time, 'sleep', lambda _: None)
    with pytest.raises(PublishError, match='不能把普通 #文字当作话题发布'):
        publish._input_single_tag(page, '.editor', '旅行')
    assert [call.args[0] for call in page.type_text.call_args_list] == ['#', '旅', '行']
    page.click_element.assert_not_called()


def test_suggestion_is_selected(monkeypatch):
    page = Mock()
    page.has_element.return_value = True
    monkeypatch.setattr(publish.time, 'sleep', lambda _: None)
    publish._input_single_tag(page, '.editor', '旅行')
    page.click_element.assert_called_once_with(
        f'{publish.TAG_TOPIC_CONTAINER} {publish.TAG_FIRST_ITEM}')


@pytest.mark.parametrize('module', [publish, publish_video])
def test_image_and_video_route_trailing_topics_through_picker(module, monkeypatch):
    page = Mock()
    picker = Mock()
    monkeypatch.setattr(module.time, 'sleep', lambda _: None)
    monkeypatch.setattr(module, '_find_content_element', lambda _: '.editor')
    monkeypatch.setattr(module, '_input_tags', picker)
    monkeypatch.setattr(publish, '_check_title_max_length', lambda _: None)
    monkeypatch.setattr(publish, '_check_content_max_length', lambda _: None)
    if module is publish:
        module._fill_publish_form(page, '标题', '正文\n#旅行', ['周末'], None, False, '')
    else:
        module._fill_publish_video_form(page, '标题', '正文\n#旅行', ['周末'], None, '')
    page.input_content_editable.assert_called_once_with('.editor', '正文')
    picker.assert_called_once_with(page, '.editor', ['周末', '旅行'])


@pytest.mark.parametrize('description', ['正文\n#旅行', '#旅行'])
def test_long_article_routes_topics_to_description_picker(description, monkeypatch):
    page = Mock()
    picker = Mock()
    monkeypatch.setattr(publish_long_article.time, 'sleep', lambda _: None)
    monkeypatch.setattr(publish_long_article, '_click_button_by_text', lambda *args: None)
    monkeypatch.setattr(publish_long_article, '_find_content_element', lambda _: '.editor')
    monkeypatch.setattr(publish_long_article, '_input_tags', picker)
    publish_long_article.click_next_and_fill_description(page, description, ['周末'])
    picker.assert_called_once_with(page, '.editor', ['周末', '旅行'])
    assert '#' not in page.input_content_editable.call_args.args[1]


def test_next_step_cli_forwards_topics(tmp_path, monkeypatch):
    content = tmp_path / 'content.txt'
    content.write_text('正文', encoding='utf-8')
    args = cli.build_parser().parse_args([
        'next-step', '--content-file', str(content), '--tags', '旅行', '周末'])
    browser, page = Mock(), Mock()
    fill = Mock()
    monkeypatch.setattr(cli, '_connect_existing', lambda _: (browser, page))
    monkeypatch.setattr(cli, '_output', Mock())
    monkeypatch.setattr(publish_long_article, 'click_next_and_fill_description', fill)
    args.func(args)
    fill.assert_called_once_with(page, '正文', tags=['旅行', '周末'])


@pytest.mark.parametrize(('module', 'entry', 'fill', 'click'), [
    (publish, 'publish_image_content', 'fill_publish_form', 'click_publish_button'),
    (publish_video, 'publish_video_content', 'fill_publish_video_form', 'click_publish_video_button'),
])
def test_topic_failure_prevents_one_step_submission(module, entry, fill, click, monkeypatch):
    submit = Mock()
    monkeypatch.setattr(module, fill, Mock(side_effect=PublishError('话题未选中')))
    monkeypatch.setattr(module, click, submit)
    with pytest.raises(PublishError, match='话题未选中'):
        getattr(module, entry)(Mock(), Mock())
    submit.assert_not_called()
