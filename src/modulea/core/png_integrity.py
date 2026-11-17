"""标准库PNG原件核验；复用原验收包的尺寸/CRC规则，不绘图或加载Pillow。"""
import zlib
from contracts import require


def png_size(raw):
    """检查已登记PNG各块CRC和尺寸，不在HTTP进程加载绘图依赖或重画。"""
    require(raw.startswith(b'\x89PNG\r\n\x1a\n'), '登记PNG格式错误')
    at = 8;ended = False;size = None
    while at + 12 <= len(raw):
        count = int.from_bytes(raw[at:at + 4], 'big');tag = raw[at + 4:at + 8];chunk = raw[at + 8:at + 8 + count]
        require(at + 12 + count <= len(raw) and zlib.crc32(tag + chunk) ==
                int.from_bytes(raw[at + 8 + count:at + 12 + count], 'big'), '登记PNG块长度或CRC错误')
        if tag == b'IHDR':size = [int.from_bytes(chunk[:4], 'big'), int.from_bytes(chunk[4:8], 'big')]
        at += count + 12
        if tag == b'IEND':ended = True;break
    require(ended and at == len(raw) and size and all(x > 0 for x in size), '登记PNG缺少完整图像')
    return size
