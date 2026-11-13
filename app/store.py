"""Tiny JSON-file store for SCIM users/groups plus an event log.

Deliberately simple: this is a lab target app, not a production directory.
"""
import json
import os
import threading
import uuid
from datetime import datetime, timezone

from . import config

_lock = threading.Lock()


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Store:
    def __init__(self, path=None):
        self.path = path or os.path.join(config.DATA_DIR, "scim.json")
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.data = {"Users": {}, "Groups": {}, "events": []}
        if os.path.exists(self.path):
            with open(self.path) as f:
                self.data = json.load(f)

    def _save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.data, f, indent=2)
        os.replace(tmp, self.path)

    # --- generic resource ops -------------------------------------------
    def list(self, rtype):
        return list(self.data[rtype].values())

    def get(self, rtype, rid):
        return self.data[rtype].get(rid)

    def create(self, rtype, resource):
        with _lock:
            rid = str(uuid.uuid4())
            resource["id"] = rid
            resource["meta"] = {
                "resourceType": rtype[:-1],
                "created": _now(),
                "lastModified": _now(),
                "location": f"{config.BASE_URL}/scim/v2/{rtype}/{rid}",
            }
            self.data[rtype][rid] = resource
            self._save()
            return resource

    def replace(self, rtype, rid, resource):
        with _lock:
            existing = self.data[rtype][rid]
            resource["id"] = rid
            resource["meta"] = {**existing["meta"], "lastModified": _now()}
            self.data[rtype][rid] = resource
            self._save()
            return resource

    def delete(self, rtype, rid):
        with _lock:
            self.data[rtype].pop(rid, None)
            self._save()

    def touch(self, rtype, rid):
        with _lock:
            self.data[rtype][rid]["meta"]["lastModified"] = _now()
            self._save()

    # --- audit trail shown on the dashboard -----------------------------
    def log(self, action, detail):
        with _lock:
            self.data["events"].insert(0, {"at": _now(), "action": action, "detail": detail})
            self.data["events"] = self.data["events"][:200]
            self._save()

    def reset(self):
        with _lock:
            self.data = {"Users": {}, "Groups": {}, "events": []}
            self._save()
