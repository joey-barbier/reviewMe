#!/usr/bin/env python3
"""Precheck i18n : compare les clés de traduction entre langues (ADR v3 D7).

Ce que ce script établit est un FAIT — une clé est présente ou absente, il n'y a rien à
juger. Le faire ici plutôt qu'au LLM, c'est gratuit, instantané et sans faux positif ; le
modèle garde ce qui demande vraiment du jugement (wording, variables, pluriels, longueur).

Formats reconnus : `.strings` (iOS), `strings.xml` (Android), `.json` (web/JS).
Sortie : markdown sur stdout, injecté tel quel dans le prompt du reviewer.

Usage : precheck.py --repo /chemin/du/clone
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

MAX_FILES = 400          # garde-fou : au-delà, le dépôt n'est pas structuré comme prévu
MAX_REPORTED = 25        # au-delà, on résume : un mur de clés n'aide personne

_STRINGS_RE = re.compile(r'^\s*"((?:[^"\\]|\\.)*)"\s*=', re.MULTILINE)
_IOS_LANG_RE = re.compile(r"/([A-Za-z-]+)\.lproj/")
_ANDROID_LANG_RE = re.compile(r"/values(?:-([A-Za-z][\w-]*))?/")
_WEB_LANG_RE = re.compile(r"/(?:locales?|i18n|lang)/([A-Za-z]{2}(?:[-_][A-Za-z]{2})?)(?:/|\.)")


def _flatten(obj, prefix: str = "") -> set[str]:
    keys: set[str] = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            full = f"{prefix}.{k}" if prefix else str(k)
            if isinstance(v, (dict, list)):
                keys |= _flatten(v, full)
            else:
                keys.add(full)
    return keys


def read_keys(path: Path) -> set[str]:
    try:
        if path.suffix == ".strings":
            return set(_STRINGS_RE.findall(path.read_text(encoding="utf-8", errors="replace")))
        if path.name.startswith("strings") and path.suffix == ".xml":
            root = ET.fromstring(path.read_text(encoding="utf-8", errors="replace"))
            return {el.get("name") for el in root.iter() if el.tag in ("string", "plurals")
                    and el.get("name")}
        if path.suffix == ".json":
            return _flatten(json.loads(path.read_text(encoding="utf-8", errors="replace")))
    except (OSError, ValueError, ET.ParseError):
        return set()
    return set()


def detect(path: Path) -> tuple[str, str] | None:
    """(langue, bundle) d'un fichier de localisation, ou None si non reconnu."""
    posix = "/" + path.as_posix().lstrip("/")

    if m := _IOS_LANG_RE.search(posix):
        lang = m.group(1)
        return (("en" if lang.lower() in ("base", "en") else lang), path.name)

    if path.name.startswith("strings") and path.suffix == ".xml":
        if m := _ANDROID_LANG_RE.search(posix):
            return (m.group(1) or "default", path.name)

    if path.suffix == ".json":
        if m := _WEB_LANG_RE.search(posix):
            return (m.group(1), path.name)
        if re.fullmatch(r"[a-z]{2}([-_][A-Za-z]{2})?", path.stem):
            return (path.stem, path.parent.name or "locales")
    return None


def collect(repo: Path) -> dict[str, dict[str, set[str]]]:
    """{bundle: {langue: clés}} — un « bundle » = un même fichier décliné par langue."""
    bundles: dict[str, dict[str, set[str]]] = defaultdict(dict)
    seen = 0
    for pattern in ("**/*.strings", "**/strings*.xml", "**/*.json"):
        for path in repo.glob(pattern):
            if not path.is_file() or any(p in {".git", "node_modules", "build", "Pods",
                                               ".build", "vendor", "dist"} for p in path.parts):
                continue
            found = detect(path)
            if not found:
                continue
            lang, bundle = found
            keys = read_keys(path)
            if keys:
                bundles[bundle][lang] = keys
                seen += 1
            if seen >= MAX_FILES:
                return bundles
    return bundles


def report(bundles: dict[str, dict[str, set[str]]]) -> str:
    lines: list[str] = []
    total_missing = 0

    for bundle, per_lang in sorted(bundles.items()):
        if len(per_lang) < 2:
            continue  # une seule langue : rien à comparer
        union: set[str] = set().union(*per_lang.values())
        gaps = {lang: sorted(union - keys) for lang, keys in per_lang.items()}
        gaps = {lang: missing for lang, missing in gaps.items() if missing}
        langs = ", ".join(f"{lang} ({len(keys)})" for lang, keys in sorted(per_lang.items()))

        if not gaps:
            lines.append(f"- **{bundle}** — {len(union)} clés, complet dans toutes les langues : {langs}")
            continue

        total_missing += sum(len(v) for v in gaps.values())
        lines.append(f"- **{bundle}** — {len(union)} clés au total ; langues : {langs}")
        for lang, missing in sorted(gaps.items()):
            shown = ", ".join(f"`{k}`" for k in missing[:MAX_REPORTED])
            more = f" … et {len(missing) - MAX_REPORTED} autres" if len(missing) > MAX_REPORTED else ""
            lines.append(f"  - ❌ **{lang}** : {len(missing)} clé(s) manquante(s) — {shown}{more}")

    if not lines:
        return "Aucun jeu de fichiers de localisation multilingue détecté dans ce dépôt."

    header = ("Toutes les clés sont présentes dans toutes les langues."
              if total_missing == 0 else
              f"**{total_missing} clé(s) manquante(s)** au total.")
    return f"## Complétude des traductions\n\n{header}\n\n" + "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".", help="racine du dépôt à analyser")
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    if not repo.is_dir():
        print(f"Dépôt introuvable : {repo}", file=sys.stderr)
        return 1

    print(report(collect(repo)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
