"""P0-only lossless scalar frames. Never imported by production modules."""

from dataclasses import dataclass
from struct import pack, unpack_from

from trade_plan_monitor.state.index_evidence import RawIndexCandidate

MIB = 1024 * 1024
LIMIT, RESERVE, FRAME = 64 * MIB, 16 * MIB, MIB
RAW_CHUNK, TEXT_CHUNK, OUTPUT = 2 * MIB, MIB, MIB


class AdmissionError(ValueError):
    """Select the unchanged thread path before submitting any evidence."""


class ProtocolError(ValueError):
    """Transport cannot certify a complete, correctly bound input."""


@dataclass(frozen=True)
class Plan:
    chunks: tuple
    raw_bytes: int
    external_bytes: int
    reserved: int


def copy_bound(wire, raw, text):
    # Two child generations, original decoded text, IPC/encoding overlap and output.
    return 8 * wire + 2 * raw + 2 * text + 2 * OUTPUT + MIB


def scalar_bound(value):
    if value is None or type(value) is bool:
        return 1, 80
    if type(value) is int and -(2**63) <= value < 2**63:
        return 9, 80
    if type(value) in (str, bytes):
        length = len(value) * (4 if type(value) is str else 1)
        return 5 + length, 80 + length * (4 if type(value) is str else 1)
    raise AdmissionError("unsupported scalar")


def row_bound(row):
    if (type(row) is not RawIndexCandidate or type(row.head) is not tuple
            or len(row.head) != 7 or type(row.json_is_text) is not bool
            or (row.payload is not None
                and (type(row.payload) is not tuple or len(row.payload) != 12))):
        raise AdmissionError("unsupported candidate shape")
    wire, raw, text = 2, 512, 0
    for values in (row.head, row.payload):
        for value in values or ():
            size, retained = scalar_bound(value)
            wire += size
            raw += retained
    if row.payload is not None and row.json_is_text:
        value = row.payload[9]
        if type(value) is not bytes:
            raise AdmissionError("unsupported text representation")
        text = 80 + 4 * len(value)
    return wire, raw, text


def plan(rows, *, external_bytes=0):
    if type(external_bytes) is not int or external_bytes < 0:
        raise AdmissionError("invalid external lease")
    raw_bytes = sum(row.retained_size() for row in rows)
    reserved = raw_bytes + external_bytes + RESERVE
    if reserved > LIMIT:
        raise AdmissionError("aggregate budget exceeded")
    chunks, start = [], 0
    wire, raw, text = 4, 0, 0
    output_bound = {}
    for i, row in enumerate(rows):
        w, r, t = row_bound(row)
        if (w + 4 > FRAME or r > RAW_CHUNK or t > TEXT_CHUNK
                or copy_bound(w+4, r, t) > RESERVE):
            raise AdmissionError("candidate exceeds frame envelope")
        if (wire+w > FRAME or raw+r > RAW_CHUNK or text+t > TEXT_CHUNK
                or copy_bound(wire+w, raw+r, text+t) > RESERVE):
            chunks.append((start, i))
            start, wire, raw, text = i, 4, 0, 0
        wire, raw, text = wire+w, raw+r, text+t
        if row.payload is not None:
            # Selected result JSON is bounded conservatively before child submission.
            code = row.head[1]
            if type(code) is not str:
                raise AdmissionError("unsupported index identity")
            output_bound[code] = max(output_bound.get(code, 0), w * 4 + 1024)
    if start < len(rows):
        chunks.append((start, len(rows)))
    if sum(output_bound.values()) > OUTPUT or len(chunks) * 128 > MIB // 2:
        raise AdmissionError("output or plan exceeds reservation")
    return Plan(tuple(chunks), raw_bytes, external_bytes, reserved)


def encode(rows):
    data = bytearray(pack('!I', len(rows)))
    for row in rows:
        data.extend((int(row.json_is_text), int(row.payload is not None)))
        for values in (row.head, row.payload):
            for value in values or ():
                if value is None:
                    data.append(0)
                elif type(value) is bool:
                    data.append(2 if value else 1)
                elif type(value) is int:
                    data.append(3)
                    data.extend(pack('!q', value))
                elif type(value) in (str, bytes):
                    blob = value.encode('utf8') if type(value) is str else value
                    data.append(4 if type(value) is str else 5)
                    data.extend(pack('!I', len(blob)))
                    data.extend(blob)
                else:
                    raise AdmissionError("unsupported scalar")
        if len(data) > FRAME:
            raise AdmissionError("unplanned oversized frame")
    return data


def decode(data):
    if len(data) > FRAME:
        raise ProtocolError("oversized frame")
    offset = 0

    def take(length):
        nonlocal offset
        if length < 0 or offset + length > len(data):
            raise ProtocolError("truncated frame")
        value = memoryview(data)[offset:offset+length]
        offset += length
        return value

    def integer():
        return unpack_from('!I', take(4))[0]

    def scalar():
        tag = take(1)[0]
        if tag == 0:
            return None
        if tag in (1, 2):
            return tag == 2
        if tag == 3:
            return unpack_from('!q', take(8))[0]
        if tag in (4, 5):
            value = bytes(take(integer()))
            try:
                return value.decode('utf8') if tag == 4 else value
            except UnicodeError as error:
                raise ProtocolError("invalid text encoding") from error
        raise ProtocolError("unknown scalar tag")

    count = integer()
    if count > FRAME // 21:
        raise ProtocolError("invalid row count")
    rows = []
    for _ in range(count):
        text, present = take(2)
        if text not in (0, 1) or present not in (0, 1):
            raise ProtocolError("invalid flags")
        head = tuple(scalar() for _ in range(7))
        payload = tuple(scalar() for _ in range(12)) if present else None
        rows.append(RawIndexCandidate(head, payload, bool(text)))
    if offset != len(data):
        raise ProtocolError("trailing bytes")
    return tuple(rows)
