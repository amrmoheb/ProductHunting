from __future__ import annotations

import base64
import hashlib
import json
import os
import urllib.error
import urllib.request
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from .base import ResearchSource, SourceAvailability, SourceStatus

SANDBOX_URL = "https://sandbox.dataforseo.com"
PRODUCTION_URL = "https://api.dataforseo.com"
UAE_LOCATION_CODE = 2784
ENDPOINTS = {
    "user_data": "/v3/appendix/user_data",
    "labs_status": "/v3/dataforseo_labs/status",
    "locations": "/v3/dataforseo_labs/locations_and_languages",
    "recent_errors": "/v3/dataforseo_labs/errors",
    "bulk_search_volume": "/v3/dataforseo_labs/amazon/bulk_search_volume/live",
    "ranked_keywords": "/v3/dataforseo_labs/amazon/ranked_keywords/live",
    "product_competitors": "/v3/dataforseo_labs/amazon/product_competitors/live",
    "merchant_sellers": "/v3/merchant/amazon/sellers/live/advanced",
}
SECRET_KEYS = {"login", "password", "authorization", "dataforseo_login", "dataforseo_password"}
CREDENTIAL_KEYS = ("DATAFORSEO_LOGIN", "DATAFORSEO_PASSWORD")
FREE_GET_ENDPOINTS = frozenset({ENDPOINTS["user_data"], ENDPOINTS["labs_status"], ENDPOINTS["locations"]})
FREE_POST_ENDPOINTS = frozenset({ENDPOINTS["recent_errors"]})
PROVIDER_STATUS_NAMES = {
    20000:"OK", 40102:"NO_SEARCH_RESULTS", 40103:"TASK_EXECUTION_FAILED",
    40210:"INSUFFICIENT_FUNDS", 40501:"INVALID_FIELD", 40502:"EMPTY_POST_DATA",
    40503:"INVALID_POST_DATA", 40505:"OUTDATED_LOCATION_DATA",
    40506:"UNKNOWN_FIELDS", 50303:"UPDATE_IN_PROGRESS", 50304:"FUNCTION_UNAVAILABLE",
}


class DataForSEOMode(str, Enum):
    DISABLED = "disabled"
    SANDBOX = "sandbox"
    PRODUCTION = "production"


class EvidenceEnvironment(str, Enum):
    SANDBOX_DUMMY = "SANDBOX_DUMMY"
    PRODUCTION = "PRODUCTION"


def _bool(value: str | None) -> bool:
    return str(value or "").lower() == "true"


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: ("[REDACTED]" if k.lower() in SECRET_KEYS else redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str) and value.lower().startswith("basic "):
        return "[REDACTED]"
    return value


def _provider_status(payload: dict[str, Any]) -> tuple[Any, Any]:
    code=payload.get("status_code"); message=payload.get("status_message")
    if code in (None,20000):
        task=next(iter(payload.get("tasks") or []),{})
        if task.get("status_code") not in (None,20000): code=task.get("status_code"); message=task.get("status_message")
    return code,message


def _safe_provider_message(message: Any, payload: dict[str,Any], extra_secrets: tuple[str,...]=()) -> str | None:
    if message is None: return None
    text=str(message)[:500]
    secrets=[]
    def visit(value):
        if isinstance(value,dict):
            for key,item in value.items():
                if key.lower() in SECRET_KEYS and isinstance(item,str): secrets.append(item)
                else: visit(item)
        elif isinstance(value,list):
            for item in value: visit(item)
    visit(payload)
    secrets.extend(extra_secrets)
    for secret in secrets:
        if secret: text=text.replace(secret,"[REDACTED]")
    text=re.sub(r"(?i)authorization\s*:\s*basic\s+[^\s,;]+","Authorization: [REDACTED]",text)
    text=re.sub(r"(?i)basic\s+[A-Za-z0-9+/=]{8,}","[REDACTED]",text)
    return text


def sanitize_provider_payload(value: Any, secrets: tuple[str,...]=()) -> Any:
    if isinstance(value,dict):
        return {key:("[REDACTED]" if key.lower() in SECRET_KEYS else sanitize_provider_payload(item,secrets)) for key,item in value.items()}
    if isinstance(value,list): return [sanitize_provider_payload(item,secrets) for item in value]
    if isinstance(value,str): return _safe_provider_message(value,{},secrets)
    return value


def safe_http_error(exc: urllib.error.HTTPError) -> dict[str, Any]:
    content_type=exc.headers.get("Content-Type") if exc.headers else None
    server=exc.headers.get("Server") if exc.headers else None
    payload: dict[str,Any]={}
    try:
        decoded=json.loads(exc.read().decode("utf-8","replace"))
        if isinstance(decoded,dict): payload=decoded
    except Exception: pass  # Never echo an HTML/text error body.
    code,message=_provider_status(payload); message=_safe_provider_message(message,payload)
    classification="ACCOUNT_VERIFICATION_REQUIRED" if code==40104 else "HTTP_ERROR"
    return {"http_status":exc.code,"provider_status_code":code,"provider_status_message":message,"content_type":content_type,"server":server,"classification":classification}

def _cache_safe(value: Any) -> Any:
    if isinstance(value, dict): return {k:_cache_safe(v) for k,v in value.items() if k.lower() not in SECRET_KEYS}
    if isinstance(value, list): return [_cache_safe(v) for v in value]
    return value


def repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def load_dataforseo_environment(root: str | Path | None = None) -> list[str]:
    """Load DataForSEO configuration without normalizing malformed credentials.

    DATAFORSEO_PASSWORD means the API password from DataForSEO API Access, which
    can be distinct from the password used to sign in to the DataForSEO account.
    Existing process values intentionally win over .env and are diagnosed below.
    """
    root_path = Path(root).resolve() if root is not None else repository_root()
    env_path = root_path / ".env"
    diagnostics: list[str] = []
    if not env_path.is_file():
        diagnostics.append("DOTENV_NOT_LOADED_FROM_REPOSITORY_ROOT")
        dotenv: dict[str, str] = {}
    else:
        dotenv = {}
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if not line or line.lstrip().startswith("#") or "=" not in line: continue
            key, value = line.split("=", 1); key = key.strip()
            if key in {*CREDENTIAL_KEYS, "DATAFORSEO_MODE", "DATAFORSEO_ALLOW_PAID", "DATAFORSEO_MAX_COST_USD_PER_RUN", "DATAFORSEO_MAX_TASKS_PER_RUN"}:
                dotenv[key] = value
        for key, value in dotenv.items():
            if key not in os.environ: os.environ[key] = value
    for key in CREDENTIAL_KEYS:
        label = key.removeprefix("DATAFORSEO_")
        process_present = key in os.environ
        value = os.environ.get(key)
        file_value = dotenv.get(key)
        if not process_present and file_value is None: diagnostics.append(f"{label}_VARIABLE_MISSING")
        elif value == "": diagnostics.append(f"{label}_VARIABLE_EMPTY")
        if value and value != value.strip(): diagnostics.append(f"{label}_LEADING_OR_TRAILING_WHITESPACE")
        stripped = value.strip() if value else ""
        if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in {'\"', "'"}: diagnostics.append(f"{label}_SURROUNDING_QUOTES_INCLUDED")
        if process_present and file_value is not None and value != file_value:
            diagnostics.append(f"{label}_PROCESS_ENV_OVERRIDES_DOTENV")
    return diagnostics


@dataclass(frozen=True)
class DataForSEOSettings:
    mode: DataForSEOMode = DataForSEOMode.DISABLED
    allow_paid: bool = False
    max_cost_usd_per_run: float = .25
    max_tasks_per_run: int = 10
    login: str | None = None
    password: str | None = None

    @classmethod
    def from_environment(cls, *, load_dotenv: bool = True) -> "DataForSEOSettings":
        if load_dotenv: load_dataforseo_environment()
        raw = os.getenv("DATAFORSEO_MODE", "disabled").lower()
        try: mode = DataForSEOMode(raw)
        except ValueError: raise ValueError("DATAFORSEO_MODE must be disabled, sandbox, or production") from None
        return cls(mode, _bool(os.getenv("DATAFORSEO_ALLOW_PAID", "false")), max(0.0, float(os.getenv("DATAFORSEO_MAX_COST_USD_PER_RUN", ".25"))), max(0, int(os.getenv("DATAFORSEO_MAX_TASKS_PER_RUN", "10"))), os.getenv("DATAFORSEO_LOGIN") or None, os.getenv("DATAFORSEO_PASSWORD") or None)

    @property
    def base_url(self) -> str:
        return SANDBOX_URL if self.mode == DataForSEOMode.SANDBOX else PRODUCTION_URL

    @property
    def environment(self) -> EvidenceEnvironment:
        return EvidenceEnvironment.SANDBOX_DUMMY if self.mode == DataForSEOMode.SANDBOX else EvidenceEnvironment.PRODUCTION


@dataclass
class DataForSEOBudget:
    allow_paid: bool = False
    max_cost_usd: float = .25
    max_tasks: int = 10
    tasks_attempted: int = 0
    tasks_succeeded: int = 0
    tasks_failed: int = 0
    provider_reported_cost: float = 0.0
    items_returned: int = 0
    cache_hits: int = 0

    @classmethod
    def from_settings(cls, settings: DataForSEOSettings) -> "DataForSEOBudget":
        return cls(settings.allow_paid, settings.max_cost_usd_per_run, settings.max_tasks_per_run)

    def authorize(self, environment: EvidenceEnvironment, estimated_cost: float = 0.0) -> None:
        if environment == EvidenceEnvironment.PRODUCTION and not self.allow_paid:
            raise PermissionError("DataForSEO production calls require DATAFORSEO_ALLOW_PAID=true")
        if self.tasks_attempted + 1 > self.max_tasks:
            raise PermissionError("DataForSEO local task limit would be exceeded")
        if self.provider_reported_cost + estimated_cost > self.max_cost_usd:
            raise PermissionError("DataForSEO local cost limit would be exceeded")
        self.tasks_attempted += 1

    def record(self, response: dict[str, Any], succeeded: bool) -> None:
        cost = provider_cost(response)
        if self.provider_reported_cost + cost > self.max_cost_usd:
            self.tasks_failed += 1
            raise PermissionError("DataForSEO provider-reported cost exceeds the local run limit")
        self.provider_reported_cost = round(self.provider_reported_cost + cost, 8)
        self.tasks_succeeded += int(succeeded); self.tasks_failed += int(not succeeded)
        self.items_returned += count_items(response)

    def as_dict(self) -> dict[str, Any]:
        return {**asdict(self), "remaining_local_task_budget": max(0, self.max_tasks-self.tasks_attempted), "remaining_local_cost_budget": round(max(0.0, self.max_cost_usd-self.provider_reported_cost), 8), "limits_are_local_not_account_balance": True}


def provider_cost(payload: dict[str, Any]) -> float:
    costs = [float(payload.get("cost") or 0)]
    costs += [float(task.get("cost") or 0) for task in payload.get("tasks") or []]
    return max(costs, default=0.0)  # API top-level and task cost usually repeat.


def count_items(payload: dict[str, Any]) -> int:
    total = 0
    for task in payload.get("tasks") or []:
        for result in task.get("result") or []:
            total += len(result.get("items") or [])
    return total


class DataForSEOCache:
    def __init__(self, directory: str | Path = "research/cache/dataforseo"):
        self.directory = Path(directory)

    def fingerprint(self, endpoint: str, environment: EvidenceEnvironment | str, request: dict[str, Any]) -> str:
        safe = _cache_safe(request)
        payload = {"provider":"dataforseo", "endpoint":endpoint, "environment":str(getattr(environment,"value",environment)), "request":safe}
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",",":"), ensure_ascii=False).encode()).hexdigest()

    def path(self, endpoint: str, environment: EvidenceEnvironment | str, request: dict[str, Any]) -> Path:
        env = str(getattr(environment,"value",environment)).lower()
        return self.directory / env / f"{self.fingerprint(endpoint, environment, request)}.json"

    def get(self, endpoint: str, environment: EvidenceEnvironment | str, request: dict[str, Any]) -> dict[str, Any] | None:
        path=self.path(endpoint,environment,request)
        return json.loads(path.read_text()) if path.exists() else None

    def put(self, endpoint: str, environment: EvidenceEnvironment | str, request: dict[str, Any], response: dict[str, Any]) -> None:
        path=self.path(endpoint,environment,request); path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps({"environment":str(getattr(environment,"value",environment)),"response":redact(response)},sort_keys=True),encoding="utf-8")


def _task_rows(payload: dict[str, Any]):
    for task in payload.get("tasks") or []:
        for result in task.get("result") or []:
            for item in result.get("items") or []:
                yield task, result, item


def parse_locations(payload: dict[str, Any]) -> dict[str, Any]:
    rows=[]
    for task in payload.get("tasks") or []:
        rows.extend(task.get("result") or [])
    uae=next((r for r in rows if r.get("location_code")==UAE_LOCATION_CODE or r.get("country_iso_code")=="AE"),None)
    languages=[]
    for language in (uae or {}).get("available_languages") or []:
        sources={str(x).lower() for x in language.get("available_sources") or []}
        if "amazon" in sources: languages.append({"language_name":language.get("language_name"),"language_code":language.get("language_code")})
    return {"location_name":(uae or {}).get("location_name","United Arab Emirates"),"location_code":(uae or {}).get("location_code",UAE_LOCATION_CODE),"supported_languages":languages,"provider_support_status":"SUPPORTED" if languages else "UNAVAILABLE_OR_NOT_CONFIRMED"}


def parse_uae_location_diagnostic(payload: dict[str, Any]) -> dict[str, Any]:
    rows=[]
    for task in payload.get("tasks") or []: rows.extend(task.get("result") or [])
    uae=next((r for r in rows if r.get("location_code")==UAE_LOCATION_CODE),None)
    languages=[{"language_name":x.get("language_name"),"language_code":x.get("language_code"),"available_sources":list(x.get("available_sources") or [])} for x in (uae or {}).get("available_languages") or []]
    return {"uae_location_exists":uae is not None,"languages":languages}


def parse_labs_status(payload: dict[str, Any]) -> dict[str, Any]:
    result={}
    for task in payload.get("tasks") or []:
        if task.get("result"): result=task["result"][0] or {}; break
    amazon=result.get("amazon") if isinstance(result,dict) else None
    return {"amazon_labs_status_exists":isinstance(amazon,dict),"amazon_last_update":amazon.get("date_update") if isinstance(amazon,dict) else None}


class DataForSEOHTTPError(RuntimeError):
    def __init__(self, details: dict[str,Any]):
        self.details=details
        code=details.get("provider_status_code"); message=details.get("provider_status_message")
        suffix=f"; provider status {code}: {message}" if code is not None else ""
        super().__init__(f"DataForSEO request failed with HTTP {details.get('http_status')}{suffix}; credentials and Authorization were redacted")


class DataForSEOProviderError(RuntimeError):
    def __init__(self, code: Any, message: Any, cost: float, payload: dict[str,Any], secrets: tuple[str,...]=()):
        self.status_code=code; self.status_name=PROVIDER_STATUS_NAMES.get(code,"UNMAPPED_PROVIDER_STATUS")
        self.status_message=_safe_provider_message(message,payload,secrets); self.provider_reported_cost=cost
        super().__init__(f"DataForSEO provider status_code: {code} ({self.status_name}); DataForSEO provider status_message: {self.status_message or 'UNAVAILABLE'}; Provider reported cost: {cost}")


def parse_recent_errors(payload: dict[str,Any]) -> list[dict[str,Any]]:
    rows=[]
    for task in payload.get("tasks") or []:
        for item in task.get("result") or []:
            if not isinstance(item,dict): continue
            rows.append({"datetime":item.get("datetime"),"function":item.get("function"),"error_code":item.get("error_code"),"error_message":item.get("error_message"),"http_code":item.get("http_code"),"endpoint":item.get("http_url") or item.get("path")})
    return rows


def parse_bulk_search_volume(payload: dict[str, Any], environment: EvidenceEnvironment) -> list[dict[str, Any]]:
    now=datetime.now(timezone.utc).isoformat(); rows=[]
    for task,result,item in _task_rows(payload):
        rows.append({"keyword":item.get("keyword"),"search_volume":item.get("search_volume"),"search_volume_present":"search_volume" in item,"location_code":result.get("location_code") or task.get("data",{}).get("location_code"),"language_code":result.get("language_code") or task.get("data",{}).get("language_code"),"last_updated":item.get("last_updated_time") or item.get("last_updated") or now,"provider_cost":float(task.get("cost") or 0),"environment":environment.value,"score_eligible":False})
    return rows


def parse_ranked_keywords(payload: dict[str, Any], environment: EvidenceEnvironment) -> list[dict[str, Any]]:
    now=datetime.now(timezone.utc).isoformat(); rows=[]
    for task,_,item in _task_rows(payload):
        kd=item.get("keyword_data") or {}; info=kd.get("keyword_info") or {}; ranked=item.get("ranked_serp_element") or {}; serp=ranked.get("serp_item") or {}
        rows.append({"target_asin":task.get("data",{}).get("asin"),"keyword":kd.get("keyword") or item.get("keyword"),"search_volume":info.get("search_volume"),"organic_position":ranked.get("serp_item",{}).get("rank_absolute") if serp.get("type")!="paid" else None,"paid_position":serp.get("rank_absolute") if serp.get("type")=="paid" else item.get("paid_position"),"ranking_information":redact(ranked),"last_updated":kd.get("last_updated_time") or item.get("last_updated_time") or now,"provider_cost":float(task.get("cost") or 0),"environment":environment.value,"score_eligible":False})
    return rows


def parse_product_competitors(payload: dict[str, Any], environment: EvidenceEnvironment) -> list[dict[str, Any]]:
    rows=[]
    for task,_,item in _task_rows(payload):
        rows.append({"target_asin":task.get("data",{}).get("asin"),"competitor_asin":item.get("asin") or item.get("target"),"keyword_intersections":item.get("intersections") or item.get("keywords_count"),"average_position":item.get("avg_position") or item.get("average_position"),"organic_metrics":item.get("organic") or item.get("organic_metrics"),"paid_metrics":item.get("paid") or item.get("paid_metrics"),"total_search_volume_related_metrics":item.get("metrics") or item.get("full_domain_metrics") or item.get("search_volume"),"provider_cost":float(task.get("cost") or 0),"environment":environment.value,"score_eligible":False})
    return rows


def parse_merchant_sellers(payload: dict[str, Any], environment: EvidenceEnvironment) -> list[dict[str, Any]]:
    return [{"seller_id":item.get("seller_id"),"seller_name":item.get("seller_name") or item.get("title"),"price":item.get("price"),"rating":item.get("rating"),"environment":environment.value,"score_eligible":False} for _,_,item in _task_rows(payload)]


class DataForSEOSource(ResearchSource):
    name="DataForSEO"; paid=True; required_env=("DATAFORSEO_LOGIN","DATAFORSEO_PASSWORD")
    def __init__(self, settings: DataForSEOSettings | None=None): self.settings=settings or DataForSEOSettings.from_environment()
    def status(self) -> SourceStatus:
        if not self.settings.login or not self.settings.password: return SourceStatus(self.name,SourceAvailability.NOT_CONFIGURED,"credentials missing")
        if self.settings.mode==DataForSEOMode.DISABLED: return SourceStatus(self.name,SourceAvailability.NOT_CONFIGURED,"disabled by default")
        return SourceStatus(self.name,SourceAvailability.READY,f"{self.settings.mode.value}; UAE support must be capability-validated")
    @staticmethod
    def _authorized_request(url: str, login: str, password: str, *, method: str="GET", data: bytes | None=None) -> urllib.request.Request:
        # DataForSEO API credentials are API_LOGIN:API_PASSWORD, not necessarily
        # the credentials used for the account UI. A preemptive header is needed
        # because API clients cannot rely on an authentication challenge round trip.
        token=base64.b64encode(f"{login}:{password}".encode("utf-8")).decode("ascii")
        return urllib.request.Request(url,data=data,method=method,headers={"Authorization":f"Basic {token}","Content-Type":"application/json","User-Agent":"amazon-uae-product-scout/1.4A"})

    def free_get(self, endpoint: str) -> dict[str,Any]:
        if endpoint not in FREE_GET_ENDPOINTS: raise PermissionError("Endpoint is not allowlisted as a zero-cost DataForSEO GET diagnostic")
        if not self.settings.login or not self.settings.password: return {"http_status":None,"status_code":"CONFIGURATION_ERROR","status_message":"credentials missing","payload":{}}
        req=self._authorized_request(PRODUCTION_URL+endpoint,self.settings.login,self.settings.password)
        try:
            with urllib.request.urlopen(req,timeout=30) as response: payload=json.loads(response.read()); http_status=getattr(response,"status",200)
            code,message=_provider_status(payload)
            return {"http_status":http_status,"status_code":code,"status_message":message,"payload":redact(payload),"content_type":response.headers.get("Content-Type") if getattr(response,"headers",None) else None,"server":response.headers.get("Server") if getattr(response,"headers",None) else None,"classification":"ACCOUNT_VERIFICATION_REQUIRED" if code==40104 else "OK"}
        except urllib.error.HTTPError as exc:
            details=safe_http_error(exc)
            return {"http_status":details["http_status"],"status_code":details["provider_status_code"],"status_message":details["provider_status_message"],"payload":{},"content_type":details["content_type"],"server":details["server"],"classification":details["classification"]}
        except Exception:
            return {"http_status":None,"status_code":"REQUEST_ERROR","status_message":"request failed safely","payload":{},"content_type":None,"server":None,"classification":"HTTP_ERROR"}

    def free_post(self, endpoint: str, task: dict[str,Any]) -> dict[str,Any]:
        if endpoint not in FREE_POST_ENDPOINTS: raise PermissionError("Endpoint is not allowlisted as a zero-cost DataForSEO POST diagnostic")
        if not self.settings.login or not self.settings.password: return {"http_status":None,"status_code":"CONFIGURATION_ERROR","status_message":"credentials missing","payload":{}}
        data=json.dumps([task]).encode("utf-8"); req=self._authorized_request(PRODUCTION_URL+endpoint,self.settings.login,self.settings.password,method="POST",data=data)
        secrets=(self.settings.login,self.settings.password)
        try:
            with urllib.request.urlopen(req,timeout=30) as response: payload=json.loads(response.read()); http_status=getattr(response,"status",200)
            code,message=_provider_status(payload)
            return {"http_status":http_status,"status_code":code,"status_message":_safe_provider_message(message,payload,secrets),"payload":sanitize_provider_payload(payload,secrets)}
        except urllib.error.HTTPError as exc:
            details=safe_http_error(exc); return {"http_status":details["http_status"],"status_code":details["provider_status_code"],"status_message":details["provider_status_message"],"payload":{}}
        except Exception:
            return {"http_status":None,"status_code":"REQUEST_ERROR","status_message":"request failed safely","payload":{}}

    def user_data(self) -> dict[str, Any]:
        """Call only DataForSEO's zero-cost authentication/account endpoint."""
        if not self.settings.login or not self.settings.password: return {"auth":"FAIL","http_status":None,"api_status_code":"CONFIGURATION_ERROR","account_balance":None}
        req=self._authorized_request(PRODUCTION_URL+ENDPOINTS["user_data"],self.settings.login,self.settings.password)
        try:
            with urllib.request.urlopen(req,timeout=30) as response:
                payload=json.loads(response.read()); http_status=getattr(response,"status",200)
            api_code=payload.get("status_code"); result=(payload.get("tasks") or [{}])[0].get("result") or []
            user=result[0] if result and isinstance(result[0],dict) else payload.get("result") or {}
            balance=user.get("money",{}).get("balance") if isinstance(user.get("money"),dict) else user.get("balance")
            if not isinstance(balance,(int,float)): balance=None
            return {"auth":"PASS" if http_status==200 and int(api_code or 0)==20000 else "FAIL","http_status":http_status,"api_status_code":api_code,"account_balance":balance}
        except urllib.error.HTTPError as exc:
            api_code=None
            try: api_code=json.loads(exc.read()).get("status_code")
            except Exception: pass
            return {"auth":"FAIL","http_status":exc.code,"api_status_code":api_code,"account_balance":None}
        except Exception:
            return {"auth":"FAIL","http_status":None,"api_status_code":"REQUEST_ERROR","account_balance":None}
    def request(self, endpoint: str, task: dict[str,Any] | None, budget: DataForSEOBudget, cache: DataForSEOCache | None=None, *, estimated_cost: float=0.0, method: str="POST") -> tuple[dict[str,Any],bool]:
        if self.settings.mode==DataForSEOMode.DISABLED: raise PermissionError("DataForSEO is disabled")
        if not self.settings.login or not self.settings.password: raise PermissionError("DataForSEO credentials are missing")
        request_data=task or {}; env=self.settings.environment
        if cache and (cached:=cache.get(endpoint,env,request_data)) is not None: budget.cache_hits+=1; return cached["response"],True
        budget.authorize(env,estimated_cost)
        data=None if method=="GET" else json.dumps([request_data]).encode()
        req=self._authorized_request(self.settings.base_url+endpoint,self.settings.login,self.settings.password,method=method,data=data)
        try:
            with urllib.request.urlopen(req,timeout=30) as response: payload=json.loads(response.read())
            code,message=_provider_status(payload); ok=code==20000 and not int(payload.get("tasks_error",0) or 0); budget.record(payload,ok)
            if not ok: raise DataForSEOProviderError(code,message,provider_cost(payload),payload,(self.settings.login,self.settings.password))
            if cache: cache.put(endpoint,env,request_data,payload)
            return payload,False
        except urllib.error.HTTPError as exc:
            if budget.tasks_succeeded+budget.tasks_failed < budget.tasks_attempted: budget.tasks_failed+=1
            raise DataForSEOHTTPError(safe_http_error(exc)) from None
        except Exception as exc:
            if budget.tasks_succeeded+budget.tasks_failed < budget.tasks_attempted: budget.tasks_failed+=1
            if isinstance(exc,(PermissionError,RuntimeError)): raise
            raise RuntimeError("DataForSEO request failed; credentials and Authorization were redacted") from None
