"""Regression cases reported by the user: campus, office, Adel, and negation."""
import json
from types import SimpleNamespace as NS
from unittest import TestCase
from unittest.mock import patch

from schemas.chat_sch import ProjectScopeContext
from services import llm_service, memory_service
from services.location_grounding import ground_locations
from services.memory_policy import validate_extracted_knowledge
from services.neo4j_service import Neo4jService


def node(id, label, name, identity=""):
    return {"id": id, "label": label, "name": name, "identity_context": identity, "confidence": 1.0}


def edge(source, target, relation):
    return {"source": source, "target": target, "relation": relation,
            "confidence": 1.0, "supersedes": [], "replaces_current_relation": False}


def completion(payload):
    return NS(choices=[NS(message=NS(content=json.dumps(payload)))])


class LocationGroundingTests(TestCase):
    def extract(self, message, payload, history=None, knowledge=None):
        with patch.object(llm_service, "_memory_completion", return_value=completion(payload)):
            return llm_service.extract_knowledge(message, session_history=history,
                neo4j_context=knowledge, raise_on_error=True)

    def test_university_location_does_not_become_user_residence(self):
        payload = {"nodes": [node("p", "Person", "nafiz"), node("u", "Organization", "its"), node("l", "Location", "surabaya")],
                   "edges": [edge("p", "u", "STUDIED_AT"), edge("p", "l", "LIVES_IN")]}
        result = self.extract("saat ini aku kuliah di ITS (Institut Teknologi Sepuluh Nopember) di Surabaya", payload)
        self.assertEqual({("p", "u", "STUDIED_AT"), ("u", "l", "LOCATED_IN")},
                         {(item["source"], item["target"], item["relation"]) for item in result["edges"]})

    def test_internship_location_belongs_to_organization(self):
        payload = {"nodes": [node("p", "Person", "nafiz"), node("o", "Organization", "agung sedayu group"), node("l", "Location", "pik")],
                   "edges": [edge("p", "o", "INTERNS_AT"), edge("p", "l", "LIVES_IN")]}
        result = self.extract("Aku saat ini magang di Agung Sedayu Group di PIK", payload)
        self.assertEqual({("p", "o", "INTERNS_AT"), ("o", "l", "LOCATED_IN")},
                         {(item["source"], item["target"], item["relation"]) for item in result["edges"]})

    def test_adel_studies_in_malang_without_residence_inference(self):
        payload = {"nodes": [node("a", "Person", "adel", "teman nafiz"), node("p", "Person", "nafiz"),
                             node("u", "Organization", "universitas brawijaya"), node("l", "Location", "malang"),
                             node("s", "Concept", "semester 7")],
                   "edges": [edge("a", "p", "IS_FRIEND_WITH"), edge("a", "u", "STUDIED_AT"),
                             edge("a", "l", "LIVES_IN"), edge("a", "s", "HAS_ATTRIBUTE"), edge("p", "s", "HAS_ATTRIBUTE")]}
        result = self.extract("temenku namanya adel dia kuliah di UB (Universitas Brawijaya) di Malang, dia sekarang semester 7 juga sama kayak aku", payload)
        self.assertNotIn("LIVES_IN", [item["relation"] for item in result["edges"]])
        self.assertIn(edge("u", "l", "LOCATED_IN"), result["edges"])
        self.assertEqual(2, sum(item["relation"] == "HAS_ATTRIBUTE" for item in result["edges"]))

    def test_campus_and_explicit_residence_are_distinct(self):
        payload = {"nodes": [node("p", "Person", "nafiz"), node("u", "Organization", "its"),
                             node("s", "Location", "surabaya"), node("j", "Location", "jakarta")],
                   "edges": [edge("p", "u", "STUDIED_AT"), edge("p", "s", "LIVES_IN"), edge("p", "j", "LIVES_IN")]}
        result = self.extract("Aku kuliah di ITS di Surabaya, tapi aku tinggal di Jakarta", payload)
        self.assertIn(edge("p", "j", "LIVES_IN"), result["edges"])
        self.assertNotIn(edge("p", "s", "LIVES_IN"), result["edges"])

    def test_adel_correction_restores_surabaya_and_retracts_only_malang(self):
        payload = {"nodes": [node("a", "Person", "adel", "teman nafiz"), node("m", "Location", "malang")],
                   "edges": [edge("a", "m", "LIVES_IN")],
                   "retractions": [{"source": "a", "relation": "LIVES_IN"}]}
        result = self.extract("tapi si adel itu dia tinggal nya di surabaya sih gak di malang", payload)
        names = {item["id"]: item["name"] for item in result["nodes"]}
        self.assertEqual([("adel", "surabaya")], [(names[item["source"]], names[item["target"]])
            for item in result["edges"] if item["relation"] == "LIVES_IN"])
        self.assertEqual([("adel", "malang")], [(names[item["source"]], names[item["target"]]) for item in result["retractions"]])

    def test_negative_reminder_is_not_skipped_or_lost_with_empty_model_output(self):
        history = [{"role": "user", "content": "temenku namanya adel dia kuliah di UB di Malang"}]
        for message in ("inget loh ya si adel itu gak tinggal di malang", "kamu inget kan si adel itu gak tinggal di malang"):
            with self.subTest(message=message):
                result = self.extract(message, {"nodes": [], "edges": []}, history)
                names = {item["id"]: item["name"] for item in result["nodes"]}
                self.assertEqual([("adel", "malang")], [(names[item["source"]], names[item["target"]]) for item in result["retractions"]])
                self.assertEqual([], result["edges"])

    def test_negative_only_can_link_existing_identity_without_dialogue(self):
        knowledge = ["[fact_id: f; current: true] (Person 'adel'; identity: teman nafiz) --[LIVES_IN]--> (Location 'malang')"]
        result = self.extract("si Adel gak tinggal di Malang", {"nodes": [], "edges": []}, knowledge=knowledge)
        self.assertEqual("teman nafiz", next(item["identity_context"] for item in result["nodes"] if item["label"] == "Person"))
        self.assertEqual(1, len(result["retractions"]))

    def test_office_correction_does_not_reassert_pik_residence(self):
        result = self.extract("yang di pik itu kantor ku, aku gak tinggal di pik",
            {"nodes": [node("p", "Person", "nafiz"), node("l", "Location", "pik")], "edges": [edge("p", "l", "LIVES_IN")]})
        self.assertEqual([], result["edges"])
        self.assertEqual("l", result["retractions"][0]["target"])

    def test_spatial_assertions_do_not_come_from_questions_quotes_or_hypotheses(self):
        payload = {"nodes": [node("p", "Person", "nafiz"), node("l", "Location", "malang")], "edges": [edge("p", "l", "LIVES_IN")]}
        for message in ("Aku tinggal di Malang?", 'Dia berkata "aku tinggal di Malang"',
                        "Kalau aku tinggal di Malang nanti", "Mungkin aku tinggal di Malang"):
            result = ground_locations(payload, message)
            self.assertEqual([], result["edges"], message)
            self.assertEqual([], result["retractions"], message)

    def test_multi_subjects_do_not_attach_other_persons_residence(self):
        payload = {"nodes": [node("a", "Person", "adel", "teman nafiz"), node("p", "Person", "nafiz"),
                             node("s", "Location", "surabaya"), node("m", "Location", "malang")],
                   "edges": [edge("a", "s", "LIVES_IN"), edge("p", "m", "LIVES_IN")]}
        result = self.extract("Aku tinggal di Surabaya, si Adel gak tinggal di Malang", payload)
        self.assertEqual([edge("p", "s", "LIVES_IN")], result["edges"])
        self.assertEqual("a", result["retractions"][0]["source"])

    def test_type_contracts_and_friend_identity_paraphrases(self):
        with self.assertRaises(ValueError):
            validate_extracted_knowledge({"nodes": [node("p", "Person", "nafiz"), node("l", "Location", "pik")],
                                         "edges": [edge("p", "l", "LOCATED_IN")]})
        expected = Neo4jService._entity_key("Person", "adel", "teman nafiz")
        for identity in ("temen nafiz", "temenku", "temanku", "my friend"):
            self.assertEqual(expected, Neo4jService._entity_key("Person", "adel", identity))

    def test_residence_pronoun_uses_a_clear_dialogue_identity(self):
        payload = {"nodes": [node("a", "Person", "adel", "teman nafiz"), node("s", "Location", "surabaya")],
                   "edges": [edge("a", "s", "LIVES_IN")]}
        history = [{"role": "user", "content": "ya adel temenku"}]
        for message in ("dia tinggal di Surabaya", "Aku tahu dia tinggal di Surabaya"):
            result = self.extract(message, payload, history)
            self.assertEqual([edge("a", "s", "LIVES_IN")], result["edges"])
        result = self.extract("dia tinggal di Surabaya", payload, [{"role": "user", "content": "Adel dan Budi datang bersama"}])
        self.assertEqual([], result["edges"])
        ambiguous = {**payload, "nodes": [*payload["nodes"], node("b", "Person", "budi", "teman nafiz")]}
        result = self.extract("dia tinggal di Surabaya", ambiguous, [{"role": "user", "content": "Adel dan Budi datang bersama"}])
        self.assertEqual([], result["edges"])

    def test_future_and_past_residence_do_not_become_current_assertions(self):
        payload = {"nodes": [node("p", "Person", "nafiz"), node("l", "Location", "malang")], "edges": [edge("p", "l", "LIVES_IN")]}
        for message in ("Aku mau tinggal di Malang", "Aku akan tinggal di Malang", "Aku dulu tinggal di Malang", "Aku live di Malang"):
            self.assertEqual([], ground_locations(payload, message)["edges"], message)
        self.assertEqual([edge("p", "l", "LIVES_IN")], ground_locations(payload, "Aku gak cuma tinggal di Malang")["edges"])

    def test_internship_type_drift_and_parenthetical_campus_qualifier(self):
        payload = {"nodes": [node("p", "Person", "nafiz"), node("o", "Organization", "agung sedayu group")],
                   "edges": [edge("p", "o", "WORKS_AS")]}
        self.assertEqual([edge("p", "o", "INTERNS_AT")], self.extract("Aku lagi magang di Agung Sedayu Group di PIK", payload)["edges"])
        campus = {"nodes": [node("p", "Person", "nafiz"), node("o", "Organization", "institut teknologi sepuluh nopember"),
                            node("s", "Location", "surabaya")], "edges": [edge("p", "o", "STUDIED_AT"), edge("p", "s", "LIVES_IN")]}
        result = self.extract("Aku kuliah di ITS (Institut Teknologi Sepuluh Nopember) Surabaya jurusan Informatika", campus)
        self.assertIn(edge("o", "s", "LOCATED_IN"), result["edges"])
        self.assertNotIn(edge("p", "s", "LIVES_IN"), result["edges"])


class InlineReferenceTests(TestCase):
    def test_introduced_adel_resolves_despite_router_ambiguity_and_empty_history(self):
        message = "temenku namanya adel dia kuliah di UB (Universitas Brawijaya) di Malang, dia sekarang semester 7 juga sama kayak aku"
        payload = {"needs_memory": True, "keywords": [], "reference_status": "ambiguous", "confidence": 0.2}
        with patch.object(llm_service, "_memory_completion", return_value=completion(payload)), patch.object(
            memory_service, "_resolve_project_scope", return_value=ProjectScopeContext()
        ), patch.object(memory_service, "search_memory", return_value=[]) as vector, patch.object(
            memory_service.neo4j_client, "search_knowledge", return_value=[]
        ) as graph:
            result = memory_service.retrieve_context(message, session_history=[])
        self.assertEqual("resolved", result.query_resolution.status)
        self.assertIn("namanya adel adel kuliah", vector.call_args.args[0])
        self.assertIn("adel", graph.call_args.args[0])
        self.assertIsNone(llm_service._reference_clarification(result))

    def test_explicit_correction_subject_and_predicate_suffix_are_not_ambiguous(self):
        with patch.object(llm_service, "_memory_completion", return_value=completion(
            {"needs_memory": True, "keywords": [], "reference_status": "ambiguous"})):
            result = llm_service.route_memory_query("tapi si adel itu dia tinggal nya di surabaya sih gak di malang")
        self.assertEqual("resolved", result.reference_status)
        self.assertIn("si adel itu adel tinggal nya", result.query)

    def test_model_can_anchor_a_name_from_latest_turn(self):
        payload = {"needs_memory": True, "keywords": ["adel"], "reference_status": "resolved", "confidence": 0.95,
                   "references": [{"mention": "dia", "entity": "Adel"}]}
        with patch.object(llm_service, "_memory_completion", return_value=completion(payload)):
            result = llm_service.route_memory_query("Aku membahas Adel. Di mana dia kerja?")
        self.assertEqual("resolved", result.reference_status)
        self.assertIn("Adel kerja", result.query)

    def test_different_explicit_subjects_do_not_use_global_pronoun_override(self):
        self.assertIsNone(llm_service._inline_person_reference("temenku namanya Adel dia kuliah, dan si Budi dia bekerja"))
        self.assertEqual([], llm_service._reference_matches("temenku namanya Adel"))
