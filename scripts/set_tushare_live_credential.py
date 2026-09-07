"""Prompt without echo and store the Tushare token in Windows Credential Manager."""

from __future__ import annotations

import argparse
import getpass

from trade_plan_monitor.live_certification import DEFAULT_CREDENTIAL_TARGET
from trade_plan_monitor.windows_credentials import write_windows_generic_credential


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credential-target", default=DEFAULT_CREDENTIAL_TARGET)
    arguments = parser.parse_args()
    value = getpass.getpass("Tushare token (input hidden): ")
    try:
        material = bytearray(value.encode("ascii", errors="strict"))
    except UnicodeEncodeError:
        print("Credential rejected: the token must contain printable ASCII only.")
        return 2
    value = ""
    if not material or any(not 0x21 <= byte <= 0x7E for byte in material):
        for index in range(len(material)):
            material[index] = 0
        print("Credential rejected: the token must contain printable ASCII only.")
        return 2
    try:
        write_windows_generic_credential(arguments.credential_target, material)
    finally:
        for index in range(len(material)):
            material[index] = 0
    print("Credential stored in Windows Credential Manager.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
