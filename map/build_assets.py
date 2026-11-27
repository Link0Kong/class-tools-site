"""Build the shared campus data and verify the four bundled copies."""

import argparse
import json
import math
import re
from pathlib import Path

from indoor import BUILDINGS as INDOOR


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
HTML = HERE / 'campus_final_25d.html'
OFFLINE = (
    ROOT / 'android-class-tools/app/src/main/assets/map/campus_final_25d.html',
    ROOT / 'harmony-class-tools/entry/src/main/resources/rawfile/map/campus_final_25d.html',
)
MP = ROOT / 'mp-class-tools/pages/map'
WIN = ROOT / 'windows-class-tools/src/ClassTools.App/Assets/campus_map.json'
ORIGINS = {'south': ['正大门', [326, 458]], 'east': ['东侧门', [692, 399]], 'dorm': ['宿舍区', [200, 250]]}
METERS_PER_UNIT = 0.9


def js(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/')


def project(point, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    fraction = ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / (dx * dx + dy * dy)
    t = max(0, min(1, fraction))
    return t, (a[0] + dx * t, a[1] + dy * t)


def intersection(a, b, c, d):
    dx, dy = b[0] - a[0], b[1] - a[1]
    ex, ey = d[0] - c[0], d[1] - c[1]
    det = dx * ey - dy * ex
    if abs(det) < 1e-8:
        return None
    t = ((c[0] - a[0]) * ey - (c[1] - a[1]) * ex) / det
    u = ((c[0] - a[0]) * dy - (c[1] - a[1]) * dx) / det
    if 0 <= t <= 1 and 0 <= u <= 1:
        return t, u, (a[0] + t * dx, a[1] + t * dy)
    return None


def road_network(buildings, roads):
    road_names = [road['name'] for road in roads]
    segments = [(index, a, b, [(0, a), (1, b)]) for index, road in enumerate(roads)
                for a, b in zip(road['p'], road['p'][1:]) if math.dist(a, b) > 0.05]
    connectors = []
    for i, (road, a, b, parts) in enumerate(segments):
        for other_road, c, d, other_parts in segments[i + 1:]:
            if road == other_road or max(a[0], b[0]) < min(c[0], d[0]) or max(c[0], d[0]) < min(a[0], b[0]):
                continue
            if max(a[1], b[1]) < min(c[1], d[1]) or max(c[1], d[1]) < min(a[1], b[1]):
                continue
            hit = intersection(a, b, c, d)
            if hit:
                t, u, point = hit
                parts.append((t, point))
                other_parts.append((u, point))

    def nearest(points, exclude=None):
        best = None
        for point in points:
            for road, a, b, parts in segments:
                if road == exclude:
                    continue
                t, target = project(point, a, b)
                distance = math.dist(point, target)
                if best is None or distance < best[0]:
                    best = (distance, t, target, parts)
        return best

    # Small endpoint gaps in the surveyed centerlines are expected at junctions.
    for index, road in enumerate(roads):
        for point in (road['p'][0], road['p'][-1]):
            distance, t, target, parts = nearest([point], exclude=index)
            if distance <= 3.5:
                parts.append((t, target))
                connectors.append((point, target))

    anchors = {key: [point] for key, (_, point) in ORIGINS.items()}
    anchors.update({b['id']: [b['entry']] if 'entry' in b else b['p'] for b in buildings})
    stops = {}
    points = []
    indexes = {}

    def node(point):
        key = tuple(round(v, 1) for v in point)
        if key not in indexes:
            indexes[key] = len(points)
            points.append(key)
        return indexes[key]

    for key, candidates in anchors.items():
        _, t, target, parts = nearest(candidates)
        parts.append((t, target))
        stops[key] = node(target)

    edges = set()

    def edge(a, b, road):
        start, end = sorted([node(a), node(b)])
        if start != end:
            edges.add((start, end, road))

    for road, _, _, parts in segments:
        path = sorted(parts, key=lambda split: split[0])
        for (_, a), (_, b) in zip(path, path[1:]):
            edge(a, b, road)
    for a, b in connectors:
        edge(a, b, -1)
    return {'p': points, 'e': sorted(edges), 'stops': stops, 'names': road_names,
            'origins': {key: name for key, (name, _) in ORIGINS.items()}, 'scale': METERS_PER_UNIT}


def compile_data():
    data = json.loads((HERE / 'campus_final_25d_data.json').read_text(encoding='utf-8'))
    corrections = json.loads((HERE / 'building_corrections.json').read_text(encoding='utf-8'))
    buildings = {building['id']: building for building in data['buildings']}
    if set(corrections) - set(buildings):
        raise ValueError('unknown building corrections')
    for key, update in corrections.items():
        building = buildings[key]
        building.update({k: v for k, v in update.items() if k not in ('evidence', 'note')})
        if 'm' in update:
            building['h'] = round(update['m'] / METERS_PER_UNIT, 2)
        elif 'fl' in update:
            building['h'] = round(update['fl'] * 3.05, 2)
        for part in building.get('parts', []):
            meters = part.get('m', building['m'] * part['fl'] / building['fl'])
            part['h'] = round(meters / METERS_PER_UNIT, 2)
    for feature in data['features']:
        if feature['id'] in buildings:
            feature['p'] = buildings[feature['id']]['p']
    data['indoor'] = INDOOR
    data['walk'] = road_network(data['buildings'], data['roads'])
    return data


def build(check=False):
    data = compile_data()
    logic = (HERE / 'campus_logic.js').read_text(encoding='utf-8').strip()
    html = HTML.read_text(encoding='utf-8')
    html, count = re.subn(r'(?m)^var DATA = .*?;?$', lambda _: f'var DATA = {js(data)};', html)
    if count != 1:
        raise ValueError('map data marker missing')
    html, count = re.subn(r'(?s)(/\* campus logic begin \*/\n).*?(/\* campus logic end \*/)',
                          lambda match: match[1] + logic + '\n' + match[2], html)
    if count != 1:
        raise ValueError('map logic markers missing')
    native = {k: v for k, v in data.items() if k not in ('bg', 'next')}
    mp_data = {k: v for k, v in native.items() if k not in ('src', 'features', 'bridges')}
    mp_data['water'] = [{'p': shape['p']} for shape in data['features'] if shape['k'] == 'water']
    files = {HTML: html, **dict.fromkeys(OFFLINE, html), WIN: js(native) + '\n',
             MP / 'campus_map.js': 'module.exports = ' + js(mp_data) + ';\n',
             MP / 'campus_logic.js': logic + '\n'}
    for path, contents in files.items():
        if check:
            if path.read_text(encoding='utf-8') != contents:
                raise ValueError(f'out of date: {path}')
        else:
            path.write_text(contents, encoding='utf-8', newline='\n')
    print(f'{len(data["buildings"])} buildings, {len(data["walk"]["p"])} road nodes, {len(files)} matching assets')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    build(parser.parse_args().check)
