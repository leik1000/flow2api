"""Flow captcha standalone service client."""
from __future__ import annotations

from typing import Any, Dict, Optional
from urllib.parse import urljoin

from curl_cffi.requests import AsyncSession

from ..core.config import config


class FlowCaptchaService:
    """Client for upstream Flow captcha service."""

    SERVICE_NAME = "Flow-RecaptchaV3TaskProxylessM1"
    TASK_TYPE = "RecaptchaV3TaskProxylessM1"
    PROVIDER = "browser"
    PRICING = {
        "currency": "CNY",
        "price_per_1000_tasks": 15.0,
        "price_per_task": 0.015,
        "points_per_task": 15.0,
    }
    FLOW_PROJECT_URL_PREFIX = "https://labs.google/fx/tools/flow/project/"

    async def get_token(self, *, project_id: Optional[str], page_action: str = "IMAGE_GENERATION") -> Optional[str]:
        if not project_id:
            return None
        result = await self.solve(project_id=project_id, website_url=None, page_action=page_action)
        return result.get("token")

    async def solve(
        self,
        *,
        project_id: Optional[str],
        website_url: Optional[str],
        page_action: str,
    ) -> Dict[str, Any]:
        base_url = (config.flow_captcha_service_base_url or "").strip()
        solve_path = (config.flow_captcha_service_solve_path or "").strip()
        api_key = (config.flow_captcha_service_api_key or "").strip()
        timeout_seconds = config.flow_captcha_service_timeout_seconds

        if not base_url:
            raise ValueError("FlowCaptchaServiceBaseURL is not configured")
        if not solve_path:
            raise ValueError("FlowCaptchaServiceSolvePath is not configured")
        if not api_key:
            raise ValueError("FlowCaptchaServiceApiKey is not configured")

        resolved_website_url = (website_url or "").strip()
        if not resolved_website_url and project_id:
            resolved_website_url = f"{self.FLOW_PROJECT_URL_PREFIX}{project_id}"

        payload: Dict[str, Any] = {
            "page_action": page_action,
        }
        if project_id:
            payload["project_id"] = project_id
        if resolved_website_url:
            payload["website_url"] = resolved_website_url

        request_url = urljoin(base_url.rstrip("/") + "/", solve_path.lstrip("/"))

        try:
            async with AsyncSession() as session:
                response = await session.post(
                    request_url,
                    json=payload,
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=timeout_seconds,
                    impersonate="chrome110",
                )
        except Exception as e:
            raise RuntimeError(f"flow captcha service error: request failed: {str(e)}") from e

        response_json: Dict[str, Any]
        try:
            response_json = response.json()
        except Exception:
            text_preview = (response.text or "")[:200]
            raise RuntimeError(
                f"flow captcha service error: invalid json response (status={response.status_code}): {text_preview}"
            )

        if response.status_code >= 400:
            upstream_message = self._extract_error_message(response_json)
            raise RuntimeError(
                f"flow captcha service error: upstream status {response.status_code}: {upstream_message}"
            )

        if isinstance(response_json.get("error"), dict):
            upstream_message = self._extract_error_message(response_json)
            raise RuntimeError(f"flow captcha service error: {upstream_message}")

        token = (
            response_json.get("token")
            or response_json.get("gRecaptchaResponse")
            or response_json.get("g_recaptcha_response")
            or response_json.get("solution", {}).get("gRecaptchaResponse")
        )
        if not token:
            raise RuntimeError("flow captcha service error: missing token in upstream response")

        return {
            "name": self.SERVICE_NAME,
            "object": "captcha.solution",
            "provider": self.PROVIDER,
            "page_action": page_action,
            "token": token,
            "duration_ms": self._to_int(response_json.get("duration_ms")),
            "browser_id": self._to_int(response_json.get("browser_id"), default=0),
            "task_type": self.TASK_TYPE,
            "pricing": self.PRICING,
        }

    @staticmethod
    def _extract_error_message(response_json: Dict[str, Any]) -> str:
        err = response_json.get("error")
        if isinstance(err, dict):
            return str(err.get("message") or err.get("error") or response_json)
        if isinstance(err, str):
            return err
        if isinstance(response_json.get("message"), str):
            return response_json["message"]
        return str(response_json)

    @staticmethod
    def _to_int(value: Any, default: int = 0) -> int:
        try:
            if value is None:
                return default
            return int(value)
        except Exception:
            return default
