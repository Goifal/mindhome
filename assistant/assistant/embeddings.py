"""
Zentrales Embedding-Modul fuer den MindHome Assistant.

Stellt eine multilingual-optimierte Embedding-Function bereit,
die von allen ChromaDB-Collections gemeinsam genutzt wird.

Modell: paraphrase-multilingual-MiniLM-L12-v2
- 118M Parameter, 384 Dimensionen
- Optimiert fuer 50+ Sprachen inkl. Deutsch
- Deutlich besser fuer deutsche Texte als der ChromaDB-Default
  (all-MiniLM-L6-v2, nur Englisch trainiert)
"""

import logging
from typing import Optional

from .config import yaml_config

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"

_embedding_fn: Optional[object] = None


def get_embedding_function():
    """Gibt die konfigurierte Embedding-Function zurueck (Singleton).

    Wird beim ersten Aufruf initialisiert und dann gecacht.
    Falls sentence-transformers nicht installiert ist, wird None
    zurueckgegeben und ChromaDB nutzt seinen Server-Default.
    """
    global _embedding_fn

    if _embedding_fn is not None:
        return _embedding_fn

    kb_config = yaml_config.get("knowledge_base", {})
    model_name = kb_config.get("embedding_model", DEFAULT_MODEL)

    try:
        from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
        _embedding_fn = SentenceTransformerEmbeddingFunction(
            model_name=model_name,
        )
        logger.info("Embedding-Modell geladen: %s", model_name)
        return _embedding_fn
    except ImportError:
        logger.warning(
            "sentence-transformers nicht installiert — ChromaDB nutzt Server-Default. "
            "Fuer bessere deutsche Suche: pip install sentence-transformers"
        )
        return None
    except Exception as e:
        logger.warning("Embedding-Modell '%s' konnte nicht geladen werden: %s", model_name, e)
        return None
