"""W07 offline contract examples. Run with python -B tools/tests/test_water_shared_v2.py.

The in-memory tables model the current composite key, upsert and hard delete.
W08/W09 must additionally run the JSON vectors through their actual clients.
"""

import json
import re
import unittest
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from pathlib import Path


CASES = json.loads(Path(__file__).with_name("water_shared_v2_cases.json").read_text(encoding="utf-8"))
TRIP = CASES["journey"]
MONTH = TRIP["month"]
NEXT = TRIP["nextMonth"]
ROOM, OTHER_ROOM = TRIP["rooms"]
ALICE, BOB = TRIP["accounts"]
UNKNOWN = object()  # Different from None, which represents an observed absence.


def valid_people(value):
    return type(value) is int and 1 <= value <= 6


def parse_rows(room, rows):
    result = {}
    for row in rows:
        if not isinstance(row, dict) or row.get("roomverify") != room:
            raise ValueError("unexpected room")
        month = row.get("month", "")
        if not isinstance(month, str) or not re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])", month):
            raise ValueError("invalid month")
        reading = Decimal(str(row.get("reading")))
        if not reading.is_finite() or reading < 0 or not valid_people(row.get("persons")):
            raise ValueError("invalid reading or persons")
        if month in result:
            raise ValueError("duplicate month in a full response")
        result[month] = {"reading": float(reading), "persons": row["persons"]}
    return result


def parse_people(room, rows):
    if not rows:
        return 4
    if len(rows) != 1 or not isinstance(rows[0], dict) or rows[0].get("roomverify") != room:
        raise ValueError("unexpected room")
    value = rows[0].get("persons")
    if not valid_people(value):
        raise ValueError("invalid persons")
    return value


def replay_decision(source, base, current, desired, outcome_unknown=False):
    if source not in ("user", "confirmed-import"):
        return "review"
    if current == desired:
        return "satisfied"
    if outcome_unknown or base is UNKNOWN or current != base:
        return "review"
    return "send"


class PendingWrites:
    """One outstanding user intent per account, room and month (None is the people key)."""
    def __init__(self):
        self.entries = {}
        self.last_id = 0

    def replace(self, account, room, month, desired):
        self.last_id += 1
        key = account, room, month
        self.entries[key] = (self.last_id, desired)
        return key, self.last_id

    def acknowledge(self, ticket, sent_context, active_context):
        key, operation_id = ticket
        entry = self.entries.get(key)
        if sent_context == active_context and key[:2] == active_context[:2] and entry and entry[0] == operation_id:
            del self.entries[key]


class Tables:
    def __init__(self):
        self.rows = {}
        self.people = {}
        self.writes = []

    def write(self, room, month, value):
        if month is None:
            self.people[room] = value
            resource, method = "water_room", "POST"
        elif value is None:
            self.rows.pop((room, month), None)
            resource, method = "water", "DELETE"
        else:
            self.rows[room, month] = dict(value)
            resource, method = "water", "POST"
        self.writes.append((method, resource, room, month, value))

    def get_room(self, room):
        rows = [
            dict(roomverify=rv, month=m, **value)
            for (rv, m), value in sorted(self.rows.items()) if rv == room
        ]
        people = [{"roomverify": room, "persons": self.people[room]}] if room in self.people else []
        return ("complete", rows), ("complete", people)


class ClientView:
    def __init__(self, account, room):
        self.sequence = 0
        self.cache = {}
        self.select(account, room)

    def select(self, account, room):
        self.account, self.room = account, room
        self.sequence += 1

    def start_read(self):
        self.sequence += 1
        return self.account, self.room, self.sequence

    @property
    def view(self):
        if not self.account:
            return {}
        return self.cache.get((self.account, self.room), {})

    def accept(self, request, records, people):
        if not self.account or request != (self.account, self.room, self.sequence):
            return (False, False)
        accepted = []
        for key, packet, parse in (("records", records, parse_rows), ("persons", people, parse_people)):
            status, rows = packet
            if status != "complete" or not isinstance(rows, list):
                accepted.append(False)
                continue
            try:
                value = parse(self.room, rows)
            except (ValueError, InvalidOperation):
                accepted.append(False)
                continue
            self.cache.setdefault((self.account, self.room), {})[key] = value
            accepted.append(True)
        return tuple(accepted)

    def refresh(self, tables):
        return self.accept(self.start_read(), *tables.get_room(self.room))


class WaterSharedV2(unittest.TestCase):
    def test_two_clients_remove_then_restore_network(self):
        db = Tables()
        a, b = ClientView(ALICE, ROOM), ClientView(BOB, ROOM)
        db.write(ROOM, MONTH, TRIP["first"])
        db.write(ROOM, None, TRIP["serverPersons"])
        a.refresh(db)
        b.refresh(db)
        self.assertEqual(a.view, b.view)
        self.assertEqual(b.view, {"records": {MONTH: TRIP["first"]}, "persons": 3})
        private_history = deepcopy(b.view["records"])

        db.write(ROOM, MONTH, None)
        writes_before = len(db.writes)
        for _ in range(2):  # First foreground read and subsequent reconnect.
            b.refresh(db)
        expected = TRIP["afterDeleteRefresh"]
        self.assertEqual(sorted(b.view["records"]), expected["months"])
        self.assertEqual(b.view["persons"], expected["persons"])
        self.assertEqual(len(db.writes) - writes_before, expected["sharedWrites"])
        self.assertEqual(private_history, {MONTH: TRIP["first"]})

        # A confirmed new month entered offline can be sent exactly once in this sequence.
        operation = dict(source="user", base=None, desired=TRIP["next"])
        for _ in range(2):
            current = db.rows.get((ROOM, NEXT))
            if replay_decision(current=current, **operation) == "send":
                db.write(ROOM, NEXT, operation["desired"])
        b.refresh(db)
        expected = TRIP["afterOfflineCreate"]
        self.assertEqual(sorted(b.view["records"]), expected["months"])
        self.assertEqual(len(db.writes) - writes_before, expected["sharedWrites"])
        self.assertEqual(db.writes[-1], ("POST", "water", ROOM, NEXT, TRIP["next"]))

        # v1 accepted the same upsert from an inferred missing month as from a new user entry.
        writes_before = len(db.writes)
        for month, row in private_history.items():
            if (ROOM, month) not in db.rows:
                db.write(ROOM, month, row)
        a.refresh(db)
        expected = TRIP["afterLegacyReconnect"]
        self.assertEqual(sorted(a.view["records"]), expected["months"])
        self.assertEqual(len(db.writes) - writes_before, expected["sharedWrites"])
        self.assertEqual(db.writes[-1], ("POST", "water", ROOM, MONTH, TRIP["first"]))

    def test_complete_empty_partial_error_and_cache_only(self):
        packets = {
            "complete-empty": ("complete", []),
            "complete-3": ("complete", [{"roomverify": ROOM, "persons": 3}]),
            "failed": ("failed", []),
            "ttl-skip": ("cached", []),
            "partial": ("partial", []),
            "foreign-row": ("complete", [dict(roomverify=OTHER_ROOM, month=MONTH, **TRIP["first"])]),
            "invalid": ("complete", None),
        }
        for case in CASES["refreshCases"]:
            with self.subTest(case=case["id"]):
                db = Tables()
                db.write(ROOM, MONTH, TRIP["first"])
                db.write(ROOM, None, 5)
                b = ClientView(BOB, ROOM)
                b.refresh(db)
                success = b.accept(b.start_read(), packets[case["records"]], packets[case["people"]])
                self.assertEqual(list(success), case["confirmed"])
                self.assertEqual(sorted(b.view["records"]), case["expectMonths"])
                self.assertEqual(b.view["persons"], case["expectPersons"])
                self.assertEqual(len(db.writes), 2)

    def test_persons_range_and_absence(self):
        self.assertEqual(parse_people(ROOM, []), CASES["persons"]["absentDefault"])
        for value in CASES["persons"]["valid"]:
            with self.subTest(people=value):
                self.assertEqual(parse_people(ROOM, [{"roomverify": ROOM, "persons": value}]), value)
                row = dict(roomverify=ROOM, month=MONTH, reading="0.00", persons=value)
                self.assertEqual(parse_rows(ROOM, [row])[MONTH], {"reading": 0, "persons": value})
        for value in CASES["persons"]["invalid"]:
            with self.subTest(people=value), self.assertRaises(ValueError):
                parse_people(ROOM, [{"roomverify": ROOM, "persons": value}])

    def test_explicit_intent_and_recovery(self):
        for case in CASES["replayCases"]:
            with self.subTest(case=case["id"]):
                decision = replay_decision(case["source"], case.get("base", UNKNOWN), case["current"],
                                           case["desired"], case.get("outcomeUnknown", False))
                self.assertEqual(decision, case["decision"])

    def test_older_ack_cannot_clear_newer_or_other_owner_intent(self):
        queue = PendingWrites()
        save = queue.replace(ALICE, ROOM, MONTH, TRIP["first"])
        delete = queue.replace(ALICE, ROOM, MONTH, None)
        people = queue.replace(ALICE, ROOM, None, 3)
        other = queue.replace(BOB, OTHER_ROOM, MONTH, TRIP["next"])
        original = deepcopy(queue.entries)
        sent_context = (ALICE, ROOM, 1)
        queue.acknowledge(save, sent_context, sent_context)
        queue.acknowledge(delete, sent_context, (BOB, OTHER_ROOM, 2))
        verified_context = (ALICE, ROOM, 3)
        queue.acknowledge(delete, sent_context, verified_context)
        self.assertEqual(queue.entries, original)
        # A fresh read in the new context confirms that this same key is already absent.
        queue.acknowledge(delete, verified_context, verified_context)
        self.assertEqual(set(queue.entries), {people[0], other[0]})

    def test_context_and_read_order(self):
        db = Tables()
        db.write(ROOM, MONTH, TRIP["first"])
        a = ClientView(ALICE, ROOM)
        old_request, old_response = a.start_read(), db.get_room(ROOM)
        a.select(ALICE, OTHER_ROOM)
        a.refresh(db)
        expected = deepcopy(a.cache)
        self.assertEqual(a.accept(old_request, *old_response), (False, False))
        self.assertEqual(a.cache, expected)
        a.select(BOB, ROOM)
        self.assertEqual(a.accept(old_request, *old_response), (False, False))
        self.assertEqual(a.view, {})

        # A newer read wins, even for the same account and room.
        a.select(ALICE, ROOM)
        first = a.start_read()
        db.write(ROOM, MONTH, None)
        a.refresh(db)
        a.accept(first, *old_response)
        self.assertEqual(a.view["records"], {})
        still_in_flight = a.start_read()
        a.select(None, ROOM)
        self.assertEqual(a.accept(still_in_flight, *old_response), (False, False))
        self.assertEqual(a.view, {})
        a.select(ALICE, ROOM)
        self.assertEqual(a.accept(still_in_flight, *old_response), (False, False))
        self.assertEqual(len(db.writes), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
