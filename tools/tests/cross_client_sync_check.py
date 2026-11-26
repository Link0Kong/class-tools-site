"""Run real Web and WeChat client flows against one isolated REST fixture (Python, Edge, Node 22+)."""
import argparse
import json
import subprocess
from contextlib import contextmanager
from pathlib import Path

from _test_account import TEST_SID
from sync_browser_fixture import browser_fixture, click, wait
from task_cloud_check import TaskService, hold_write, quick, sync
from v2_web_batch2_water_cloud_check import MONTH, NEXT, R, S, WaterService, choose, listed, persons, pull, save, wait_idle, water_html


@contextmanager
def mini_program(root, endpoint):
    script = Path(__file__).with_name('cross_sync_peer.cjs')
    proc = subprocess.Popen(['node', str(script), str(root.resolve()), endpoint],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding='utf-8')
    try:
        def command(op, **fields):
            proc.stdin.write(json.dumps(dict(op=op, **fields)) + '\n')
            proc.stdin.flush()
            result = json.loads(proc.stdout.readline())
            if 'error' in result:
                raise AssertionError(result['error'])
            return result['result']
        yield command
    finally:
        proc.stdin.close()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        proc.stdout.close()


def task_journey(root):
    service = TaskService()
    with browser_fixture(service) as tab, mini_program(root, tab.endpoint) as mp:
        page = tab()
        mp('login', sid=TEST_SID, token='fixture-rotate')
        wait(page, "TASKSYNC.state().status.includes('暂无可见')")
        page.evaluate("__diag.gotoTab('hw');TASK.setSeg('my')")
        quick(page, 'web-first')
        hold_write(page)
        assert not mp('task-add', id='mp-first', title='mp-first')['state']['dirty']
        page.evaluate('release()')
        wait(page, "TASKSYNC.state().status==='已同步'")
        assert service.collisions == 1
        result = mp('task-pull')
        assert {row['title'] for row in result['items']} == {'web-first', 'mp-first'}

        homework = {'id':'qa-source-hw', 'subject':'QA', 'content':'source'}
        page.evaluate('TASK.addFromHW(' + json.dumps(homework) + ')')
        hold_write(page)
        mp('task-homework', id=homework['id'])
        page.evaluate('release()')
        wait(page, "TASKSYNC.state().status==='已同步'")
        copies = [row for row in service.leaf()['items'] if row.get('sourceHwId') == homework['id']]
        assert len(copies) == 1
        task_id = copies[0]['id']
        assert any(row['id'] == task_id and row['done'] for row in mp('task-done', id=task_id)['items'])
        assert sync(page)
        assert page.evaluate('TASK.items().some(t=>t.id===' + json.dumps(task_id) + '&&t.done)')
        page.evaluate('TASK.open(' + json.dumps(task_id) + ')')
        click(page, '#tkFDelete')
        assert sync(page)
        after = mp('task-edit', id=task_id, title='离线旧改')
        assert all(row['id'] != task_id for row in after['items'])
        assert sync(page) and not page.evaluate("TASK.linkedHW('qa-source-hw')")
        assert not page.evaluate('jsErrors')
        print(f'V05 Web + MP: two first writes converged, one homework copy, completion visible, stale edit after deletion dropped ({service.collisions} CAS conflicts)')


def water_journey(root):
    service = WaterService()
    with browser_fixture(service, water_html()) as tab, mini_program(root, tab.endpoint) as mp:
        page = tab()
        mp('login', sid='9999000012', token='fixture-b')
        choose(page, R)
        assert pull(page)
        empty = mp('water-room', room=R)
        assert not empty['room']['recs'] and service.writes() == 0
        persons(page, 3)
        wait_idle(page)
        save(page, MONTH, 12.34)
        wait_idle(page)
        shared = mp('water-refresh')['room']
        assert shared['p'] == 3
        assert [(r['m'], r['r']) for r in shared['recs']] == [(MONTH, 12.34)]
        click(page, '[data-wdel=' + json.dumps(MONTH) + ']')
        wait_idle(page)
        writes = service.writes()
        assert not mp('water-refresh')['room']['recs']
        assert not mp('water-room', room=R)['room']['recs']
        assert pull(page) and not listed(page) and service.writes() == writes
        mp('water-save', month=NEXT, reading=20.5)
        assert service.writes() == writes + 1
        assert pull(page) and listed(page) == [NEXT] and service.rows[R, NEXT]['reading'] == 20.5
        choose(page, S)
        assert pull(page, S) and not listed(page) and not mp('water-room', room=S)['room']['recs']
        assert service.writes() == writes + 1 and not page.evaluate('jsErrors')
        print(f'V09 Web + MP: shared persons and readings, deletion survives refresh/reopen, explicit new month visible, second room isolated ({service.writes()} explicit writes)')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mp-root', type=Path, default=Path(__file__).resolve().parents[3] / 'mp-class-tools')
    parser.add_argument('--suite', choices=['all', 'task', 'water'], default='all')
    args = parser.parse_args()
    if args.suite in ('all', 'task'):
        task_journey(args.mp_root)
    if args.suite in ('all', 'water'):
        water_journey(args.mp_root)
