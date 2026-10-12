#!/usr/bin/env python3
"""Read-only focused check: message metadata, editor/actions, local bubble colors.
Never clicks, types, sends messages, or makes network/model requests.
"""
import ctypes as C
import ctypes.util
import json
import os
from collections import Counter, deque
from pathlib import Path


def session():
    for proc in sorted(Path('/proc').iterdir()):
        if not proc.name.isdigit():
            continue
        try:
            exe = Path(os.fsdecode((proc / 'cmdline').read_bytes().split(b'\0')[0])).name.lower()
            if exe not in ('wechat', 'weixin'):
                continue
            fields = (proc / 'environ').read_bytes().split(b'\0')
            env = dict(os.fsdecode(f).split('=', 1) for f in fields if b'=' in f)
            if not env.get('DBUS_SESSION_BUS_ADDRESS'):
                continue
            for key in ('DISPLAY', 'DBUS_SESSION_BUS_ADDRESS', 'XDG_RUNTIME_DIR', 'XAUTHORITY'):
                if key in env:
                    os.environ[key] = env[key]
                else:
                    os.environ.pop(key, None)
            return int(proc.name)
        except OSError:
            continue
    raise RuntimeError('No readable WeChat session; run with -u abc')


class ImageHeader(C.Structure):
    _fields_ = [(n, t) for n, t in (
        ('width', C.c_int), ('height', C.c_int), ('xoffset', C.c_int),
        ('format', C.c_int), ('data', C.c_void_p), ('byte_order', C.c_int),
        ('bitmap_unit', C.c_int), ('bitmap_bit_order', C.c_int),
        ('bitmap_pad', C.c_int), ('depth', C.c_int), ('bytes_per_line', C.c_int),
        ('bits_per_pixel', C.c_int), ('red_mask', C.c_ulong),
        ('green_mask', C.c_ulong), ('blue_mask', C.c_ulong))]


class Pixels:
    def __init__(self):
        self.lib = C.CDLL(ctypes.util.find_library('X11') or 'libX11.so.6')
        signatures = {
            'XOpenDisplay': ([C.c_char_p], C.c_void_p),
            'XDefaultRootWindow': ([C.c_void_p], C.c_ulong),
            'XDefaultScreen': ([C.c_void_p], C.c_int),
            'XDisplayWidth': ([C.c_void_p, C.c_int], C.c_int),
            'XDisplayHeight': ([C.c_void_p, C.c_int], C.c_int),
            'XGetImage': ([C.c_void_p, C.c_ulong, C.c_int, C.c_int,
                           C.c_uint, C.c_uint, C.c_ulong, C.c_int], C.c_void_p),
            'XGetPixel': ([C.c_void_p, C.c_int, C.c_int], C.c_ulong),
            'XDestroyImage': ([C.c_void_p], C.c_int),
            'XCloseDisplay': ([C.c_void_p], C.c_int),
        }
        for name, (args, result) in signatures.items():
            fn = getattr(self.lib, name)
            fn.argtypes, fn.restype = args, result
        self.display = self.lib.XOpenDisplay(None)
        if not self.display:
            raise RuntimeError('XOpenDisplay failed')
        self.root = self.lib.XDefaultRootWindow(self.display)
        screen = self.lib.XDefaultScreen(self.display)
        self.width = self.lib.XDisplayWidth(self.display, screen)
        self.height = self.lib.XDisplayHeight(self.display, screen)

    def sample(self, row, viewport):
        x, y, w, h = row
        vx, vy, vw, vh = viewport
        left, top = max(x, vx, 0), max(y, vy, 0)
        right, bottom = min(x+w, vx+vw, self.width), min(y+h, vy+vh, self.height)
        if right-left < 120 or bottom-top < 15:
            return {'status': 'clipped_or_offscreen'}
        ptr = self.lib.XGetImage(self.display, self.root, left, top,
                                right-left, bottom-top, C.c_ulong(-1).value, 2)
        if not ptr:
            return {'status': 'capture_failed'}
        try:
            header = C.cast(ptr, C.POINTER(ImageHeader)).contents
            masks = (header.red_mask, header.green_mask, header.blue_mask)
            if not all(masks):
                return {'status': 'unsupported_pixel_format'}
            shifts = [(mask & -mask).bit_length()-1 for mask in masks]
            colors = [Counter(), Counter()]
            green = [0, 0]
            width, height = right-left, bottom-top
            # Exclude edge avatars, sample bubble interiors; report evidence, not sender claims.
            for py in range(6, height-6, 4):
                for px in range(52, width-52, 4):
                    pixel = self.lib.XGetPixel(ptr, px, py)
                    rgb = tuple(((pixel & mask) >> shift)*255//(mask >> shift)
                                for mask, shift in zip(masks, shifts))
                    side = int(px >= width//2)
                    colors[side][tuple(channel//8*8 for channel in rgb)] += 1
                    r, g, b = rgb
                    if g > 140 and g-r > 35 and g-b > 25:
                        green[side] += 1
            return {'green_samples_left_right': green,
                    'common_rgb_left': colors[0].most_common(4),
                    'common_rgb_right': colors[1].most_common(4)}
        finally:
            self.lib.XDestroyImage(ptr)

    def close(self):
        self.lib.XCloseDisplay(self.display)


def emit(label, data):
    print(label + ': ' + json.dumps(data, ensure_ascii=False), flush=True)


def main():
    pid = session()
    import gi
    gi.require_version('Atspi', '2.0')
    from gi.repository import Atspi
    Atspi.set_timeout(1000, 1000)
    Atspi.init()
    desktop = Atspi.get_desktop(0)
    apps = [desktop.get_child_at_index(i) for i in range(desktop.get_child_count())]
    app = next(a for a in apps if a and a.get_process_id() == pid)

    def rect(node):
        try:
            r = node.get_component_iface().get_extents(Atspi.CoordType.SCREEN)
            return (r.x, r.y, r.width, r.height)
        except Exception:
            return (0, 0, 0, 0)

    def metadata(node):
        data = {'role': node.get_role_name(), 'name': (node.get_name() or '')[:500],
                'rect': rect(node)}
        for name, method in [('description', node.get_description),
                             ('attributes', node.get_attributes),
                             ('accessible_id', node.get_accessible_id)]:
            try:
                data[name] = method()
            except Exception as exc:
                data[name] = type(exc).__name__
        try:
            states = node.get_state_set()
            data['states'] = [state.value_nick for state in states.get_states()]
        except Exception:
            pass
        try:
            action = node.get_action_iface()
            data['actions'] = ([action.get_action_name(i) for i in range(action.get_n_actions())]
                               if action else [])
        except Exception:
            pass
        return data

    # Fast starting point from this client's observed tree; root fallback for changed layouts.
    start = app
    try:
        for index in (0, 0, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0, 1):
            start = start.get_child_at_index(index)
            if start is None:
                raise ValueError('missing node')
    except Exception:
        start = app
    todo = deque([(start, 0)])
    messages, editors, send_buttons = [], [], []
    examined = 0
    while todo and examined < 2500:
        node, depth = todo.popleft()
        examined += 1
        try:
            name, role = node.get_name() or '', node.get_role_name()
            r = rect(node)
            if r[2] > 0 and r[3] > 0:
                if role == 'list' and name in ('Messages', '消息'):
                    messages.append(node)
                if role in ('text', 'entry') and name not in ('Search', '搜索'):
                    if node.get_editable_text_iface() is not None:
                        editors.append(node)
                if role == 'button' and name in ('Send', '发送'):
                    send_buttons.append(node)
            if messages and editors and send_buttons:
                break
            # Message rows are examined separately; no need to descend into them here.
            if depth < 28 and not (role == 'list' and name in ('Messages', '消息')):
                for i in range(min(node.get_child_count(), 100)):
                    child = node.get_child_at_index(i)
                    if child is not None:
                        todo.append((child, depth+1))
        except Exception:
            continue
    emit('FOUND', {'message_lists': len(messages), 'editors': len(editors),
                   'send_buttons': len(send_buttons), 'examined': examined})
    for node in editors:
        emit('EDITOR', metadata(node))
    for node in send_buttons:
        emit('SEND_BUTTON', metadata(node))
    pixels = None
    try:
        pixels = Pixels()
    except Exception as exc:
        emit('PIXEL_CHECK', {'error': str(exc)[:160]})
    try:
        for listing in messages:
            viewport = rect(listing)
            emit('MESSAGE_LIST', metadata(listing))
            total = listing.get_child_count()
            for i in range(max(0, total-12), total):
                row = listing.get_child_at_index(i)
                if row is None:
                    continue
                data = metadata(row)
                if pixels:
                    data['bubble_pixels'] = pixels.sample(rect(row), viewport)
                emit('MESSAGE', data)
    finally:
        if pixels:
            pixels.close()
    print('READ_ONLY: no typing, clicks, sending, or model requests.', flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        emit('ERROR', {'type': type(exc).__name__, 'message': str(exc)[:200]})
        raise SystemExit(1)
