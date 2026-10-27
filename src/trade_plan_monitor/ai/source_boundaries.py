"""Finite A/B markers identify provenance partitions, never blanket waivers."""

import re

from trade_plan_monitor.domain.daily_hash import canonical

PARTITION_MARKERS = {
    "A. 执行计划": "A", "B. 背景说明": "B",
    "A. Executable plan": "A", "B. Background": "B",
}


def source_partitions(source):
    return tuple((line.start(), PARTITION_MARKERS[line.group().strip()])
                 for line in re.finditer(r"[^\r\n]+", source)
                 if line.group().strip() in PARTITION_MARKERS)


def partition_at(partitions, position):
    active = "A"
    for start, label in partitions:
        if start > position:
            break
        active = label
    return active


def repeats_executable(declaration, declarations, partitions):
    return any(row.start < declaration.start and partition_at(partitions, row.start) == "A"
               and row.path == declaration.path
               and canonical(row.value) == canonical(declaration.value)
               for row in declarations)
