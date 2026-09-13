import hashlib
import re

class EntityIdentityPolicy:
    @staticmethod
    def _clean_label(label: str) -> str:
        clean_label = re.sub(r'[^a-zA-Z0-9_]', '', str(label or "Entity"))
        # Preserve PascalCase/acronyms exactly as supplied by the extractor.
        # Cypher labels must start with a letter when interpolated unquoted.
        if not clean_label or not clean_label[0].isalpha():
            return "Entity"
        return clean_label

    @staticmethod
    def _clean_name(name: str) -> str:
        return " ".join(str(name or "").strip().lower().split())

    @classmethod
    def _canonical_identity_context(cls, identity_context: str) -> str:
        """Normalize common relational paraphrases without erasing distinctions."""
        text = cls._clean_name(identity_context)
        text = re.sub(r"\b(?:temanku|temenku|my friend)\b", "teman nafiz", text)
        text = re.sub(r"\btemen\b", "teman", text)
        # Joined Indonesian possessives are descriptive evidence, not a stable
        # difference in identity ("ibunya nafiz" and "ibu dari nafiz").
        text = re.sub(r"\b(ibu|ayah|istri|suami|teman|kakak|adik)nya\b", r"\1", text)
        aliases = {
            "mother": "ibu", "mom": "ibu", "mama": "ibu", "mommy": "ibu",
            "father": "ayah", "dad": "ayah", "papa": "ayah",
            "wife": "istri", "spouse": "pasangan", "husband": "suami",
            "friend": "teman", "colleague": "rekan", "coworker": "rekan",
            "sister": "saudara perempuan", "brother": "saudara laki laki",
        }
        ignored = {"dari", "of", "the", "seorang", "a", "an", "milik", "punya"}
        tokens = re.findall(r"[^\W_]+", text, flags=re.UNICODE)
        canonical = [aliases.get(token, token) for token in tokens if token not in ignored]
        return " ".join(canonical)

    @staticmethod
    def _prepare_search_keyword(keyword: str) -> tuple[str, str] | None:
        """Build a Unicode word-boundary regex for one meaningful keyword."""
        tokens = re.findall(r"[^\W_]+", str(keyword or "").lower(), flags=re.UNICODE)
        normalized = " ".join(tokens)
        # Prevent noisy one/two-character router output ("a", "di", "an")
        # from fanning out across the graph. Meaningful abbreviations should be
        # emitted with context by the router (for example "ai engineer").
        if sum(len(token) for token in tokens) < 3:
            return None
        term_pattern = r"\s+".join(re.escape(token) for token in tokens)
        boundary_pattern = (
            rf"(?i).*(?<![\p{{L}}\p{{N}}]){term_pattern}"
            rf"(?![\p{{L}}\p{{N}}]).*"
        )
        return normalized, boundary_pattern

    @classmethod
    def _entity_key(cls, label: str, name: str, identity_context: str = "") -> str:
        """Return a safe graph identity key without treating a display name as ID.

        A named Person is only stable when the extractor supplies an explicit
        differentiator (for example, ``mother of nafiz``). Unqualified people
        are rejected instead of being permanently fragmented by random keys.
        """
        label = cls._clean_label(label).lower()
        name = cls._clean_name(name)
        context = cls._canonical_identity_context(identity_context)

        if label == "person" and name in {"nafiz", "claire"}:
            return f"person:{name}"
        if label == "person" and not context:
            raise ValueError("Non-canonical Person requires identity_context")

        canonical = f"{label}|{name}|{context}" if label == "person" else f"{label}|{name}"
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return f"{label}:{digest}"

    @staticmethod
    def _residence_marker_key(source, scope, target=None):
        return hashlib.sha256(
            repr((str(source), str(scope), str(target) if target is not None else None)).encode("utf-8")
        ).hexdigest()
