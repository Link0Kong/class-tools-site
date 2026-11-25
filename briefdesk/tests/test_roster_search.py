import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sync_roster_search import account_map, digest, lookup_keys


class RosterSearchTest(unittest.TestCase):
    def test_only_public_group_fields_enter_index(self):
        rows = [{"wxid": "wxid_test", "nickname": "Blue 星", "groupNickname": "小蓝",
                 "remark": "private note", "displayName": "private display"}]
        self.assertEqual(lookup_keys(rows, "微信", {"wxid_test": "99990001"}),
                         {("99990001", digest("Blue 星")), ("99990001", digest("小蓝"))})

    def test_stable_accounts_and_full_names_only(self):
        people = [{"sid": "99990001", "qq": [{"uin": "123", "matchBy": "name"}]},
                  {"sid": "99990002", "qq": [{"uin": "123", "matchBy": "name"}, {"uin": "234", "matchBy": "name"}]}]
        owners = account_map(people, "QQ")
        self.assertEqual(owners, {"234": "99990002"})
        rows = [{"uin": "123", "nick": "unresolved"}, {"uin": "234", "nick": " A星光 ", "card": "234"}]
        self.assertEqual(lookup_keys(rows, "QQ", owners), {("99990002", digest("A星光"))})
