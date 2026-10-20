"""PLANEXIUM bridge to the installed YATRA/VISTA Motion V3 engine."""
from contextlib import ExitStack
import hashlib
import importlib.util
import json
from pathlib import Path
import textwrap


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fingerprint(tools):
    library = Path(tools) / 'motion_v3'
    digest = hashlib.sha256()
    for name in ['layout_grammar.py', 'card_renderer.py', 'cards.html']:
        path = library / name
        if not path.is_file():
            raise FileNotFoundError('Installed shared Motion V3 library is incomplete: ' + name)
        digest.update(name.encode()); digest.update(path.read_bytes())
    for path in sorted((library / 'vendor').rglob('*')):
        if path.is_file():
            digest.update(path.relative_to(library).as_posix().encode()); digest.update(path.read_bytes())
    digest.update(Path(__file__).read_bytes())
    return digest.hexdigest()


class SharedMotion:
    def __init__(self, root, tools, family):
        self.root = Path(root)
        self.library = Path(tools) / 'motion_v3'
        self.library_hash = fingerprint(tools)
        self.grammar = load_module(self.library / 'layout_grammar.py', 'planexium_installed_grammar')
        self.cards = load_module(self.library / 'card_renderer.py', 'planexium_installed_cards')
        self.history = self.root.parent / 'direction-history'
        self.family = family
        self.resources = ExitStack()
        self.renderer = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.resources.close()

    def plan(self, shots):
        selected = [(i, s) for i, s in enumerate(shots, 1) if s.get('callout') and s['kind'] != 'primary']
        request = hashlib.sha256(json.dumps({'library': self.library_hash, 'family': self.family,
            'shots': [(i, s['scene'], s['frames'], s['callout']) for i, s in selected]}, sort_keys=True).encode()).hexdigest()
        path = self.root / 'edit/shared-director-plan.json'
        if path.exists():
            prior = json.loads(path.read_text(encoding='utf-8'))
            if prior['request_hash'] == request:
                self.receipt = prior
                return {int(k): v for k, v in prior['specs'].items()}
        recent = self.grammar.recent_signatures(self.history)
        used, usage, specs = set(), {}, {}
        world = {'format_family': self.family, 'visual_world': 'planexium-science',
                 'rules': {'palettes': ['monsoon', 'paper'], 'motifs': ['orbit', 'soft-particles', 'contour']}}
        for ordinal, shot in selected:
            spec = {'template': 'lower', 'overlay': True, 'duration': shot['frames'] / 30,
                    'lines': textwrap.wrap(shot['callout'], 28), 'size': 64,
                    'brand': False, 'kicker': '', 'sub': '', 'note': ''}
            specs[ordinal] = self.grammar.direct(spec, {'family': 'obs', 'layout': 'evidence', 'headline': shot['callout']},
                video_id='planexium:' + self.root.name, scene_id=str(shot['scene']), beat_id=str(ordinal),
                recent=recent, used=used, usage=usage, world=world)
        report = self.grammar.similarity_report(list(specs.values()), recent)
        if specs and (not report['ok'] or report['unique_compositions'] < min(4, len(specs))):
            raise ValueError('Shared director failed PLANEXIUM overlay diversity')
        self.receipt = {'request_hash': request, 'library_sha256': self.library_hash,
                        'brand': 'planexium', 'weekday_format': self.family, 'specs': specs, 'similarity': report,
                        'visible_integration': ['composition', 'palette', 'motif', 'shared lower-third GSAP animation'],
                        'not_claimed': ['full-screen weekday effects', 'all camera/entrance/exit direction dimensions']}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.receipt, indent=2), encoding='utf-8')
        return specs

    def render(self, spec, filters, media, target):
        if self.renderer is None:
            self.renderer = self.resources.enter_context(self.cards.CardRenderer())
        self.renderer.render_over(spec, filters + '[base]', media, Path(target))

    def finish(self):
        self.history.mkdir(parents=True, exist_ok=True)
        report = {**self.receipt['similarity'], 'video_id': 'planexium:' + self.root.name,
                  'library_sha256': self.library_hash,
                  'beats': [s['direction'] for s in self.receipt['specs'].values()]}
        (self.history / (self.root.name + '.json')).write_text(json.dumps(report, indent=2), encoding='utf-8')
