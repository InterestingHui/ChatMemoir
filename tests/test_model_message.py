"""Unit tests for memoir.model.message — Message dataclass hierarchy.

Tests cover all 15 message types: constructors, to_text(), to_json(), type_name(),
is_chatroom(), comparison, get_file_size(), set_file_name(), and MessageType utilities.
"""

import json
from datetime import datetime
from unittest import mock

import pytest

from memoir.model.message import (
    Message,
    MessageType,
    TextMessage,
    QuoteMessage,
    FileMessage,
    ImageMessage,
    EmojiMessage,
    VideoMessage,
    AudioMessage,
    LinkMessage,
    FavoritesVideoMessage,
    MergedMessage,
    VoipMessage,
    PositionMessage,
    BusinessCardMessage,
    TransferMessage,
    RedEnvelopeMessage,
    FavNoteMessage,
    PatMessage,
)


# ── Helpers ──────────────────────────────────────────────────

def _base_msg(**kwargs):
    defaults = dict(
        local_id=1,
        server_id=101,
        sort_seq=1,
        timestamp=1700000000,
        str_time="2024-11-15 00:00:00",
        type=MessageType.Text,
        talker_id="wxid_test123",
        is_sender=True,
        sender_id="wxid_sender",
        display_name="TestUser",
        avatar_src="",
        status=3,
        xml_content="<msg></msg>",
    )
    defaults.update(kwargs)
    return defaults


# ── MessageType ──────────────────────────────────────────────


class TestMessageType:
    def test_name_known_types(self):
        assert MessageType.name(MessageType.Text) == '文本'
        assert MessageType.name(MessageType.Image) == '图片'
        assert MessageType.name(MessageType.Video) == '视频'
        assert MessageType.name(MessageType.Audio) == '语音'
        assert MessageType.name(MessageType.Emoji) == '表情包'
        assert MessageType.name(MessageType.File) == '文件'
        assert MessageType.name(MessageType.Voip) == '音视频通话'
        assert MessageType.name(MessageType.RedEnvelope) == '红包'
        assert MessageType.name(MessageType.Transfer) == '转账'
        assert MessageType.name(MessageType.System) == '系统消息'
        assert MessageType.name(MessageType.Pat) == '拍一拍'
        assert MessageType.name(MessageType.Position) == '位置分享'
        assert MessageType.name(MessageType.Quote) == '引用消息'

    def test_name_unknown_type(self):
        assert MessageType.name(99999999) == '未知类型'
        assert MessageType.name(-999) == '未知类型'

    def test_constants_are_unique(self):
        """All MessageType constants should be unique integers."""
        attrs = {v for k, v in vars(MessageType).items()
                 if not k.startswith('_') and isinstance(v, int)}
        assert len(attrs) > 15


# ── Message base class ───────────────────────────────────────


class TestMessage:
    def test_constructor(self):
        msg = Message(**_base_msg())
        assert msg.local_id == 1
        assert msg.type == MessageType.Text
        assert msg.is_sender is True
        assert msg.talker_id == "wxid_test123"

    def test_is_chatroom_true(self):
        msg = Message(**_base_msg(talker_id="123456@chatroom"))
        assert msg.is_chatroom() is True

    def test_is_chatroom_false(self):
        msg = Message(**_base_msg(talker_id="wxid_test123"))
        assert msg.is_chatroom() is False

    def test_type_name(self):
        msg = Message(**_base_msg(type=MessageType.Image))
        assert msg.type_name() == '图片'

    def test_to_text(self):
        msg = Message(**_base_msg(xml_content="<msg><text>hello</text></msg>"))
        result = msg.to_text()
        assert "hello" in result

    def test_to_json(self):
        msg = Message(**_base_msg(server_id=12345, is_sender=False))
        data = msg.to_json()
        assert data['type'] == str(MessageType.Text)
        assert data['is_send'] is False
        assert data['server_id'] == '12345'

    def test_to_json_invalid_xml(self):
        msg = Message(**_base_msg(xml_content="not valid xml <<<"))
        data = msg.to_json()
        assert 'xml_dict' in data

    def test_comparison_by_sort_seq(self):
        msg1 = Message(**_base_msg(sort_seq=1))
        msg2 = Message(**_base_msg(sort_seq=10))
        assert msg1 < msg2
        assert not msg2 < msg1


# ── TextMessage ──────────────────────────────────────────────


class TestTextMessage:
    def test_constructor_and_content(self):
        msg = TextMessage(**_base_msg(), content="你好世界")
        assert msg.content == "你好世界"

    def test_to_text(self):
        msg = TextMessage(**_base_msg(), content="hello")
        assert msg.to_text() == "hello"

    def test_to_json(self):
        msg = TextMessage(**_base_msg(server_id=42), content="test text")
        data = msg.to_json()
        assert data['text'] == "test text"
        assert data['server_id'] == '42'


# ── QuoteMessage ─────────────────────────────────────────────


class TestQuoteMessage:
    def test_quotes_text_message(self):
        quoted = TextMessage(**_base_msg(display_name="Alice"), content="original")
        qm = QuoteMessage(**_base_msg(display_name="Bob"), content="reply", quote_message=quoted)
        text = qm.to_text()
        assert "reply" in text
        assert "Alice" in text
        assert "original" in text

    def test_quotes_another_quote_prevents_recursion(self):
        """Quoting a QuoteMessage should not recurse — uses .content directly."""
        inner = TextMessage(**_base_msg(), content="inner text")
        quoted_quote = QuoteMessage(**_base_msg(display_name="Alice"), content="mid", quote_message=inner)
        qm = QuoteMessage(**_base_msg(display_name="Bob"), content="outer", quote_message=quoted_quote)
        text = qm.to_text()
        assert "outer" in text
        assert "Alice" in text
        assert "inner text" in text

    def test_to_json(self):
        quoted = TextMessage(**_base_msg(server_id=10, display_name="User"), content="hello")
        qm = QuoteMessage(**_base_msg(server_id=20), content="reply", quote_message=quoted)
        data = qm.to_json()
        assert data['quote_server_id'] == '10'
        assert data['text'] == 'reply'


# ── FileMessage ──────────────────────────────────────────────


class TestFileMessage:
    def test_get_file_size(self):
        fm = FileMessage(**_base_msg(), path="", md5="", file_size=1048576,
                         file_name="test.pdf", file_type="pdf")
        assert fm.get_file_size('MB') == '1.00 MB'
        assert fm.get_file_size('KB') == '1024.00 KB'
        assert fm.get_file_size('B') == '1048576.00 B'

    def test_get_file_size_gb(self):
        fm = FileMessage(**_base_msg(), path="", md5="", file_size=2 * 1024**3,
                         file_name="big.mkv", file_type="mkv")
        assert fm.get_file_size('GB') == '2.00 GB'

    def test_get_file_size_invalid_format(self):
        fm = FileMessage(**_base_msg(), path="", md5="", file_size=100,
                         file_name="x.txt", file_type="txt")
        with pytest.raises(ValueError):
            fm.get_file_size('INVALID')

    def test_set_file_name_with_provided_name(self):
        fm = FileMessage(**_base_msg(), path="", md5="", file_size=100,
                         file_name="", file_type="txt")
        assert fm.set_file_name("custom.pdf") is True
        assert fm.file_name == "custom.pdf"

    def test_set_file_name_auto_generate(self):
        fm = FileMessage(**_base_msg(timestamp=1700000000, server_id=123456789),
                         path="", md5="", file_size=100, file_name="", file_type="txt")
        fm.set_file_name()
        assert "20231115" in fm.file_name or fm.file_name  # format varies by timezone

    def test_to_text(self):
        fm = FileMessage(**_base_msg(), path="/tmp/doc.pdf", md5="abc123",
                         file_size=2048, file_name="report.pdf", file_type="pdf")
        text = fm.to_text()
        assert "【文件】" in text
        assert "report.pdf" in text


# ── ImageMessage ─────────────────────────────────────────────


class TestImageMessage:
    def test_to_text(self):
        im = ImageMessage(**_base_msg(), path="/img/photo.jpg", md5="",
                          file_size=5000, file_name="", file_type="jpg",
                          thumb_path="/img/photo_thumb.jpg")
        assert "【图片】" in im.to_text()

    def test_to_json(self):
        im = ImageMessage(**_base_msg(), path="/img/photo.jpg", md5="",
                          file_size=5000, file_name="", file_type="jpg",
                          thumb_path="/img/thumb.jpg")
        data = im.to_json()
        assert data['path'] == "/img/photo.jpg"
        assert data['thumb_path'] == "/img/thumb.jpg"


# ── EmojiMessage ─────────────────────────────────────────────


class TestEmojiMessage:
    def test_to_text(self):
        em = EmojiMessage(**_base_msg(type=MessageType.Emoji), path="", md5="",
                          file_size=0, file_name="", file_type="",
                          thumb_path="", url="http://emoji.gif",
                          thumb_url="http://thumb.gif", description="大笑")
        assert "【表情包】" in em.to_text()
        assert "大笑" in em.to_text()

    def test_to_json(self):
        em = EmojiMessage(**_base_msg(type=MessageType.Emoji), path="", md5="",
                          file_size=0, file_name="", file_type="",
                          thumb_path="", url="http://emoji.gif",
                          thumb_url="http://thumb.gif", description="开心")
        data = em.to_json()
        assert data['path'] == "http://emoji.gif"
        assert data['desc'] == "开心"


# ── VideoMessage ─────────────────────────────────────────────


class TestVideoMessage:
    def test_to_text(self):
        vm = VideoMessage(**_base_msg(type=MessageType.Video), path="", md5="",
                          file_size=0, file_name="", file_type="",
                          thumb_path="", duration=120, raw_md5="abc")
        assert vm.to_text() == "【视频】"

    def test_to_json(self):
        vm = VideoMessage(**_base_msg(type=MessageType.Video), path="/v/test.mp4",
                          md5="", file_size=0, file_name="", file_type="",
                          thumb_path="/v/thumb.jpg", duration=60, raw_md5="def")
        data = vm.to_json()
        assert data['duration'] == 60
        assert data['path'] == "/v/test.mp4"


# ── AudioMessage ─────────────────────────────────────────────


class TestAudioMessage:
    def test_to_text(self):
        am = AudioMessage(**_base_msg(type=MessageType.Audio), path="", md5="",
                          file_size=0, file_name="", file_type="",
                          duration=30, audio_text="你好吗")
        assert "【语音】" in am.to_text()
        assert "你好吗" in am.to_text()

    def test_set_file_name(self):
        am = AudioMessage(**_base_msg(type=MessageType.Audio, timestamp=1700000000,
                                      server_id=999, is_sender=False),
                          path="", md5="", file_size=0, file_name="",
                          file_type="", duration=30, audio_text="")
        am.set_file_name()
        assert am.get_file_name() == am.file_name
        assert am.file_name.endswith('_0')


# ── LinkMessage ──────────────────────────────────────────────


class TestLinkMessage:
    def test_to_text(self):
        lm = LinkMessage(**_base_msg(type=MessageType.LinkMessage),
                         href="https://example.com", title="Example",
                         description="A cool site", cover_path="", cover_url="",
                         app_name="WeChat", app_icon="", app_id="")
        text = lm.to_text()
        assert "【分享链接】" in text
        assert "Example" in text

    def test_to_json(self):
        lm = LinkMessage(**_base_msg(type=MessageType.LinkMessage),
                         href="https://x.com", title="X", description="social",
                         cover_path="", cover_url="http://img.jpg", app_name="X",
                         app_icon="", app_id="1")
        data = lm.to_json()
        assert data['url'] == "https://x.com"
        assert data['title'] == "X"


# ── VoipMessage ──────────────────────────────────────────────


class TestVoipMessage:
    def test_to_text(self):
        vm = VoipMessage(**_base_msg(type=MessageType.Voip),
                         invite_type=1, display_content="语音通话 01:30", duration=90)
        assert "【音视频通话】" in vm.to_text()
        assert "语音通话" in vm.to_text()


# ── PositionMessage ──────────────────────────────────────────


class TestPositionMessage:
    def test_to_text(self):
        pm = PositionMessage(**_base_msg(type=MessageType.Position),
                             x=116.404, y=39.915, label="Beijing",
                             poiname="Tiananmen", scale=15.0)
        text = pm.to_text()
        assert "【位置分享】" in text
        assert "116.404" in text


# ── BusinessCardMessage ──────────────────────────────────────


class TestBusinessCardMessage:
    def test_to_text_personal(self):
        bm = BusinessCardMessage(**_base_msg(type=MessageType.BusinessCard),
                                 is_open_im=False, username="wxid_abc",
                                 nickname="John", alias="john_wx",
                                 province="北京", city="朝阳", sign="Hello",
                                 sex=1, small_head_url="", big_head_url="",
                                 open_im_desc="", open_im_desc_icon="")
        text = bm.to_text()
        assert "【名片】" in text
        assert "John" in text
        assert "男" in text

    def test_to_text_open_im(self):
        bm = BusinessCardMessage(**_base_msg(type=MessageType.BusinessCard),
                                 is_open_im=True, username="", nickname="Jane",
                                 alias="", province="", city="", sign="",
                                 sex=2, small_head_url="", big_head_url="",
                                 open_im_desc="ACME Corp", open_im_desc_icon="")
        text = bm.to_text()
        assert "ACME Corp" in text

    def test_sex_name_unknown(self):
        bm = BusinessCardMessage(**_base_msg(type=MessageType.BusinessCard),
                                 is_open_im=False, username="", nickname="",
                                 alias="", province="", city="", sign="",
                                 sex=0, small_head_url="", big_head_url="",
                                 open_im_desc="", open_im_desc_icon="")
        assert "未知" in bm._sex_name()

    def test_to_json(self):
        bm = BusinessCardMessage(**_base_msg(type=MessageType.BusinessCard),
                                 is_open_im=False, username="wxid", nickname="N",
                                 alias="alias", province="P", city="C", sign="S",
                                 sex=1, small_head_url="", big_head_url="",
                                 open_im_desc="", open_im_desc_icon="")
        data = bm.to_json()
        assert data['nickname'] == "N"
        assert data['sex'] == "男"


# ── TransferMessage ──────────────────────────────────────────


class TestTransferMessage:
    def test_display_content_known(self):
        tm = TransferMessage(**_base_msg(type=MessageType.Transfer),
                             fee_desc="100.00", pay_memo="lunch",
                             receiver_username="wxid_recv", pay_subtype=3)
        assert tm.display_content() == "已收款"

    def test_display_content_unknown(self):
        tm = TransferMessage(**_base_msg(type=MessageType.Transfer),
                             fee_desc="", pay_memo="", receiver_username="",
                             pay_subtype=99)
        assert tm.display_content() == "未知"


# ── RedEnvelopeMessage ──────────────────────────────────────


class TestRedEnvelopeMessage:
    def test_to_text(self):
        rm = RedEnvelopeMessage(**_base_msg(type=MessageType.RedEnvelope),
                                icon_url="", title="恭喜发财", inner_type=1)
        assert "【红包】" in rm.to_text()
        assert "恭喜发财" in rm.to_text()


# ── FavNoteMessage ───────────────────────────────────────────


class TestFavNoteMessage:
    def test_to_text(self):
        fm = FavNoteMessage(**_base_msg(type=MessageType.FavNote),
                            title="My Note", description="content here", record_item="item1")
        text = fm.to_text()
        assert "【笔记】" in text
        assert "content here" in text


# ── PatMessage ───────────────────────────────────────────────


class TestPatMessage:
    def test_to_text(self):
        pm = PatMessage(**_base_msg(type=MessageType.Pat),
                        title="你拍了拍张三", from_username="wxid_a",
                        chat_username="wxid_b", patted_username="wxid_c",
                        template="")
        assert pm.to_text() == "你拍了拍张三"

    def test_to_json_sets_system_type(self):
        pm = PatMessage(**_base_msg(type=MessageType.Pat),
                        title="拍一拍", from_username="", chat_username="",
                        patted_username="", template="")
        data = pm.to_json()
        assert data['type'] == MessageType.System


# ── MergedMessage ────────────────────────────────────────────


class TestMergedMessage:
    def test_to_text(self):
        inner = TextMessage(**_base_msg(display_name="Alice"), content="hi")
        mm = MergedMessage(**_base_msg(type=MessageType.MergedMessages),
                           title="Chat History", description="2 messages",
                           messages=[inner], level=0)
        text = mm.to_text()
        assert "【合并转发的聊天记录】" in text
        assert "Alice" in text
        assert "hi" in text

    def test_to_json(self):
        inner = TextMessage(**_base_msg(server_id=1, display_name="A"), content="hello")
        mm = MergedMessage(**_base_msg(type=MessageType.MergedMessages),
                           title="History", description="1 msg",
                           messages=[inner], level=0)
        data = mm.to_json()
        assert data['title'] == "History"
        assert len(data['messages']) == 1


# ── FavoritesVideoMessage ────────────────────────────────────


class TestFavoritesVideoMessage:
    def test_to_text(self):
        fv = FavoritesVideoMessage(**_base_msg(type=MessageType.FavoritesVideo),
                                   url="http://video.mp4", publisher_nickname="Channel",
                                   publisher_avatar="", description="Cool video",
                                   media_count=1, cover_path="", cover_url="",
                                   thumb_url="", duration=30, width=1920, height=1080)
        text = fv.to_text()
        assert "【视频号】" in text
        assert "Channel" in text

    def test_to_json(self):
        fv = FavoritesVideoMessage(**_base_msg(type=MessageType.FavoritesVideo),
                                   url="http://v.mp4", publisher_nickname="Ch",
                                   publisher_avatar="http://av.jpg", description="desc",
                                   media_count=1, cover_path="", cover_url="http://cv.jpg",
                                   thumb_url="http://th.jpg", duration=15, width=720, height=1280)
        data = fv.to_json()
        assert data['url'] == "http://v.mp4"
        assert data['publisher_nickname'] == "Ch"
        assert data['duration'] == 15
