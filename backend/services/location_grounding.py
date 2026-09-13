"""Ground spatial writes in the latest assertion, not inferred geography."""
import hashlib
import re

_RESIDENCE = re.compile(r"\b(?:tinggal(?:\s*nya)?|menetap|berdomisili|domisili(?:\s*nya)?|(?:lives?|living|resides?|residing)(?=\s+(?:in|at)\b))\b", re.I)
_NEGATIVE = re.compile(r"\b(?:tidak|tak|gak|ga|nggak|enggak|ngga|bukan|not|never|no longer|doesn't|don't|isn't)\b", re.I)
_NON_ASSERTION = re.compile(r"\b(?:kalau|jika|seandainya|andaikan|misalnya|mungkin|katanya|konon|bilang|berkata|ingin|pengin|pengen|mau|akan|berencana|harus|dulu|pernah|said|says|if|suppose|might|maybe|would|will|wants?|plan|used to|need to|have to)\b", re.I)
_FRIEND = re.compile(r"\b(?:teman|temen)(?:ku|\s+aku|\s+saya)\s+(?:namanya|bernama)\s+([\w'-]+(?:\s+[\w'-]+){0,2}?)(?=\s+(?:dia|itu|kuliah|tinggal)|[,.;]|$)", re.I)


def _name(value):
    return " ".join(str(value or "").casefold().split())


def _node(nodes, label, name, identity_context=""):
    matching = [node for node in nodes if _name(node.get("label")) == label.casefold()
                and _name(node.get("name")) == _name(name)]
    if len(matching) == 1:
        return matching[0]
    if matching:
        return None
    digest = hashlib.sha256(f"{label}|{name}|{identity_context}".encode()).hexdigest()[:16]
    node = {"id": "sp_" + digest, "label": label, "name": _name(name),
            "identity_context": identity_context, "confidence": 1.0}
    nodes.append(node)
    return node


def _prepare_people(nodes, message, history, knowledge):
    if re.search(r"\b(?:aku|saya|gw|gue|nafiz|I)\b", message, re.I):
        _node(nodes, "Person", "nafiz")
    history = [item for item in (history or []) if isinstance(item, dict)]
    passive = [*[item for item in history if item.get("role") == "summary"][-1:],
               *[item for item in history if item.get("role") in {"user", "assistant"}][-12:]]
    discourse = [message, *[str(item.get("content") or "")[:1500] for item in passive
                           if item.get("role") in {"user", "summary"}]]
    contexts = {}
    for text in discourse:
        for match in _FRIEND.finditer(text):
            contexts.setdefault(_name(match.group(1)), set()).add("teman nafiz")
    for fact in knowledge or []:
        for match in re.finditer(r"\(Person '([^']+)'; identity: ([^)]+)\)", str(fact)):
            contexts.setdefault(_name(match.group(1)), set()).add(match.group(2).strip())
    for name, identities in contexts.items():
        if len(identities) == 1 and re.search(rf"(?<!\w){re.escape(name)}(?!\w)", message, re.I):
            _node(nodes, "Person", name, next(iter(identities)))


def _historical_subject(people, history):
    named = [person for person in people if _name(person.get("name")) not in {"nafiz", "claire"}]
    for item in reversed(list(history or [])[-12:]):
        if not isinstance(item, dict) or item.get("role") not in {"user", "summary"}:
            continue
        text = str(item.get("content") or "")
        names = {_name(match.group(1)) for match in _FRIEND.finditer(text)}
        names.update(_name(person["name"]) for person in named if re.search(
            rf"(?<!\w){re.escape(_name(person['name']))}(?!\w)", text, re.I))
        if names:
            for name in names:
                if re.search(rf"(?<!\w){re.escape(name)}\s+(?:dan|atau|and|or)\s+[\w'-]+|[\w'-]+\s+(?:dan|atau|and|or)\s+{re.escape(name)}(?!\w)", text, re.I):
                    return None
            matching = [person for person in named if _name(person["name"]) in names]
            return matching[0] if len(names) == 1 and len(matching) == 1 else None
    return None


def _subject(prefix, people, history=None):
    mentions = []
    for person in people:
        name = _name(person.get("name"))
        pattern = rf"(?<!\w){re.escape(name)}(?!\w)"
        if name == "nafiz":
            pattern = r"\b(?:nafiz|aku|saya|gw|gue|I)\b"
        for match in re.finditer(pattern, prefix, re.I):
            mentions.append((match.start(), person))
    pronouns = list(re.finditer(r"\b(?:dia|ia|beliau|he|she)\b", prefix, re.I))
    if not mentions:
        return _historical_subject(people, history) if pronouns else None
    latest = max(position for position, _ in mentions)
    candidates = [person for position, person in mentions if position == latest]
    if len(candidates) != 1 or re.search(r"\b(?:dan|atau|and|or)\s*$", prefix[:latest], re.I):
        return None
    if pronouns and pronouns[-1].start() > latest and _name(candidates[0]["name"]) in {"nafiz", "claire"}:
        return _historical_subject(people, history)
    return candidates[0]


def _clauses(message):
    text = re.sub(r"```[\s\S]*?```|\"[^\"]*\"|(?<!\w)'[^']*'", " ", message)
    for match in re.finditer(r"([^\n.;,!?]+)([\n.;,!?]|$)", text):
        clause = match.group(1).strip()
        if not clause or match.group(2) == "?" or _NON_ASSERTION.search(clause):
            continue
        if re.search(r"\b(?:siapa|apakah|dimana|di mana|who|whether|where)\b", clause, re.I):
            continue
        yield clause


def _place_names(clause):
    prepositions = list(re.finditer(r"\b(?:di|in|at)\s+", clause, re.I))
    for index, match in enumerate(prepositions):
        end = prepositions[index + 1].start() if index + 1 < len(prepositions) else len(clause)
        name = re.split(r"\b(?:sih|loh|lho|kok|kan|ya|juga|sekarang|saat|tapi|tetapi|dan|gak|ga|nggak|enggak|tidak|bukan|not|but|and)\b", clause[match.end():end], maxsplit=1, flags=re.I)[0].strip()
        if name and len(name.split()) <= 5 and not re.search(r"\b(?:mana|sana|situ|sini|rumahnya|kantornya|kampusnya|which|where|there|here)\b", name, re.I):
            yield match.start(), match.end(), name


def residence_claims(message, nodes, history=None, knowledge=None):
    """Return (source node, location node, negative) for explicit clauses."""
    _prepare_people(nodes, message, history, knowledge)
    people = [node for node in nodes if _name(node.get("label")) == "person"]
    claims = []
    for clause in _clauses(message):
        verbs = list(_RESIDENCE.finditer(clause))
        for index, verb in enumerate(verbs):
            source = _subject(clause[:verb.start()], people, history)
            if source is None:
                continue
            end = verbs[index + 1].start() if index + 1 < len(verbs) else len(clause)
            prefix = clause[:verb.start()]
            subject_tokens = list(re.finditer(r"\b(?:aku|saya|gw|gue|dia|ia|beliau)\b|(?<!\w)" + re.escape(_name(source["name"])) + r"(?!\w)", prefix, re.I))
            prefix = prefix[subject_tokens[-1].end():] if subject_tokens else prefix
            prefix = re.sub(r"\b(?:(?:tidak|gak|nggak|bukan)\s+(?:hanya|cuma|sekadar)|not only)\b", "", prefix, flags=re.I)
            negative_verb = bool(_NEGATIVE.search(prefix))
            last_end = verb.end()
            for preposition, start, place in _place_names(clause[verb.end():end]):
                preposition += verb.end()
                start += verb.end()
                between = clause[last_end:preposition]
                contrast = bool(re.search(r"\b(?:tapi|tetapi|but)\b", between, re.I))
                negative = bool(_NEGATIVE.search(between)) or (negative_verb and not contrast)
                target = _node(nodes, "Location", place)
                if target:
                    claims.append((source, target, negative))
                last_end = start + len(place)
    return claims


def _aliases(node, message):
    name = _name(node.get("name"))
    aliases = [name]
    for match in re.finditer(r"\b([\w'-]+)\s*\(([^)]+)\)", message):
        if _name(match.group(2)) == name:
            aliases.append(_name(match.group(1)))
    return aliases


def ground_locations(data, message, history=None, knowledge=None):
    """Filter unsupported residence and enforce targeted explicit negation."""
    nodes = [dict(node) for node in data.get("nodes", [])]
    claims = residence_claims(message, nodes, history, knowledge)
    positive = {(source["id"], target["id"]) for source, target, negative in claims if not negative}
    negative = {(source["id"], target["id"]) for source, target, denied in claims if denied}
    edges = [dict(edge) for edge in data.get("edges", []) if
             _name(edge.get("relation")) != "lives_in" or
             ((edge.get("source"), edge.get("target")) in positive and
              (edge.get("source"), edge.get("target")) not in negative)]
    for source, target in sorted(positive - negative):
        if not any(edge.get("source") == source and edge.get("target") == target
                   and _name(edge.get("relation")) == "lives_in" for edge in edges):
            edges.append({"source": source, "target": target, "relation": "LIVES_IN", "confidence": 1.0,
                          "supersedes": [], "replaces_current_relation": False})
    # Denials authorize only the mentioned target, never all residences.
    retractions = [dict(item) for item in data.get("retractions", []) if _name(item.get("relation")) != "lives_in"]
    for source, target in sorted(negative):
        retractions.append({"source": source, "target": target, "relation": "LIVES_IN", "confidence": 1.0})
    organizations = [node for node in nodes if _name(node.get("label")) in {"organization", "university", "school", "company", "office", "institution", "campus"}]
    locations = [node for node in nodes if _name(node.get("label")) == "location"]
    for clause in _clauses(message):
        for organization in organizations:
            for alias in _aliases(organization, message):
                internship = re.search(rf"\bmagang\s+di\s+{re.escape(alias)}(?!\w)", clause, re.I)
                if internship:
                    person = _subject(clause[:internship.start()], [node for node in nodes if _name(node.get("label")) == "person"], history)
                    if person:
                        edges = [item for item in edges if not (item.get("source") == person["id"]
                                 and item.get("target") == organization["id"] and _name(item.get("relation")) == "works_as")]
                        if not any(item.get("source") == person["id"] and item.get("target") == organization["id"]
                                   and _name(item.get("relation")) == "interns_at" for item in edges):
                            edges.append({"source": person["id"], "target": organization["id"], "relation": "INTERNS_AT",
                                          "confidence": 1.0, "supersedes": [], "replaces_current_relation": False})
                for location in locations:
                    attachment = rf"(?<!\w){re.escape(alias)}(?:\s*\([^)]+\)\s+(?:di\s+)?|\s+(?:yang\s+)?(?:berlokasi\s+|berada\s+)?di\s+){re.escape(_name(location['name']))}(?!\w)"
                    if re.search(attachment, clause, re.I) and not _NEGATIVE.search(clause):
                        if not any(edge.get("source") == organization["id"] and edge.get("target") == location["id"]
                                   and _name(edge.get("relation")) == "located_in" for edge in edges):
                            edges.append({"source": organization["id"], "target": location["id"], "relation": "LOCATED_IN",
                                          "confidence": 1.0, "supersedes": [], "replaces_current_relation": False})
    used = {edge[field] for edge in edges for field in ("source", "target")}
    used.update(item[field] for item in retractions for field in ("source", "target") if item.get(field))
    return {"nodes": [node for node in nodes if node.get("id") in used], "edges": edges, "retractions": retractions}
