"""Strict local wheel auditing for isolated qualification experiments."""

import base64
import csv
import hashlib
import io
import ntpath
import stat
import zipfile


def audit_wheel(path):
    with zipfile.ZipFile(path) as wheel:
        names = wheel.namelist()
        if len(set(names)) != len(names):
            raise ValueError("duplicate wheel member")
        targets = {name.casefold() for name in names}
        if len(targets) != len(names):
            raise ValueError("colliding wheel members")
        for entry in wheel.infolist():
            name = entry.filename
            parts = name.split("/")
            if "\\" in name or any(p in ("", ".", "..") or ntpath.isreserved(p) for p in parts):
                raise ValueError("unsafe wheel member")
            if stat.S_IFMT(entry.external_attr >> 16) not in (0, stat.S_IFREG):
                raise ValueError("unsafe wheel member")
            if any("/".join(parts[:i]).casefold() in targets for i in range(1, len(parts))):
                raise ValueError("colliding wheel members")
        records = [n for n in names if n.endswith(".dist-info/RECORD")]
        if len(records) != 1:
            raise ValueError("expected one RECORD")
        record = records[0]
        rows = list(csv.reader(io.StringIO(wheel.read(record).decode("utf8"))))
        seen = set()
        hashes = {}
        for row in rows:
            if len(row) != 3 or row[0] in seen or row[0] not in names:
                raise ValueError("invalid RECORD entry")
            name, expected, size = row
            seen.add(name)
            data = wheel.read(name)
            hashes[name] = hashlib.sha256(data).hexdigest()
            if name == record:
                if expected or size:
                    raise ValueError("invalid RECORD self entry")
                continue
            digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
            if expected != "sha256=" + digest or size != str(len(data)):
                raise ValueError("RECORD hash or size mismatch")
        if seen != set(names):
            raise ValueError("incomplete RECORD")
    return {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "members": hashes}
