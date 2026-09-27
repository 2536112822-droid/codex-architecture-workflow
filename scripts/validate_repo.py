"""Validate the distributable package without connecting to desktop apps."""
from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
NAMES = {'architecture-studio', 'architecture-aesthetics', 'site-analysis',
         'su-model', 'cad-tz-model', 'rhino-model'}


def main():
    errors = []
    marketplace = json.loads((ROOT / '.agents/plugins/marketplace.json').read_text(encoding='utf-8-sig'))
    entries = marketplace['plugins']
    if {entry['name'] for entry in entries} != NAMES or len(entries) != len(NAMES):
        errors.append('Marketplace must contain the six public plugins exactly once')
    for entry in entries:
        plugin = ROOT / entry['source']['path']
        path = plugin / '.codex-plugin/plugin.json'
        manifest = json.loads(path.read_text(encoding='utf-8-sig'))
        if manifest['name'] != entry['name'] or manifest.get('license') != 'MIT':
            errors.append(f'{path.relative_to(ROOT)}: identity or license mismatch')
        if entry['policy'] != {'installation': 'AVAILABLE', 'authentication': 'ON_INSTALL'}:
            errors.append(f'{entry["name"]}: unexpected installation policy')
        for key in ('skills', 'mcpServers', 'apps'):
            if isinstance(manifest.get(key), str) and not (plugin / manifest[key]).exists():
                errors.append(f'{entry["name"]}: missing {key} path')
        for key in ('logo', 'composerIcon'):
            if manifest.get('interface', {}).get(key) and not (plugin / manifest['interface'][key]).is_file():
                errors.append(f'{entry["name"]}: missing {key}')
        skill = plugin / 'skills' / entry['name'] / 'SKILL.md'
        if not skill.is_file() or not skill.read_text(encoding='utf-8-sig').startswith('---'):
            errors.append(f'{entry["name"]}: missing skill or frontmatter')
    count = 0
    for path in sorted(ROOT.rglob('*')):
        rel = path.relative_to(ROOT)
        if any(part in {'.git', '.venv', '__pycache__', 'work', 'outputs', 'node_modules'} for part in rel.parts):
            continue
        if not path.is_file():
            continue
        count += 1
        if path.suffix.lower() in {'.dll', '.pdb', '.db', '.sqlite', '.skp', '.dwg', '.3dm', '.pem', '.key'}:
            errors.append(f'{rel}: non-source or sensitive artifact')
            continue
        try:
            content = path.read_text(encoding='utf-8-sig')
        except UnicodeDecodeError:
            continue
        if path.suffix == '.py':
            try:
                ast.parse(content, filename=str(rel))
            except SyntaxError as exc:
                errors.append(f'{rel}: {exc}')
        if path.suffix == '.json':
            try:
                json.loads(content)
            except ValueError as exc:
                errors.append(f'{rel}: {exc}')
        for pattern in (r'gh[pousr]_[A-Za-z0-9]{30,}', r'github_pat_[A-Za-z0-9_]{40,}',
                        r'-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----'):
            if re.search(pattern, content):
                errors.append(f'{rel}: possible credential')
        if path.suffix == '.md':
            for target in re.findall(r'(?<!!)\[[^\]]*\]\(([^)]+)\)', content):
                target = target.split('#', 1)[0].strip('<>')
                if not target or re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:', target) or '<' in target:
                    continue
                if not (path.parent / unquote(target)).exists():
                    errors.append(f'{rel}: missing local link {target}')
    for required in ('README.md', 'README.en.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md',
                     'docs/INSTALL.md', 'docs/BRIDGES.md', 'docs/WORKFLOW.md', 'templates/AGENTS.architecture.md'):
        if not (ROOT / required).is_file():
            errors.append(f'Missing {required}')
    print(json.dumps({'files_checked': count, 'plugins': len(entries), 'errors': errors}, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
