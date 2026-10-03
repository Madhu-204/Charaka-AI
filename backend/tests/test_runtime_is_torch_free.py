"""The serving process must not depend on torch. It used to, and Render killed it.

The symptom was a container that started cleanly, served one request, and then
died with no traceback:

    ==> Out of memory (used over 512Mi)

which is what Render prints when it reaps a process over the free tier's memory
cap. Two independent things put torch in that process, and fixing only one of
them would have left the deploy broken:

1. ``app/nodes/retriever.py`` built a ``SentenceTransformer`` at import time,
   even though the corpus vectors are already baked into ``chroma_db/`` and the
   runtime only encodes short queries. That now goes through ``app/embedder.py``
   (ONNX Runtime).

2. ``langchain_core`` does an unconditional
   ``try: from transformers import GPT2TokenizerFast`` while importing
   ``langchain_core.language_models.base``. Having ``transformers`` merely
   *installed* is therefore enough to import all of torch, no matter what the
   application code does — which is why the fix also has to live in the
   dependency list and the Dockerfile, not only in the retriever.

Note what (2) means for testing: on a machine where torch IS installed, simply
importing the app pulls torch in, and that is expected rather than a bug in the
app. So the import test below does not assert "this process avoided importing
torch" — it asserts the stronger, environment-independent property that the app
still imports and answers with torch unavailable, which is what the runtime
image guarantees by not installing it.
"""

import json
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
ROOT = BACKEND.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

TORCH_FAMILY = ("torch", "transformers", "sentence-transformers")

# Runs before the app is imported: makes the torch family unimportable exactly
# as it is on the runtime image, where those packages are not installed.
BLOCK_TORCH = """
import sys


class _Blocker:
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in {"torch", "transformers", "sentence_transformers"}:
            raise ImportError(f"blocked (not installed): {name}")
        return None


sys.meta_path.insert(0, _Blocker())
"""


def _requirement_names(path: Path):
    """Distribution names requested by a requirements file, comments stripped."""
    names = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        # Keep the distribution name: `pkg==1.0`, `pkg>=1`, `pkg[extra]`.
        name = line.split("=", 1)[0].split(">", 1)[0].split("<", 1)[0]
        name = name.split("[", 1)[0].split("~", 1)[0].strip().lower()
        if name:
            names.append(name)
    return names


def _dockerfile_stages(path: Path):
    """Yield (stage_name, body) per FROM, with `\\` line continuations joined.

    The stage name is the `AS` alias when there is one, else the base image, so
    `FROM python:3.11-slim AS index` is reported as `index`.
    """
    text = path.read_text(encoding="utf-8").replace("\\\n", " ")
    stages, name, body = [], None, []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.upper().startswith("FROM "):
            if name is not None:
                stages.append((name, "\n".join(body)))
            parts = stripped.split()
            rest = parts[1:]
            name = (
                rest[rest.index("AS") + 1] if "AS" in rest else (rest[0] if rest else "")
            )
            body = []
        elif name is not None:
            body.append(line)
    if name is not None:
        stages.append((name, "\n".join(body)))
    return stages


class TestDependencyList:
    def test_runtime_requirements_exclude_torch(self):
        names = _requirement_names(BACKEND / "requirements.txt")
        offending = [n for n in names if n in TORCH_FAMILY]
        assert not offending, (
            f"requirements.txt installs {offending}. These must stay out of the "
            "runtime image: with transformers importable, langchain_core drags "
            "torch into the process and Render's 512 MiB free tier OOM-kills "
            "the deploy. Dockerfile.deploy installs them in its `index` stage "
            "instead."
        )

    def test_runtime_requirements_include_the_onnx_encoder(self):
        names = _requirement_names(BACKEND / "requirements.txt")
        assert "onnxruntime" in names, (
            "app/embedder.py encodes queries with ONNX Runtime. Without the "
            "package the backend has no encoder at all."
        )


class TestDeployImage:
    def test_the_image_is_split_so_the_index_build_keeps_torch(self):
        stages = _dockerfile_stages(ROOT / "Dockerfile.deploy")
        assert any(name.startswith("index") for name, _ in stages), (
            "expected an `index` build stage that installs torch and writes "
            "chroma_db/, with the torch-free runtime stage copying from it"
        )
        assert any("--from=index" in body for _, body in stages), (
            "the runtime stage must copy processed/, chroma_db/ and the "
            "generated reference/ JSON out of the index stage"
        )

    def test_torch_is_not_installed_in_the_runtime_stage(self):
        stages = _dockerfile_stages(ROOT / "Dockerfile.deploy")
        assert stages, "could not parse any FROM stage out of Dockerfile.deploy"
        runtime_name, runtime_body = stages[-1]

        installs = [
            line for line in runtime_body.splitlines() if "pip install" in line
        ]
        assert installs, (
            f"stage {runtime_name!r} installs nothing — expected it to install "
            "backend/requirements.txt"
        )
        for pkg in TORCH_FAMILY:
            assert pkg not in "\n".join(installs), (
                f"the runtime stage ({runtime_name}) pip-installs {pkg!r}; it "
                "belongs only in the earlier index-build stage"
            )


class TestServingImportChain:
    def _run(self, code: str) -> str:
        """Run `code` with torch unimportable; return its last stdout line."""
        result = subprocess.run(
            [sys.executable, "-c", BLOCK_TORCH + code],
            cwd=BACKEND,
            capture_output=True,
            text=True,
            timeout=600,
        )
        assert result.returncode == 0, (
            f"failed with torch unavailable:\n{result.stdout}\n{result.stderr}"
        )
        lines = [line for line in result.stdout.strip().splitlines() if line.strip()]
        assert lines, f"code printed nothing:\n{result.stderr}"
        return lines[-1]

    def test_app_imports_with_torch_unavailable(self):
        """The whole serving chain — FastAPI, LangGraph, langchain-groq."""
        routes = json.loads(
            self._run("import json, app.main; print(json.dumps(len(app.main.app.routes)))")
        )
        assert routes > 20, f"only {routes} routes registered; import looks partial"

    def test_retrieval_answers_with_torch_unavailable(self):
        hits = json.loads(
            self._run(
                "import json;"
                "from app.nodes import retriever;"
                "print(json.dumps(retriever.search_verses("
                "'What does Charaka say about shatavari as a rejuvenator?',"
                "limit=3)))"
            )
        )
        assert len(hits) == 3, f"expected 3 verses, got {len(hits)}"
        for hit in hits:
            assert hit["verse_id"] and hit["text"], f"empty hit: {hit}"
            assert 0.0 < hit["score"] <= 1.0, f"implausible score: {hit}"

    def test_the_encoder_is_onnx_when_torch_is_absent(self):
        chosen = self._run(
            "from app import embedder; print(embedder.backend().name)"
        )
        assert "onnx" in chosen, (
            f"expected the ONNX encoder, got {chosen!r} — with torch absent "
            "there is no alternative, so this means the runtime encoder is not "
            "installed"
        )


def test_torch_backend_stays_available_for_the_index_build(monkeypatch):
    """`CHARAKA_EMBEDDER=torch` must keep working where torch IS installed.

    scripts/build_vector_store.py and local index rebuilds rely on the torch
    path being reachable; only the deploy image forbids it.
    """
    monkeypatch.setenv("CHARAKA_EMBEDDER", "torch")
    from app import embedder

    try:
        chosen = embedder._pick_backend()
    except ImportError as exc:
        import pytest

        pytest.skip(f"torch is not installed here: {exc}")
    assert chosen.name.startswith("torch:")


def test_missing_encoder_reports_both_causes(monkeypatch):
    """With neither encoder installed the error must name both, not say "torch"."""
    monkeypatch.setenv("CHARAKA_EMBEDDER", "onnx")
    monkeypatch.setattr(
        "app.embedder._onnx_backend",
        lambda: (_ for _ in ()).throw(ImportError("no onnxruntime")),
    )
    monkeypatch.setattr(
        "app.embedder._torch_backend",
        lambda: (_ for _ in ()).throw(ImportError("no sentence_transformers")),
    )
    from app import embedder

    try:
        embedder._pick_backend()
    except RuntimeError as exc:
        message = str(exc)
        assert "no onnxruntime" in message
        assert "no sentence_transformers" in message
        assert "requirements.txt" in message
    else:
        raise AssertionError("expected a RuntimeError naming both failures")