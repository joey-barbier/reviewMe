"""Prechecks déterministes (ADR v3 D7) : établir des FAITS avant d'appeler le LLM.

Principe : ce qu'un script sait prouver ne doit pas être payé à un modèle. « La clé
`checkout.title` existe en `fr` et manque en `de` » est un fait vérifiable, gratuit et
sans faux positif ; le LLM n'intervient que sur ce qui demande du jugement (wording, ton,
variable non substituée, cohérence avec l'existant).

Un reviewer déclare son script dans `reviewer.toml` :

    precheck = "precheck.py"

Le script vit dans le dossier du reviewer, reçoit le repo à analyser via `--repo`, et écrit
sur stdout un bloc markdown injecté tel quel dans le prompt.

⚠️ SÉCURITÉ : un precheck est du CODE fourni par le projet, exécuté par le core. Sur une
config contribuée par des équipes, il doit passer par la même revue qu'un changement de
code (cf. ADR v3 D10) et le sandbox de déploiement reste la mitigation de fond.
"""
from __future__ import annotations

import logging
import subprocess
import sys

from .config import Config
from .projects import ReviewerSpec

_TIMEOUT_S = 120
_MAX_OUTPUT = 20_000  # au-delà, ce n'est plus un « fait établi » mais un dump : on tronque


def run_precheck(spec: ReviewerSpec, config: Config, logger: logging.Logger) -> str:
    """Exécute le precheck du reviewer. Renvoie son bloc de faits, ou "" si indisponible.

    Ne lève jamais : un precheck cassé dégrade la review (le LLM juge seul), il ne
    l'interrompt pas.
    """
    if not spec.precheck or spec.directory is None:
        return ""

    script = spec.directory / spec.precheck
    if not script.exists():
        logger.warning("[%s] precheck '%s' introuvable (%s)", spec.id, spec.precheck, script)
        return ""

    cmd = ([sys.executable, str(script)] if script.suffix == ".py" else [str(script)])
    cmd += ["--repo", config.repo_path]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=_TIMEOUT_S, cwd=config.repo_path, check=False)
    except subprocess.TimeoutExpired:
        logger.warning("[%s] precheck : timeout après %ds", spec.id, _TIMEOUT_S)
        return ""
    except OSError as e:
        logger.warning("[%s] precheck : impossible de lancer %s (%s)", spec.id, script.name, e)
        return ""

    if proc.returncode != 0:
        logger.warning("[%s] precheck : code %s — %s", spec.id, proc.returncode,
                       (proc.stderr or "").strip()[:300])
        return ""

    out = (proc.stdout or "").strip()
    if not out:
        return ""
    if len(out) > _MAX_OUTPUT:
        logger.info("[%s] precheck : sortie tronquée (%d car.)", spec.id, len(out))
        out = out[:_MAX_OUTPUT] + "\n\n_(sortie tronquée)_"

    logger.info("[%s] precheck : %d car. de faits établis injectés", spec.id, len(out))
    return f"# Faits établis par analyse déterministe (fiables — produits par notre outillage)\n\n{out}"
