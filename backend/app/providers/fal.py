"""FAL.AI 실연동 프로바이더.
큐 API: POST https://queue.fal.run/{model} → status_url 폴링 → result에서 URL 추출.
키는 환경변수 FAL_API_KEY에서만 읽는다 (코드에 절대 하드코딩 금지).
"""
import os
import time
import logging

from dataclasses import dataclass

log = logging.getLogger(__name__)

QUEUE_BASE = "https://queue.fal.run"


@dataclass
class Estimate:
    credits: int
    eta_seconds: int


# 내부 크레딧 단가표 (초안 — FAL 실제 요금과 별개, /v1/models/pricing 기준으로 주기 조정)
PRICING = {
    "video:kling": {"credits": 50, "eta": 180},
    "video:veo": {"credits": 80, "eta": 240},
    "video:ltx": {"credits": 10, "eta": 60},
    "image:flux": {"credits": 5, "eta": 20},
    "image:nanobanana": {"credits": 5, "eta": 20},
}

# kind → (FAL endpoint, input 빌더). endpoint ID는 FAL 대시보드에서 주기 확인.
MODEL_MAP = {
    "image:flux": ("fal-ai/flux/schnell",
                   lambda p: {"prompt": p.get("prompt", ""),
                              "image_size": "landscape_16_9", "num_images": 1}),
    "image:nanobanana": ("fal-ai/nano-banana",
                         lambda p: {"prompt": p.get("prompt", "")}),
    "video:ltx": ("fal-ai/ltx-video-13b-distilled",
                  lambda p: {"prompt": p.get("prompt", "")}),
    "video:kling": ("fal-ai/kling-video/v2.1/standard/text-to-video",
                    lambda p: {"prompt": p.get("prompt", ""),
                               "duration": "5", "aspect_ratio": "16:9"}),
    "video:veo": ("fal-ai/veo3",
                  lambda p: {"prompt": p.get("prompt", "")}),
}


class Provider:
    def estimate(self, kind: str, params: dict) -> Estimate:
        raise NotImplementedError

    def run(self, kind: str, params: dict) -> str:
        raise NotImplementedError


class StubProvider(Provider):
    """키 없이 동작 확인용."""

    def estimate(self, kind: str, params: dict) -> Estimate:
        p = PRICING.get(kind, {"credits": 20, "eta": 60})
        return Estimate(credits=p["credits"], eta_seconds=p["eta"])

    def run(self, kind: str, params: dict) -> str:
        time.sleep(2)
        return f"https://cdn.example.invalid/outputs/{kind.replace(':', '_')}_{int(time.time())}.mp4"


class FalProvider(Provider):
    def __init__(self, api_key: str):
        import httpx
        self._httpx = httpx
        self.api_key = api_key
        # 프록시 환경(VM egress 등)에서도 동작하도록 명시적 구성.
        # 일반 서버에서는 proxy가 없어 직접 연결된다.
        self._proxy = os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY")
        self._verify = os.environ.get("SSL_CERT_FILE") or True

    def _headers(self):
        return {"Authorization": f"Key {self.api_key}",
                "Content-Type": "application/json"}

    def _client(self, timeout: int = 30):
        return self._httpx.Client(trust_env=False, proxy=self._proxy,
                                  verify=self._verify, timeout=timeout)

    def estimate(self, kind: str, params: dict) -> Estimate:
        p = PRICING.get(kind, {"credits": 20, "eta": 60})
        return Estimate(credits=p["credits"], eta_seconds=p["eta"])

    def _model(self, kind: str):
        if kind not in MODEL_MAP:
            raise ValueError(f"unsupported kind: {kind}")
        return MODEL_MAP[kind]

    def submit(self, kind: str, params: dict) -> tuple[str, str]:
        """(request_id, status_url) 반환. submit 자체는 과금 발생."""
        endpoint, build_input = self._model(kind)
        with self._client(timeout=30) as c:
            r = c.post(f"{QUEUE_BASE}/{endpoint}",
                       headers=self._headers(),
                       json={"input": build_input(params or {})})
        if r.status_code not in (200, 201, 202):
            raise RuntimeError(f"FAL submit failed {r.status_code}: {r.text[:300]}")
        data = r.json()
        return data["request_id"], data.get("status_url")

    def run(self, kind: str, params: dict, poll_seconds: int = 5,
            timeout_seconds: int = 1200) -> str:
        request_id, status_url = self.submit(kind, params)
        log.info("FAL submitted kind=%s request_id=%s", kind, request_id)
        deadline = time.time() + timeout_seconds
        with self._client(timeout=30) as c:
            while time.time() < deadline:
                r = c.get(status_url, headers=self._headers())
                r.raise_for_status()
                st = r.json()
                status = st.get("status")
                if status == "COMPLETED":
                    break
                if status in ("FAILED",):
                    raise RuntimeError(f"FAL job failed: {str(st)[:500]}")
                time.sleep(poll_seconds)
            else:
                raise TimeoutError(f"FAL job {request_id} timed out")
            # 결과 조회 (status_url → response_url 규칙)
            result_url = status_url.replace("/status", "")
            rr = c.get(result_url, headers=self._headers())
            rr.raise_for_status()
            out = rr.json()
        # 호출자 귀책 실패는 detail에 담겨 옴 — URL보다 먼저 확인
        if isinstance(out, dict) and out.get("detail"):
            raise RuntimeError(f"FAL returned detail (no output): {str(out['detail'])[:500]}")
        url = None
        if isinstance(out, dict):
            if isinstance(out.get("video"), dict):
                url = out["video"].get("url")
            elif isinstance(out.get("images"), list) and out["images"]:
                url = out["images"][0].get("url")
        if not url:
            raise RuntimeError(f"FAL output has no URL: {str(out)[:500]}")
        return url


def get_provider() -> Provider:
    if os.environ.get("FAL_API_KEY"):
        return FalProvider(os.environ["FAL_API_KEY"])
    return StubProvider()
