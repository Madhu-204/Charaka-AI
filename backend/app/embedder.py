"""Runtime query embedder that does not import torch.

The corpus vectors in ``chroma_db/`` were produced at image-build time by
``scripts/build_vector_store.py``, which runs all-MiniLM-L6-v2 through
sentence-transformers (torch). At runtime this process never embeds the corpus
again -- it only encodes short queries and uploaded-document chunks -- yet
importing torch and loading the model resident cost roughly 400 MB, which
overran Render's 512 MB free tier and killed the container ~20 s after startup
("Out of memory (used over 512Mi)").

So the runtime embedder runs the *same* weights through ONNX Runtime, which
chromadb already depends on. Verified numerically equivalent to the torch path
across query-, verse- and oversize-length inputs:

    cosine(onnx, torch) = 1.0   (every row)   max |onnx - torch| = 1.75e-07
    relative ordering of candidates: identical

Same weights, same mean pooling, same L2 normalisation (torch's epsilon), so
cosine scores, the confidence bands and the fused ranking are unchanged.

This module is only half of that fix, and the smaller half. Even with nothing
in the app importing sentence-transformers, ``langchain_core`` performs an
unconditional ``try: from transformers import GPT2TokenizerFast`` at import
time, so a runtime image that merely *has* transformers installed drags all of
torch into the process. The deploy image therefore omits torch,
transformers and sentence-transformers from the serving stage entirely
(``Dockerfile.deploy``) and keeps them in the ``index`` stage that builds
chroma_db/. ``build_vector_store.py`` keeps using torch there, where memory is
not capped and the index must keep coming from the exact path the audit scripts
validate.
"""

import os
from pathlib import Path

from app.chunking import EMBEDDING_MODEL

MODEL_NAME = EMBEDDING_MODEL
"""Sourced from ``app.chunking`` for the same reason ``herb_key`` lives there:
the index builder and the runtime encoder must never disagree about which
encoder produced the vectors. Hardcoding the name here would let the two drift,
and every vector in the store would silently become wrong."""

_backend = None

DEFAULT_CACHE = Path.home() / ".cache" / "chroma" / "onnx_models" / MODEL_NAME
"""chromadb's own cache location for these weights, kept as the default so a
cache warmed by any earlier chromadb call is found with no configuration."""


def cache_dir() -> Path:
    """Directory the ONNX weights are read from.

    ``CHARAKA_ONNX_CACHE`` overrides it, and the deploy image sets it so the
    directory warmed during the build is the one read at runtime. The default is
    ``$HOME``-relative, and $HOME is a poor thing to depend on across a build
    stage and a running container that need to agree: if they ever disagree the
    service silently downloads ~80 MB on the first user question instead of
    reading weights it already has. That download is a plain request to Chroma's
    S3 bucket, so ``HF_HUB_OFFLINE=1`` does *not* stop it.
    """
    return Path(os.getenv("CHARAKA_ONNX_CACHE") or DEFAULT_CACHE)


def _torch_backend():
    """Original sentence-transformers path, for local dev and the build."""
    from sentence_transformers import SentenceTransformer

    class _Torch:
        name = f"torch:{MODEL_NAME}"

        def __init__(self):
            # Loaded once and held. Constructing a SentenceTransformer per
            # encode() call re-read the weights from disk every query and leaked
            # a whole extra copy of the model each time -- the fallback had to
            # be one instance, same as the ONNX path.
            self._model = SentenceTransformer(MODEL_NAME)

        def encode(self, texts):
            return self._model.encode(texts, normalize_embeddings=True).tolist()

    return _Torch()


def _onnx_backend():
    from chromadb.utils import embedding_functions as ef

    class _Onnx:
        name = f"onnx:{MODEL_NAME}"

        def __init__(self):
            # DOWNLOAD_PATH is a class attribute that chromadb resolves at model
            # and tokenizer load time, so it has to be set before the first
            # encode(). Pointing it at cache_dir() makes the lookup explicit
            # rather than $HOME-relative.
            ef.ONNXMiniLM_L6_V2.DOWNLOAD_PATH = cache_dir()
            self._fn = ef.ONNXMiniLM_L6_V2(
                preferred_providers=["CPUExecutionProvider"]
            )
            # chromadb downloads the weights inside __call__, not __init__, so a
            # cold cache would otherwise only surface as a long stall on the
            # first user question. Say so at startup instead.
            if not (cache_dir() / "onnx" / "model.onnx").is_file():
                print(
                    f"[embedder] ONNX weights not in {cache_dir()} — the first "
                    "query will download them (~80 MB) instead of reading them "
                    "from the image"
                )

        def encode(self, texts):
            return [list(map(float, v)) for v in self._fn(list(texts))]

    return _Onnx()


def _pick_backend():
    """ONNX by default; ``CHARAKA_EMBEDDER=torch`` forces the original path."""
    want = os.getenv("CHARAKA_EMBEDDER", "onnx").lower()
    if want == "torch":
        return _torch_backend()

    try:
        return _onnx_backend()
    except Exception as exc:  # noqa: BLE001 - report the real cause, never die silently
        print(f"[embedder] ONNX backend unavailable ({exc}) -> trying torch")
        try:
            return _torch_backend()
        except Exception as torch_exc:  # noqa: BLE001
            raise RuntimeError(
                "no query encoder is available: ONNX Runtime failed and "
                "sentence-transformers is not installed. The deploy image "
                "installs onnxruntime and omits torch on purpose — see "
                "backend/requirements.txt. For local work, either "
                "`pip install onnxruntime` or set CHARAKA_EMBEDDER=torch in an "
                f"environment that has torch. (onnx: {exc}; torch: {torch_exc})"
            ) from torch_exc


def backend():
    global _backend
    if _backend is None:
        _backend = _pick_backend()
        print(f"[embedder] runtime backend: {_backend.name}")
    return _backend


def encode(texts):
    """Embed one or more strings, L2-normalised, as plain float lists."""
    if isinstance(texts, str):
        texts = [texts]
    if not texts:
        return []
    return backend().encode(texts)


def encode_query(text: str) -> list:
    """Embed a single query string -- the hot path."""
    return encode([text])[0]