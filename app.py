"""Tornado async web server for Maruth: REST APIs, SSE GenAI chat, and static dashboard serving."""

from __future__ import annotations

import json
import os
from typing import Any
import tornado.ioloop
import tornado.web
from pydantic import BaseModel, Field

from maruth.air_quality import geocode_city, get_city_air_quality, get_presets
from maruth.bio_sensor import evaluate_drosophila_sensor
from maruth.genai_orchestrator import (
    generate_action_plan,
    get_optimization_stats,
    stream_chat_reply,
)
from maruth.impact_engine import calculate_impact_delta, get_default_interventions
from maruth.schemas import ChatRequest, HouseholdProfile

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


class PlanRequest(BaseModel):
    city_id: str = "bolpur"
    custom_city_query: str | None = None
    profile: HouseholdProfile = Field(default_factory=HouseholdProfile)
    selected_interventions: list[str] | None = None
    api_provider: str = "auto"
    api_key: str | None = None
    force_refresh: bool = False


class ImpactRequest(BaseModel):
    city_id: str = "bolpur"
    profile: HouseholdProfile = Field(default_factory=HouseholdProfile)
    selected_interventions: list[str] = Field(default_factory=list)


class BioSensorRequest(BaseModel):
    city_id: str = "bolpur"
    override_pm25: float | None = Field(default=None, ge=0.0, le=1000.0)
    force_rerun: bool = True


class BaseJSONHandler(tornado.web.RequestHandler):
    def set_default_headers(self) -> None:
        self.set_header("Content-Type", "application/json; charset=utf-8")
        self.set_header("Cache-Control", "no-store")

    def write_json(self, payload: Any, status: int = 200) -> None:
        self.set_status(status)
        if isinstance(payload, BaseModel):
            self.finish(payload.model_dump_json())
        else:
            self.finish(json.dumps(payload))

    def parse_json_body(self) -> dict[str, Any]:
        if not self.request.body:
            return {}
        return json.loads(self.request.body.decode("utf-8"))


class PresetsHandler(BaseJSONHandler):
    def get(self) -> None:
        self.write_json({"presets": [p.model_dump() for p in get_presets()]})


class AirQualityHandler(BaseJSONHandler):
    def get(self) -> None:
        city_id = self.get_argument("city_id", "bolpur")
        query = self.get_argument("q", "").strip()
        force = self.get_argument("refresh", "false").lower() == "true"

        custom = geocode_city(query) if query else None
        if query and custom is None:
            self.write_json({"error": f"Could not find city '{query}'."}, status=404)
            return

        report = get_city_air_quality(city_id=city_id, custom_city=custom, force_refresh=force)
        bio = evaluate_drosophila_sensor(report)
        self.write_json({"air_quality": report.model_dump(), "drosophila": bio.model_dump()})


class BioSensorHandler(BaseJSONHandler):
    def post(self) -> None:
        try:
            req = BioSensorRequest(**self.parse_json_body())
        except Exception as exc:
            self.write_json({"error": str(exc)}, status=400)
            return

        report = get_city_air_quality(city_id=req.city_id)
        bio = evaluate_drosophila_sensor(
            report,
            override_pm25=req.override_pm25,
            force_rerun=req.force_rerun,
        )
        self.write_json({"drosophila": bio.model_dump(), "air_quality_city": report.city_name})


class PlanHandler(BaseJSONHandler):
    async def post(self) -> None:
        try:
            req = PlanRequest(**self.parse_json_body())
        except Exception as exc:
            self.write_json({"error": str(exc)}, status=400)
            return

        custom = geocode_city(req.custom_city_query) if req.custom_city_query else None
        air = get_city_air_quality(
            city_id=req.city_id,
            custom_city=custom,
            force_refresh=req.force_refresh,
        )
        bio = evaluate_drosophila_sensor(air, force_rerun=req.force_refresh)
        profile = req.profile.model_copy(update={"city_id": air.city_id})
        plan = await generate_action_plan(
            air=air,
            brain=bio,
            profile=profile,
            selected_interventions=req.selected_interventions,
            api_provider=req.api_provider,
            api_key=req.api_key,
        )
        self.write_json(
            {
                "air_quality": air.model_dump(),
                "drosophila": bio.model_dump(),
                "plan": plan.model_dump(),
                "default_selected": get_default_interventions(profile),
            }
        )


class ImpactHandler(BaseJSONHandler):
    def post(self) -> None:
        try:
            req = ImpactRequest(**self.parse_json_body())
        except Exception as exc:
            self.write_json({"error": str(exc)}, status=400)
            return

        air = get_city_air_quality(city_id=req.city_id)
        summary = calculate_impact_delta(air, req.profile, req.selected_interventions)
        self.write_json({"impact": summary.model_dump()})


class ChatStreamHandler(tornado.web.RequestHandler):
    async def post(self) -> None:
        self.set_header("Content-Type", "text/event-stream; charset=utf-8")
        self.set_header("Cache-Control", "no-cache")
        self.set_header("X-Accel-Buffering", "no")
        try:
            body = json.loads(self.request.body.decode("utf-8"))
            req = ChatRequest(**body)
        except Exception as exc:
            self.write(f"event: error\ndata: {json.dumps({'error': str(exc)})}\n\n")
            await self.flush()
            self.finish()
            return

        async for chunk in stream_chat_reply(req):
            self.write(chunk)
            await self.flush()
        self.finish()


class TelemetryHandler(BaseJSONHandler):
    def get(self) -> None:
        self.write_json({"optimization_stats": get_optimization_stats()})


class IndexHandler(tornado.web.RequestHandler):
    def get(self) -> None:
        index_path = os.path.join(STATIC_DIR, "index.html")
        with open(index_path, "r", encoding="utf-8") as fh:
            self.set_header("Content-Type", "text/html; charset=utf-8")
            self.finish(fh.read())


def make_app() -> tornado.web.Application:
    return tornado.web.Application(
        [
            (r"/", IndexHandler),
            (r"/api/presets", PresetsHandler),
            (r"/api/air-quality", AirQualityHandler),
            (r"/api/biosensor", BioSensorHandler),
            (r"/api/plan", PlanHandler),
            (r"/api/impact", ImpactHandler),
            (r"/api/chat/stream", ChatStreamHandler),
            (r"/api/telemetry", TelemetryHandler),
            (r"/static/(.*)", tornado.web.StaticFileHandler, {"path": STATIC_DIR}),
        ],
        debug=False,
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app = make_app()
    app.listen(port)
    print(f"Maruth GenAI Air Quality Dashboard running on http://localhost:{port}")
    tornado.ioloop.IOLoop.current().start()
