"""Dependency-free QR code encoder (byte mode, error correction level M) with PNG output.

Follows ISO/IEC 18004 (structure after Project Nayuki's reference implementation).
Supports versions 1-10, enough for Kinder Spa payloads (~50 bytes).
"""
import struct
import zlib

ECC_PER_BLOCK = [None, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26]   # level M
NUM_BLOCKS = [None, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5]                # level M
ECL_M_FORMAT = 0


def _raw_modules(ver):
    result = (16 * ver + 128) * ver + 64
    if ver >= 2:
        n = ver // 7 + 2
        result -= (25 * n - 10) * n - 55
        if ver >= 7:
            result -= 36
    return result


def _data_codewords(ver):
    return _raw_modules(ver) // 8 - ECC_PER_BLOCK[ver] * NUM_BLOCKS[ver]


def _gf_mul(x, y):
    z = 0
    for i in reversed(range(8)):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z & 0xFF


def _rs_divisor(degree):
    result = [0] * (degree - 1) + [1]
    root = 1
    for _ in range(degree):
        for j in range(degree):
            result[j] = _gf_mul(result[j], root)
            if j + 1 < degree:
                result[j] ^= result[j + 1]
        root = _gf_mul(root, 0x02)
    return result


def _rs_remainder(data, divisor):
    result = [0] * len(divisor)
    for b in data:
        factor = b ^ result.pop(0)
        result.append(0)
        for i, coef in enumerate(divisor):
            result[i] ^= _gf_mul(coef, factor)
    return result


def _alignment_positions(ver):
    if ver == 1:
        return []
    n = ver // 7 + 2
    step = (ver * 8 + n * 3 + 5) // (n * 4 - 4) * 2
    result = [ver * 4 + 10 - i * step for i in range(n - 1)] + [6]
    return list(reversed(result))


class QrCode:
    def __init__(self, data: bytes):
        for ver in range(1, 11):
            ccbits = 8 if ver < 10 else 16
            if 4 + ccbits + len(data) * 8 <= _data_codewords(ver) * 8:
                break
        else:
            raise ValueError('data too long for QR versions 1-10')
        self.version, self.size = ver, ver * 4 + 17
        bits = []

        def put(val, n):
            bits.extend((val >> i) & 1 for i in reversed(range(n)))
        put(0b0100, 4)
        put(len(data), ccbits)
        for b in data:
            put(b, 8)
        capacity = _data_codewords(ver) * 8
        put(0, min(4, capacity - len(bits)))
        put(0, (-len(bits)) % 8)
        pad = 0xEC
        while len(bits) < capacity:
            put(pad, 8)
            pad ^= 0xEC ^ 0x11
        codewords = [int(''.join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]

        self.modules = [[False] * self.size for _ in range(self.size)]
        self.is_function = [[False] * self.size for _ in range(self.size)]
        self._draw_function_patterns()
        self._draw_codewords(self._add_ecc_and_interleave(codewords))
        best, best_penalty = 0, None
        for mask in range(8):
            self._apply_mask(mask)
            self._draw_format_bits(mask)
            penalty = self._penalty()
            if best_penalty is None or penalty < best_penalty:
                best, best_penalty = mask, penalty
            self._apply_mask(mask)  # undo (XOR)
        self._apply_mask(best)
        self._draw_format_bits(best)

    # ----------------------------------------------------------- drawing
    def _set_function(self, x, y, dark):
        self.modules[y][x] = dark
        self.is_function[y][x] = True

    def _draw_function_patterns(self):
        size = self.size
        for i in range(size):
            self._set_function(6, i, i % 2 == 0)
            self._set_function(i, 6, i % 2 == 0)
        for cx, cy in ((3, 3), (size - 4, 3), (3, size - 4)):
            for dy in range(-4, 5):
                for dx in range(-4, 5):
                    x, y = cx + dx, cy + dy
                    if 0 <= x < size and 0 <= y < size:
                        dist = max(abs(dx), abs(dy))
                        self._set_function(x, y, dist not in (2, 4))
        pos = _alignment_positions(self.version)
        n = len(pos)
        for i in range(n):
            for j in range(n):
                if (i == 0 and j == 0) or (i == 0 and j == n - 1) or (i == n - 1 and j == 0):
                    continue
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        self._set_function(pos[i] + dx, pos[j] + dy, max(abs(dx), abs(dy)) != 1)
        self._draw_format_bits(0)
        if self.version >= 7:
            rem = self.version
            for _ in range(12):
                rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
            bits = self.version << 12 | rem
            for i in range(18):
                bit = (bits >> i) & 1 == 1
                a, b = size - 11 + i % 3, i // 3
                self._set_function(a, b, bit)
                self._set_function(b, a, bit)

    def _draw_format_bits(self, mask):
        data = ECL_M_FORMAT << 3 | mask
        rem = data
        for _ in range(10):
            rem = (rem << 1) ^ ((rem >> 9) * 0x537)
        bits = (data << 10 | rem) ^ 0x5412
        bit = lambda i: (bits >> i) & 1 == 1
        for i in range(6):
            self._set_function(8, i, bit(i))
        self._set_function(8, 7, bit(6))
        self._set_function(8, 8, bit(7))
        self._set_function(7, 8, bit(8))
        for i in range(9, 15):
            self._set_function(14 - i, 8, bit(i))
        size = self.size
        for i in range(8):
            self._set_function(size - 1 - i, 8, bit(i))
        for i in range(8, 15):
            self._set_function(8, size - 15 + i, bit(i))
        self._set_function(8, size - 8, True)

    def _add_ecc_and_interleave(self, data):
        ver = self.version
        num_blocks, block_ecc = NUM_BLOCKS[ver], ECC_PER_BLOCK[ver]
        raw = _raw_modules(ver) // 8
        num_short = num_blocks - raw % num_blocks
        short_len = raw // num_blocks
        divisor = _rs_divisor(block_ecc)
        blocks, k = [], 0
        for i in range(num_blocks):
            dat = data[k:k + short_len - block_ecc + (0 if i < num_short else 1)]
            k += len(dat)
            ecc = _rs_remainder(dat, divisor)
            if i < num_short:
                dat = dat + [0]
            blocks.append(dat + ecc)
        result = []
        for i in range(len(blocks[0])):
            for j, blk in enumerate(blocks):
                if i != short_len - block_ecc or j >= num_short:
                    result.append(blk[i])
        return result

    def _draw_codewords(self, data):
        size, i = self.size, 0
        right = size - 1
        while right >= 1:
            if right == 6:
                right = 5
            for vert in range(size):
                for j in range(2):
                    x = right - j
                    upward = ((right + 1) & 2) == 0
                    y = size - 1 - vert if upward else vert
                    if not self.is_function[y][x] and i < len(data) * 8:
                        self.modules[y][x] = (data[i >> 3] >> (7 - (i & 7))) & 1 == 1
                        i += 1
            right -= 2

    def _apply_mask(self, mask):
        fns = [lambda x, y: (x + y) % 2 == 0, lambda x, y: y % 2 == 0, lambda x, y: x % 3 == 0,
               lambda x, y: (x + y) % 3 == 0, lambda x, y: (x // 3 + y // 2) % 2 == 0,
               lambda x, y: x * y % 2 + x * y % 3 == 0, lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0,
               lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0]
        f = fns[mask]
        for y in range(self.size):
            for x in range(self.size):
                if not self.is_function[y][x] and f(x, y):
                    self.modules[y][x] = not self.modules[y][x]

    # ----------------------------------------------------------- penalty (mask choice)
    def _penalty(self):
        size, m, result = self.size, self.modules, 0
        lines = [m[y] for y in range(size)] + [[m[y][x] for y in range(size)] for x in range(size)]
        finder = ([True, False, True, True, True, False, True, False, False, False, False],
                  [False, False, False, False, True, False, True, True, True, False, True])
        for line in lines:
            run_color, run = line[0], 1
            for v in line[1:]:
                if v == run_color:
                    run += 1
                else:
                    if run >= 5:
                        result += run - 2
                    run_color, run = v, 1
            if run >= 5:
                result += run - 2
            for i in range(len(line) - 10):
                if tuple(line[i:i + 11]) in (tuple(finder[0]), tuple(finder[1])):
                    result += 40
        for y in range(size - 1):
            for x in range(size - 1):
                c = m[y][x]
                if c == m[y][x + 1] == m[y + 1][x] == m[y + 1][x + 1]:
                    result += 3
        dark = sum(sum(row) for row in m)
        total = size * size
        k = (abs(dark * 20 - total * 10) + total - 1) // total - 1
        result += max(0, k) * 10
        return result

    # ----------------------------------------------------------- output
    def png(self, scale=10, border=4):
        dim = (self.size + border * 2) * scale
        rows = []
        for y in range(-border, self.size + border):
            row = bytearray()
            for x in range(-border, self.size + border):
                dark = 0 <= x < self.size and 0 <= y < self.size and self.modules[y][x]
                row.extend((0 if dark else 255,) * scale)
            rows.extend([b'\x00' + bytes(row)] * scale)

        def chunk(kind, payload):
            return struct.pack('!I', len(payload)) + kind + payload + struct.pack('!I', zlib.crc32(kind + payload) & 0xFFFFFFFF)
        header = struct.pack('!IIBBBBB', dim, dim, 8, 0, 0, 0, 0)
        return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', header) +
                chunk(b'IDAT', zlib.compress(b''.join(rows), 9)) + chunk(b'IEND', b''))


def qr_png(text, scale=10, border=4):
    return QrCode(text.encode('utf-8')).png(scale, border)
