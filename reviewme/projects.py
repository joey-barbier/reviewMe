"""Configuration par PROJET et specs de reviewers (ADR v3, D1/D2/D4).

L'unité de configuration est le **projet**, pas le reviewer : un dossier
`config/projects/<repo>/` porte ses guidelines ET ses reviewers complets (persona incluse).
Deux teams sur deux produits écrivent des personas réellement différentes — il n'y a donc
volontairement AUCUN héritage entre projets (cf. ADR v3 D1). Seul le contrat de sortie
reste au core (`config/output-contract.md`, D1bis) : c'est une interface avec le parseur,
pas du contenu éditorial.

Arborescence attendue :

    config/
      output-contract.md                 <- core, non surchargeable
      projects/
        <repo>/
          common/*.md                    <- consignes communes aux reviewers du projet
          reviewers/                     <- LA source de vérité : un dossier = un reviewer
            tech/{reviewer.toml, system.md}
            us/{reviewer.toml, system.md}

Rétro-compatibilité : sans `PROJECT`, on fabrique un projet virtuel à un seul reviewer
(`tech`) qui lit les anciens emplacements (`config/prompts/system.md`,
`config/guidelines/<pack>/`). Un déploiement v0.2 continue donc de tourner à l'identique.
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from pathlib import PurePosixPath

from .config import CONFIG_DIR, GUIDELINES_DIR, PROMPTS_DIR, Config

#: Emplacement par défaut des projets (dans le repo du core).
PROJECTS_DIR = CONFIG_DIR / "projects"
TEMPLATES_DIR = CONFIG_DIR / "templates"


def projects_dir(config=None) -> Path:
    """Où vivent les projets (ADR v3 D12).

    `REVIEWME_CONFIG_HOME` pointe un dépôt de configuration EXTERNE (un dépôt par organisation) :
    le core reste alors intact et `git pull`-able, la config de projets vit dans son propre
    dépôt versionné à part. Sans cette variable, on retombe sur `config/projects/` du repo.
    C'est délibérément un chemin, pas un submodule : un submodule ramène exactement les
    frictions d'un fork (init, update, HEAD détachée) qu'on cherche à éviter.
    """
    home = (getattr(config, "config_home", "") or os.environ.get("REVIEWME_CONFIG_HOME", "")).strip()
    if home:
        return Path(home).expanduser() / "projects"
    return PROJECTS_DIR
#: Contrat de sortie du core. Cherché à la racine de `config/`, puis à l'ancien emplacement.
_CONTRACT_CANDIDATES = (CONFIG_DIR / "output-contract.md", PROMPTS_DIR / "output-contract.md")

OUTPUT_MODES = ("inline", "global", "mixed")


class ProjectConfigError(RuntimeError):
    """Config de projet absente ou invalide — on préfère échouer tôt et clairement."""


@dataclass(frozen=True)
class ReviewerSpec:
    """Un reviewer tel que déclaré par un projet."""
    id: str
    project: str
    system_prompt: str                     # contenu de system.md (la persona, propre au projet)
    output_mode: str = "inline"            # inline | global | mixed  (ADR v3 D2)
    when_paths: tuple[str, ...] = ()       # globs ; vide = se déclenche toujours (D4 niveau 2)
    requires: tuple[str, ...] = ()         # contextes obligatoires, ex. ("jira_ticket",)
    priority: int = 100                    # ordre d'exécution : petit = prioritaire (D8)
    max_budget_usd: float | None = None    # None = budget global de la Config
    precheck: str = ""                     # script déterministe optionnel (D7)
    common: str = ""                       # consignes communes du projet (langue, ton, format)
    directory: Path | None = None          # dossier du reviewer (résolution du precheck)
    enabled: bool = True                   # False = présent mais mis en sommeil
    context_read: tuple[str, ...] = ()     # fichiers/dossiers de conventions à lire DANS le
                                           # dépôt reviewé (D13) — jamais recopiés ici
    plugins_marketplaces: tuple[str, ...] = ()   # marketplaces Claude Code à déclarer
    plugins_install: tuple[str, ...] = ()        # plugins à installer avant la review

    def budget(self, config: Config) -> float:
        return self.max_budget_usd if self.max_budget_usd is not None else config.max_budget_usd


@dataclass(frozen=True)
class ProjectConfig:
    name: str
    directory: Path | None
    reviewers: tuple[ReviewerSpec, ...] = field(default_factory=tuple)
    legacy: bool = False                   # True = projet virtuel de rétro-compat v0.2

    def reviewer(self, reviewer_id: str) -> ReviewerSpec | None:
        return next((r for r in self.reviewers if r.id == reviewer_id), None)


# --------------------------------------------------------------------------- chargement

def load_output_contract() -> str:
    """Le contrat JSON du core (D1bis). Non surchargeable par un projet."""
    for candidate in _CONTRACT_CANDIDATES:
        if candidate.exists():
            return candidate.read_text(encoding="utf-8")
    return ""


def _read_toml(path: Path) -> dict:
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except tomllib.TOMLDecodeError as e:
        raise ProjectConfigError(f"{path} : TOML invalide ({e})") from e


def _concat_markdown(directory: Path) -> str:
    if not directory.is_dir():
        return ""
    parts = [f"### {md.stem}\n{md.read_text(encoding='utf-8')}"
             for md in sorted(directory.glob("*.md"))]
    return "\n\n".join(parts)


def _load_common(project_dir: Path) -> str:
    """Consignes COMMUNES aux reviewers d'un projet (langue, ton, format des remarques).

    Ce n'est PAS l'endroit où recopier les conventions de code du projet : celles-ci vivent
    déjà dans le dépôt à reviewer (`AGENTS.md`, `CONTRIBUTING.md`, docs internes) et l'agent
    les lit à la source avec Read/Grep — une copie ici divergerait silencieusement du repo
    dès la première évolution. On ne met ici que ce qui n'existe nulle part dans le repo.
    """
    for folder in ("common", "guidelines"):        # `guidelines/` : ancien nom, encore accepté
        content = _concat_markdown(project_dir / folder)
        if content:
            return content
    return ""


def _load_reviewer(project_name: str, project_dir: Path, reviewer_id: str,
                   common: str) -> ReviewerSpec:
    rdir = project_dir / "reviewers" / reviewer_id
    system_file = rdir / "system.md"
    if not system_file.exists():
        raise ProjectConfigError(f"reviewer '{reviewer_id}' : `system.md` manquant dans {rdir}")

    data = _read_toml(rdir / "reviewer.toml") if (rdir / "reviewer.toml").exists() else {}
    mode = str(data.get("output_mode", "inline")).lower()
    if mode not in OUTPUT_MODES:
        raise ProjectConfigError(
            f"reviewer '{reviewer_id}' : output_mode '{mode}' inconnu (attendu : {', '.join(OUTPUT_MODES)})")

    when = data.get("when", {}) or {}
    context = data.get("context", {}) or {}
    plugins = data.get("plugins", {}) or {}
    budget = data.get("max_budget_usd")

    return ReviewerSpec(
        id=reviewer_id,
        project=project_name,
        system_prompt=system_file.read_text(encoding="utf-8"),
        output_mode=mode,
        when_paths=tuple(when.get("paths", ()) or ()),
        requires=tuple(data.get("requires", ()) or ()),
        priority=int(data.get("priority", 100)),
        max_budget_usd=float(budget) if budget is not None else None,
        precheck=str(data.get("precheck", "")),
        common=common,
        directory=rdir,
        enabled=bool(data.get("enabled", True)),
        context_read=tuple(context.get("read", ()) or ()),
        plugins_marketplaces=tuple(plugins.get("marketplaces", ()) or ()),
        plugins_install=tuple(plugins.get("install", ()) or ()),
    )


def load_project(name: str, base_dir: Path | None = None) -> ProjectConfig:
    """Charge `<projets>/<name>/`. Lève ProjectConfigError si la config est invalide."""
    root = base_dir or projects_dir()
    pdir = root / name
    if not pdir.is_dir():
        available = sorted(p.name for p in root.iterdir()
                           if p.is_dir() and not p.name.startswith(".")) if root.is_dir() else []
        raise ProjectConfigError(
            f"projet '{name}' introuvable dans {root}"
            + (f" (disponibles : {', '.join(available)})" if available else ""))

    # Les reviewers sont les DOSSIERS de `reviewers/` — pas une liste à tenir à jour ailleurs.
    # Un manifeste séparé serait une seconde source de vérité : y oublier un dossier le rendrait
    # silencieusement inactif. Pour mettre un reviewer en sommeil sans le supprimer :
    # `enabled = false` dans son `reviewer.toml`.
    rroot = pdir / "reviewers"
    if not rroot.is_dir():
        # Un dossier de projet totalement vide = submodule git non initialisé neuf fois sur
        # dix. Le dire, sinon le message parle d'un `reviewers/` manquant et envoie chercher
        # au mauvais endroit.
        if not any(pdir.iterdir()):
            raise ProjectConfigError(
                f"projet '{name}' : dossier vide ({pdir}). S'il s'agit d'un submodule git, "
                f"l'initialiser : `git submodule update --init --recursive`")
        raise ProjectConfigError(f"projet '{name}' : dossier `reviewers/` manquant dans {pdir}")

    ids = sorted(d.name for d in rroot.iterdir() if d.is_dir() and not d.name.startswith("."))
    if not ids:
        raise ProjectConfigError(
            f"projet '{name}' : aucun reviewer dans {rroot} "
            f"(un sous-dossier par reviewer, ex. `reviewers/tech/`)")

    common = _load_common(pdir)
    specs = tuple(_load_reviewer(name, pdir, rid, common) for rid in ids)
    active = tuple(s for s in specs if s.enabled)
    if not active:
        raise ProjectConfigError(
            f"projet '{name}' : tous les reviewers sont désactivés (`enabled = false`)")

    return ProjectConfig(name=name, directory=pdir, reviewers=active)


def _legacy_project(config: Config) -> ProjectConfig:
    """Projet virtuel reproduisant le comportement v0.2 (un seul reviewer `tech`)."""
    system = (PROMPTS_DIR / "system.md")
    pack_dir = GUIDELINES_DIR / config.guidelines_pack
    if not pack_dir.is_dir():
        pack_dir = GUIDELINES_DIR / "_default"
    spec = ReviewerSpec(
        id=config.reviewer_id or "tech",
        project="(legacy)",
        system_prompt=system.read_text(encoding="utf-8") if system.exists() else "",
        output_mode="inline",
        common=_concat_markdown(pack_dir),
    )
    return ProjectConfig(name="(legacy)", directory=None, reviewers=(spec,), legacy=True)


def resolve_project(config: Config) -> ProjectConfig:
    """Le projet actif : `config.project` s'il est défini, sinon le projet virtuel v0.2."""
    return load_project(config.project, projects_dir(config)) if config.project else _legacy_project(config)


# --------------------------------------------------------------------------- sélection

def _matches(path: str, patterns: tuple[str, ...]) -> bool:
    p = PurePosixPath(path)
    return any(p.full_match(pat) for pat in patterns)


def select_reviewers(project: ProjectConfig, changed_paths: list[str],
                     available_context: set[str] | None = None) -> tuple[list[ReviewerSpec], list[tuple[ReviewerSpec, str]]]:
    """Applique le déclenchement par PR (ADR v3 D4, niveau 2).

    Renvoie (retenus, [(écarté, raison)]). Sans ce filtre, CHAQUE PR paierait tous les
    reviewers du projet — c'est le principal levier de coût du fan-out.
    """
    available = available_context or set()
    kept: list[ReviewerSpec] = []
    skipped: list[tuple[ReviewerSpec, str]] = []

    for spec in sorted(project.reviewers, key=lambda s: (s.priority, s.id)):
        missing = [r for r in spec.requires if r not in available]
        if missing:
            skipped.append((spec, f"contexte manquant : {', '.join(missing)}"))
            continue
        if spec.when_paths and not any(_matches(p, spec.when_paths) for p in changed_paths):
            skipped.append((spec, "aucun fichier du diff ne correspond à when.paths"))
            continue
        kept.append(spec)

    return kept, skipped
