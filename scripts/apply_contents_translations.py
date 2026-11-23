#!/usr/bin/env python3
"""Merge scripts/contents_translations.json into a repo's translations.

    python apply_contents_translations.py custom_components/<domain>/translations \
        --copy-fields tracking_code[,<entry selector field>]

For every ``<lang>.json`` in the directory this adds, under ``services``:

* ``track_parcel.fields.contents`` when the file has a ``track_parcel`` service;
* ``update_contents`` with its own ``contents`` field, plus the ``--copy-fields``
  fields copied verbatim from that file's own ``track_parcel`` (the code field
  first, then the entry selector if the repo has one). A repo without
  ``track_parcel`` has nothing to copy: the first field then takes the table's
  generic ``code_field`` text.

A language missing from the table is an error. Run it on ``translations/`` and
then ``cp translations/en.json strings.json``. Idempotent.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

TABLE = Path(__file__).with_name("contents_translations.json")


def merge(data: dict, row: dict, copy_fields: list[str]) -> dict:
    services = data.setdefault("services", {})
    track = services.get("track_parcel")
    if track is not None:
        track.setdefault("fields", {})["contents"] = row["track_parcel_contents"]
    fields: dict = {}
    for index, name in enumerate(copy_fields):
        if track is not None:
            fields[name] = track["fields"][name]
        elif index == 0:
            fields[name] = row["code_field"]
        else:
            raise SystemExit(f"no track_parcel to copy {name!r} from")
    fields["contents"] = row["update_contents_contents"]
    services["update_contents"] = {**row["update_contents"], "fields": fields}
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("translations", type=Path)
    parser.add_argument("--copy-fields", required=True)
    args = parser.parse_args()
    table = json.loads(TABLE.read_text(encoding="utf-8"))
    copy_fields = args.copy_fields.split(",")
    for path in sorted(args.translations.glob("*.json")):
        if path.stem not in table:
            raise SystemExit(f"{path.stem}: not in {TABLE.name}")
        data = json.loads(path.read_text(encoding="utf-8"))
        merged = merge(data, table[path.stem], copy_fields)
        path.write_text(
            json.dumps(merged, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
