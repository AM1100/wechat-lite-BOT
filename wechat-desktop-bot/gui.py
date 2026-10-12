"""Adapter for the observed Linux WeChat AT-SPI/X11 layout."""
import ctypes as C
import ctypes.util
import time
from collections import deque
from probe_chat import session, Pixels


class SendDeferred(RuntimeError):
    """No send click occurred; the already-generated reply can be retained safely."""


class SendUncertain(RuntimeError):
    def __init__(self, detail, rows):
        super().__init__(detail)
        self.rows = list(rows)


def incoming_only_change(previous, current):
    """Allow appended incoming texts without starving a ready reply during a burst."""
    from main import suffix_new
    before = [r for r in previous if r[0] != 'ignore']
    after = [r for r in current if r[0] != 'ignore']
    if before == after:
        return True
    new = suffix_new(before, after)
    return new is not None and all(kind == 'in' for kind, text in new)


def classify(name, sample):
    # Unsupported rows never reach the model. This is intentionally conservative.
    media = ('Image', 'Animated Stickers', 'Sticker', 'Video', 'Voice', 'File',
             '[Photo]', '[图片]', '[视频]', '[语音]', '[文件]', '图片', '表情', '动画表情')
    import re
    if not name or name.startswith(media) or re.fullmatch(r'(?:.*\s)?\d{1,2}:\d{2}', name):
        return 'ignore'
    if sample.get('status'):
        return 'unknown'
    green = sample.get('green_samples_left_right', [0, 0])
    if green[1] >= 12 and green[0] < 5:
        return 'out'
    # Actual received-text bubble colors from the user's two-way test.
    gray = sum(count for rgb, count in sample.get('common_rgb_left', [])
               if tuple(rgb) in ((232, 232, 240), (224, 224, 232)))
    if gray >= 20 and max(green) < 5:
        return 'in'
    return 'unknown'


class Gui:
    def __init__(self):
        self.pid = session()
        import gi
        gi.require_version('Atspi', '2.0')
        from gi.repository import Atspi
        self.A = Atspi
        Atspi.set_timeout(1000, 1000)
        Atspi.init()
        desktop = Atspi.get_desktop(0)
        self.app = next(a for a in (desktop.get_child_at_index(i)
                                    for i in range(desktop.get_child_count()))
                        if a and a.get_process_id() == self.pid)
        self.pixels = Pixels()
        self.xt = None

    def rect(self, node):
        try:
            r = node.get_component_iface().get_extents(self.A.CoordType.SCREEN)
            return (r.x, r.y, r.width, r.height)
        except Exception:
            return (0, 0, 0, 0)

    def visible(self, node):
        r = self.rect(node)
        return r[2] > 0 and r[3] > 0 and node.get_state_set().contains(self.A.StateType.SHOWING)

    def scan(self):
        self.app.clear_cache()
        # Qt can reorder valid children after a restart. Always start at the app root.
        todo = deque([(self.app, 0)])
        lists, editors, send, chats, headers = [], [], [], [], []
        count = 0
        errors = {}
        while todo and count < 6000:
            node, depth = todo.popleft()
            count += 1
            try:
                name, role = node.get_name() or '', node.get_role_name()
                if self.visible(node):
                    if role == 'list' and name in ('Messages', '消息'):
                        lists.append(node)
                    elif role == 'list' and name in ('Chats', '聊天'):
                        chats.append(node)
                    elif role in ('text', 'entry') and name not in ('Search', '搜索'):
                        if node.get_editable_text_iface() is not None:
                            editors.append(node)
                    elif role == 'button' and name in ('Send', '发送'):
                        send.append(node)
                    elif role == 'label' and name:
                        headers.append(node)
                if depth < 40 and not (role == 'list' and name in ('Messages', '消息', 'Chats', '聊天')):
                    for i in range(min(node.get_child_count(), 100)):
                        child = node.get_child_at_index(i)
                        if child is not None:
                            todo.append((child, depth+1))
                if len(lists) == len(editors) == len(send) == 1 and chats:
                    ename, vr = editors[0].get_name(), self.rect(lists[0])
                    if any(h.get_name() == ename and self.rect(h)[0] >= vr[0]
                           and self.rect(h)[1] < vr[1] for h in headers):
                        break
            except Exception as exc:
                key = type(exc).__name__
                errors[key] = errors.get(key, 0) + 1
                continue
        if len(lists) != 1 or len(editors) != 1 or len(send) != 1:
            raise RuntimeError('Cannot locate chat controls: messages=%d editors=%d send=%d chats=%d scanned=%d errors=%s' %
                               (len(lists), len(editors), len(send), len(chats), count, errors))
        listing, editor, button = lists[0], editors[0], send[0]
        name, viewport = editor.get_name() or '', self.rect(listing)
        # Confirm header independently; do not trust stale editor nodes alone.
        matching = [h for h in headers if h.get_name() == name
                    and self.rect(h)[0] >= viewport[0]
                    and self.rect(h)[1] < viewport[1]]
        if len(matching) != 1:
            raise RuntimeError('Chat header and editor do not match uniquely')
        rows = []
        total = listing.get_child_count()
        for i in range(max(0, total-60), total):
            row = listing.get_child_at_index(i)
            if row is None:
                continue
            r = self.rect(row)
            # Fully visible rows only; a partial bubble cannot establish direction.
            if r[1] < viewport[1] or r[1]+r[3] > viewport[1]+viewport[3]:
                continue
            text = row.get_name() or ''
            kind = classify(text, self.pixels.sample(r, viewport))
            rows.append((kind, text))
        targets = {}
        for chatlist in chats:
            for i in range(chatlist.get_child_count()):
                row = chatlist.get_child_at_index(i)
                if row is not None and self.visible(row):
                    label = (row.get_name() or '').split('\n')[0]
                    targets.setdefault(label, []).append(self.rect(row))
        draft_iface = editor.get_text_iface()
        draft = self.A.Text.get_text(draft_iface, 0, draft_iface.get_character_count())
        return {'name': name, 'rows': rows, 'editor': editor, 'send': button,
                'draft': draft, 'targets': targets}

    def click(self, rect):
        if self.xt is None:
            self.xt = C.CDLL(ctypes.util.find_library('Xtst') or 'libXtst.so.6')
            self.xt.XTestFakeMotionEvent.argtypes = [C.c_void_p, C.c_int, C.c_int, C.c_int, C.c_ulong]
            self.xt.XTestFakeButtonEvent.argtypes = [C.c_void_p, C.c_uint, C.c_int, C.c_ulong]
            self.pixels.lib.XSync.argtypes = [C.c_void_p, C.c_int]
        x, y, w, h = rect
        if min(w, h) <= 0:
            raise RuntimeError('Invalid click target')
        d = self.pixels.display
        self.xt.XTestFakeMotionEvent(d, -1, x+w//2, y+h//2, 0)
        self.xt.XTestFakeButtonEvent(d, 1, 1, 0)
        self.xt.XTestFakeButtonEvent(d, 1, 0, 0)
        self.pixels.lib.XSync(d, 0)

    def select(self, name, snapshot):
        if snapshot['name'] == name:
            return snapshot
        if snapshot['draft']:
            raise RuntimeError('Current editor has a draft; chat switching paused')
        targets = snapshot['targets'].get(name, [])
        if len(targets) != 1:
            raise RuntimeError('Whitelisted chat is missing or duplicated in visible Chats list')
        self.click(targets[0])
        time.sleep(0.5)
        current = self.scan()
        if current['name'] != name:
            raise RuntimeError('Selected chat does not match requested name')
        return current

    def send_reply(self, name, text, expected_rows, still_allowed):
        current = self.scan()
        if current['name'] != name or current['draft'] or not incoming_only_change(expected_rows, current['rows']):
            raise SendDeferred('Chat changed, new messages appeared, or editor has a draft; send deferred')
        if not still_allowed():
            raise SendDeferred('Reply disabled or configuration changed; send deferred')
        editor = current['editor']
        if not editor.get_editable_text_iface().set_text_contents(text):
            raise RuntimeError('WeChat rejected editable-text insertion')
        time.sleep(0.2)
        current = self.scan()
        if (current['name'] != name or current['draft'] != text
                or not incoming_only_change(expected_rows, current['rows']) or not still_allowed()):
            if current['name'] == name and current['draft'] == text:
                # Clear only our own verified, unsent draft; never touch a user's changed draft.
                if current['editor'].get_editable_text_iface().set_text_contents(''):
                    raise SendDeferred('New messages/configuration before send; own draft cleared, reply retained')
            raise RuntimeError('Draft verification failed; no send click performed')
        button = current['send']
        if not button.get_state_set().contains(self.A.StateType.ENABLED):
            if current['editor'].get_editable_text_iface().set_text_contents(''):
                raise SendDeferred('Send button not yet enabled; own unsent draft cleared, reply retained')
            raise RuntimeError('Send button is disabled; draft left unsent')
        before_send = current['rows']
        try:
            self.click(self.rect(button))
            for _ in range(4):
                time.sleep(0.6)
                result = self.scan()
                from main import reply_observed
                if result['name'] == name and reply_observed(before_send, result, text):
                    return result
        except Exception as exc:
            raise SendUncertain('Post-click confirmation interrupted: ' + type(exc).__name__, before_send) from None
        raise SendUncertain('Clicked send but new outgoing bubble not yet confirmed', before_send)

    def close(self):
        self.pixels.close()
