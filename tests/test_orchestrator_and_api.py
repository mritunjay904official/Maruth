import json
import unittest
from unittest.mock import patch

from tornado.testing import AsyncHTTPTestCase

from app import make_app
from maruth.air_quality import get_city_air_quality
from maruth.bio_sensor import evaluate_drosophila_sensor
from maruth.genai_orchestrator import generate_action_plan
from maruth.prompts import compress_context
from maruth.schemas import HouseholdProfile
from maruth.impact_engine import calculate_impact_delta, get_default_interventions


class TestOrchestratorAndAPI(AsyncHTTPTestCase):
    def get_app(self):
        return make_app()

    @patch("maruth.air_quality._fetch_hourly_context", return_value=(6.5, 18.0, []))
    @patch("maruth.air_quality.get_live_air_quality", return_value={"pm2_5": 165.0, "pm10": 240.0, "co": 1150.0, "no2": 58.0})
    def test_prompt_compression_and_plan_cache(self, _mock_live, _mock_hourly):
        air = get_city_air_quality("kolkata", force_refresh=True)
        bio = evaluate_drosophila_sensor(air, force_rerun=True)
        profile = HouseholdProfile(city_id="kolkata", vulnerable_groups=["elderly"])
        chosen = get_default_interventions(profile)
        impact = calculate_impact_delta(air, profile, chosen)

        compact, raw_tok, comp_tok, ratio = compress_context(air, bio, profile, impact, ["Snippet 1", "Snippet 2"])
        self.assertLess(comp_tok, raw_tok)
        self.assertGreater(ratio, 20.0)
        self.assertIn("Kolkata", compact)

        import asyncio

        plan1 = asyncio.run(generate_action_plan(air, bio, profile, chosen, api_provider="local"))
        self.assertFalse(plan1.telemetry.cache_hit)
        self.assertEqual(len(plan1.routine_schedule), 4)

        plan2 = asyncio.run(generate_action_plan(air, bio, profile, chosen, api_provider="local"))
        self.assertTrue(plan2.telemetry.cache_hit)

    def test_presets_and_index_routes(self):
        res_index = self.fetch("/")
        self.assertEqual(res_index.code, 200)
        self.assertIn(b"Maruth", res_index.body)

        res_presets = self.fetch("/api/presets")
        self.assertEqual(res_presets.code, 200)
        data = json.loads(res_presets.body)
        ids = {p["id"] for p in data["presets"]}
        self.assertTrue({"bolpur", "kolkata", "delhi_ncr"}.issubset(ids))

    @patch("maruth.air_quality._fetch_hourly_context", return_value=(5.2, 16.5, []))
    @patch("maruth.air_quality.get_live_air_quality", return_value={"pm2_5": 112.0, "pm10": 175.0, "co": 840.0, "no2": 36.0})
    def test_plan_impact_biosensor_and_chat_endpoints(self, _mock_live, _mock_hourly):
        # Test /api/plan
        plan_resp = self.fetch(
            "/api/plan",
            method="POST",
            body=json.dumps({"city_id": "bolpur", "api_provider": "local", "force_refresh": True}),
        )
        self.assertEqual(plan_resp.code, 200)
        plan_json = json.loads(plan_resp.body)
        self.assertEqual(plan_json["air_quality"]["city_id"], "bolpur")
        self.assertEqual(plan_json["drosophila"]["status"], "HIGH POLLUTION")
        self.assertIn("action_cards", plan_json["plan"])

        # Test /api/biosensor with custom PM2.5 stimulus
        bio_resp = self.fetch(
            "/api/biosensor",
            method="POST",
            body=json.dumps({"city_id": "bolpur", "override_pm25": 42.0, "force_rerun": True}),
        )
        self.assertEqual(bio_resp.code, 200)
        bio_json = json.loads(bio_resp.body)
        self.assertEqual(bio_json["drosophila"]["status"], "NORMAL")

        # Test /api/impact
        imp_resp = self.fetch(
            "/api/impact",
            method="POST",
            body=json.dumps({"city_id": "bolpur", "selected_interventions": ["door_window_weatherstrip", "diy_corsi_rosenthal_cr_box"]}),
        )
        self.assertEqual(imp_resp.code, 200)
        imp_json = json.loads(imp_resp.body)
        self.assertGreater(imp_json["impact"]["indoor_reduction_pct"], 25.0)

        # Test /api/chat/stream SSE response
        chat_resp = self.fetch(
            "/api/chat/stream",
            method="POST",
            body=json.dumps({"message": "When should my family open windows today?", "city_id": "bolpur", "api_provider": "local"}),
        )
        self.assertEqual(chat_resp.code, 200)
        body_text = chat_resp.body.decode("utf-8")
        self.assertIn("event: tool", body_text)
        self.assertIn("event: delta", body_text)
        self.assertIn("event: done", body_text)


if __name__ == "__main__":
    unittest.main()
