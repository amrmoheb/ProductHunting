import json
import base64
import inspect
import urllib.error
import io
from pathlib import Path
from unittest.mock import patch
import pytest

from amazon_scout.dataforseo_audit import (AmazonKeywordCluster, CompetitionAudit, DemandAudit, POC_KEYWORDS, assert_audit_only, prepare_poc_mappings, select_representative_asins)
from amazon_scout.dataforseo_doctor import _bulk_probe_task, main
from amazon_scout.research_pipeline import source_status_from_evidence
from amazon_scout.sources.dataforseo import *

def response(items, data=None, cost=.01):
    return {"status_code":20000,"cost":cost,"tasks":[{"status_code":20000,"cost":cost,"data":data or {},"result":[{"location_code":2784,"language_code":"ar","items":items}]}]}

def test_environment_loading(monkeypatch):
    for key in ("DATAFORSEO_MODE","DATAFORSEO_ALLOW_PAID","DATAFORSEO_MAX_COST_USD_PER_RUN","DATAFORSEO_MAX_TASKS_PER_RUN"): monkeypatch.delenv(key,raising=False)
    s=DataForSEOSettings.from_environment(load_dotenv=False); assert s.mode==DataForSEOMode.DISABLED and not s.allow_paid and s.max_cost_usd_per_run==.25 and s.max_tasks_per_run==10

def test_hosts():
    assert DataForSEOSettings(DataForSEOMode.SANDBOX).base_url=="https://sandbox.dataforseo.com"
    assert DataForSEOSettings(DataForSEOMode.PRODUCTION).base_url=="https://api.dataforseo.com"

def test_redaction_and_cache_excludes_secrets(tmp_path):
    secret="never-store-me"; obj=redact({"Authorization":"Basic "+secret,"password":secret,"x":1}); assert secret not in json.dumps(obj)
    cache=DataForSEOCache(tmp_path); request={"keywords":["x"],"login":secret,"password":secret}; cache.put("/x",EvidenceEnvironment.PRODUCTION,request,{"Authorization":"Basic "+secret})
    assert secret not in cache.path("/x",EvidenceEnvironment.PRODUCTION,request).name
    assert secret not in cache.path("/x",EvidenceEnvironment.PRODUCTION,request).read_text()
    assert cache.fingerprint("/x",EvidenceEnvironment.PRODUCTION,{"keywords":["x"],"password":"one"})==cache.fingerprint("/x",EvidenceEnvironment.PRODUCTION,{"keywords":["x"],"password":"two"})

def test_cache_environment_isolation(tmp_path):
    c=DataForSEOCache(tmp_path); req={"asin":"B0X","limit":1}
    assert c.path("/x",EvidenceEnvironment.PRODUCTION,req)!=c.path("/x",EvidenceEnvironment.SANDBOX_DUMMY,req)

def test_location_language_normalization():
    payload={"tasks":[{"result":[{"location_name":"United Arab Emirates","location_code":2784,"country_iso_code":"AE","available_languages":[{"language_name":"Arabic","language_code":"ar","available_sources":["amazon"]},{"language_name":"English","language_code":"en","available_sources":["google"]}]}]}]}
    result=parse_locations(payload); assert result["provider_support_status"]=="SUPPORTED" and result["supported_languages"]==[{"language_name":"Arabic","language_code":"ar"}]

def test_bulk_parser_and_production_marking():
    rows=parse_bulk_search_volume(response([{"keyword":"foot hammock","search_volume":120}]),EvidenceEnvironment.PRODUCTION)
    assert rows[0]["search_volume"]==120 and rows[0]["environment"]=="PRODUCTION" and rows[0]["score_eligible"] is False

def test_ranked_keywords_parser():
    item={"keyword_data":{"keyword":"footrest","keyword_info":{"search_volume":50}},"ranked_serp_element":{"serp_item":{"type":"organic","rank_absolute":4}}}
    row=parse_ranked_keywords(response([item],{"asin":"B0X"}),EvidenceEnvironment.SANDBOX_DUMMY)[0]; assert row["target_asin"]=="B0X" and row["organic_position"]==4

def test_product_competitors_parser():
    item={"asin":"B0Y","intersections":9,"avg_position":3.5,"organic":{"count":4},"paid":{"count":2},"metrics":{"search_volume":100}}
    row=parse_product_competitors(response([item],{"asin":"B0X"}),EvidenceEnvironment.PRODUCTION)[0]; assert row["competitor_asin"]=="B0Y" and row["keyword_intersections"]==9

def test_merchant_parser_schema():
    row=parse_merchant_sellers(response([{"seller_id":"S1","title":"Seller","price":10}]),EvidenceEnvironment.SANDBOX_DUMMY)[0]; assert row["seller_id"]=="S1" and not row["score_eligible"]

def test_sandbox_blocked_from_scoring():
    with pytest.raises(ValueError,match="prohibited from scoring"): assert_audit_only("SANDBOX_DUMMY")
    assert_audit_only("PRODUCTION")

def test_budget_guards_and_cost_parsing():
    b=DataForSEOBudget(False,.25,1)
    with pytest.raises(PermissionError): b.authorize(EvidenceEnvironment.PRODUCTION,.01)
    b.authorize(EvidenceEnvironment.SANDBOX_DUMMY); assert b.tasks_attempted==1
    with pytest.raises(PermissionError): b.authorize(EvidenceEnvironment.SANDBOX_DUMMY)
    assert provider_cost(response([],cost=.0123))==.0123
    b.record(response([],cost=.02),True); assert b.provider_reported_cost==.02 and b.as_dict()["remaining_local_task_budget"]==0
    costly=DataForSEOBudget(True,.01,2); costly.authorize(EvidenceEnvironment.PRODUCTION)
    with pytest.raises(PermissionError): costly.record(response([],cost=.02),True)

def test_representative_asins_deterministic():
    products=[{"asin":"C","current_price_aed":100,"rating":5,"reviews":1},{"asin":"A","current_price_aed":80,"rating":4,"reviews":30},{"asin":"B","current_price_aed":90,"rating":4.2,"reviews":20},{"asin":"D","current_price_aed":500}]
    selected=select_representative_asins(products); assert [x["asin"] for x in selected]==["B","A","C"] and all(x["selection_reason"] for x in selected)

def test_keyword_and_audit_models():
    cluster=AmazonKeywordCluster("primary",["related"],"existing"); assert cluster.cluster_search_volume_estimate is None and "UNKNOWN" in cluster.cluster_search_volume_status
    assert DemandAudit(50,"SUFFICIENT").old_demand_score==50
    assert CompetitionAudit(40,"PARTIAL").old_competition_status=="PARTIAL"
    assert len(POC_KEYWORDS)==5

def test_poc_candidate_mappings():
    mappings=prepare_poc_mappings([{"niche":n,"asin":"B0X","current_price_aed":50} for n in POC_KEYWORDS]); assert set(mappings)==set(POC_KEYWORDS) and all(v["representative_asins"] for v in mappings.values())

def test_official_fee_source_consistency():
    assert source_status_from_evidence([],canonical_economics_used=True)["Amazon UAE official pages"]=="USED"

def test_doctor_default_zero_call(monkeypatch,capsys):
    monkeypatch.setenv("DATAFORSEO_MODE","disabled")
    with patch("amazon_scout.sources.dataforseo.urllib.request.urlopen") as call: assert main([])==0; call.assert_not_called()
    assert "Provider calls performed: 0" in capsys.readouterr().out

def test_production_test_explicit_opt_in(monkeypatch,capsys):
    monkeypatch.setenv("DATAFORSEO_ALLOW_PAID","false"); monkeypatch.setenv("DATAFORSEO_LOGIN","x"); monkeypatch.setenv("DATAFORSEO_PASSWORD","y")
    with patch("amazon_scout.sources.dataforseo.urllib.request.urlopen") as call: assert main(["--production-test"])==2; call.assert_not_called()
    assert "REFUSED" in capsys.readouterr().out

def test_env_is_gitignored_and_placeholders_blank():
    assert ".env" in Path(".gitignore").read_text().splitlines(); example=Path(".env.example").read_text(); assert "DATAFORSEO_LOGIN=\n" in example and "DATAFORSEO_PASSWORD=\n" in example

class FakeHTTPResponse:
    status=200
    def __init__(self,payload): self.payload=json.dumps(payload).encode()
    def __enter__(self): return self
    def __exit__(self,*args): return False
    def read(self): return self.payload

def test_valid_basic_auth_construction():
    request=DataForSEOSource._authorized_request("https://api.dataforseo.com/v3/appendix/user_data","api-login","api-password")
    assert request.full_url=="https://api.dataforseo.com/v3/appendix/user_data"
    scheme,token=request.get_header("Authorization").split()
    assert scheme=="Basic" and base64.b64decode(token).decode()=="api-login:api-password"

def test_api_password_distinct_from_account_password_is_documented():
    documentation=inspect.getdoc(load_dataforseo_environment)
    assert "API password" in documentation and "distinct" in documentation and "account" in documentation

def test_quoted_and_whitespace_dotenv_detection(tmp_path,monkeypatch):
    monkeypatch.delenv("DATAFORSEO_LOGIN",raising=False); monkeypatch.delenv("DATAFORSEO_PASSWORD",raising=False)
    (tmp_path/".env").write_text('DATAFORSEO_LOGIN="quoted"\nDATAFORSEO_PASSWORD= spaced \n')
    diagnostics=load_dataforseo_environment(tmp_path)
    assert "LOGIN_SURROUNDING_QUOTES_INCLUDED" in diagnostics
    assert "PASSWORD_LEADING_OR_TRAILING_WHITESPACE" in diagnostics

def test_process_environment_override_diagnosed(tmp_path,monkeypatch):
    (tmp_path/".env").write_text("DATAFORSEO_LOGIN=file-login\nDATAFORSEO_PASSWORD=file-password\n")
    monkeypatch.setenv("DATAFORSEO_LOGIN","stale-process-login"); monkeypatch.setenv("DATAFORSEO_PASSWORD","")
    diagnostics=load_dataforseo_environment(tmp_path)
    assert "LOGIN_PROCESS_ENV_OVERRIDES_DOTENV" in diagnostics
    assert "PASSWORD_PROCESS_ENV_OVERRIDES_DOTENV" in diagnostics and "PASSWORD_VARIABLE_EMPTY" in diagnostics

def test_dotenv_wrong_root_diagnosed(tmp_path,monkeypatch):
    monkeypatch.delenv("DATAFORSEO_LOGIN",raising=False); monkeypatch.delenv("DATAFORSEO_PASSWORD",raising=False)
    assert "DOTENV_NOT_LOADED_FROM_REPOSITORY_ROOT" in load_dataforseo_environment(tmp_path)

def test_user_data_response_does_not_return_or_print_login(monkeypatch,capsys):
    payload={"status_code":20000,"tasks":[{"result":[{"login":"secret-api-login","money":{"balance":1.0}}]}]}
    monkeypatch.setenv("DATAFORSEO_LOGIN","secret-api-login"); monkeypatch.setenv("DATAFORSEO_PASSWORD","secret-api-password")
    with patch("amazon_scout.dataforseo_doctor.load_dataforseo_environment",return_value=[]), patch("amazon_scout.sources.dataforseo.urllib.request.urlopen",return_value=FakeHTTPResponse(payload)) as call:
        assert main(["--auth-test"])==0
        assert call.call_args.args[0].full_url.endswith("/v3/appendix/user_data")
    output=capsys.readouterr().out
    assert "AUTH: PASS" in output and "Account balance: 1.0" in output
    assert "secret-api-login" not in output and "secret-api-password" not in output and "Authorization" not in output

def test_auth_test_cannot_call_paid_labs(monkeypatch):
    payload={"status_code":20000,"tasks":[{"result":[{"money":{"balance":1}}]}]}
    monkeypatch.setenv("DATAFORSEO_LOGIN","x"); monkeypatch.setenv("DATAFORSEO_PASSWORD","y")
    with patch("amazon_scout.dataforseo_doctor.load_dataforseo_environment",return_value=[]), patch("amazon_scout.sources.dataforseo.urllib.request.urlopen",return_value=FakeHTTPResponse(payload)) as call:
        main(["--auth-test"])
    assert call.call_count==1 and call.call_args.args[0].full_url=="https://api.dataforseo.com/v3/appendix/user_data"
    assert "dataforseo_labs" not in call.call_args.args[0].full_url

def test_401_auth_redaction(monkeypatch,capsys):
    monkeypatch.setenv("DATAFORSEO_LOGIN","do-not-print-login"); monkeypatch.setenv("DATAFORSEO_PASSWORD","do-not-print-password")
    error=urllib.error.HTTPError("https://api.dataforseo.com/v3/appendix/user_data",401,"Unauthorized",{},None)
    with patch("amazon_scout.dataforseo_doctor.load_dataforseo_environment",return_value=[]), patch("amazon_scout.sources.dataforseo.urllib.request.urlopen",side_effect=error):
        assert main(["--auth-test"])==1
    output=capsys.readouterr().out
    assert "AUTH: FAIL" in output and "HTTP status: 401" in output
    assert "do-not-print" not in output and "Basic" not in output

def test_sandbox_uses_same_auth_construction_with_hostname_only():
    production=DataForSEOSource._authorized_request(PRODUCTION_URL+ENDPOINTS["user_data"],"x","y")
    sandbox=DataForSEOSource._authorized_request(SANDBOX_URL+ENDPOINTS["user_data"],"x","y")
    assert production.get_header("Authorization")==sandbox.get_header("Authorization")
    assert production.full_url.replace(PRODUCTION_URL,SANDBOX_URL)==sandbox.full_url

def test_sandbox_401_reports_authentication_failed(monkeypatch,capsys):
    monkeypatch.setenv("DATAFORSEO_LOGIN","x"); monkeypatch.setenv("DATAFORSEO_PASSWORD","y"); monkeypatch.setenv("DATAFORSEO_MODE","sandbox")
    with patch("amazon_scout.dataforseo_doctor.load_dataforseo_environment",return_value=[]), patch.object(DataForSEOSource,"request",side_effect=RuntimeError("DataForSEO request failed with HTTP 401; credentials and Authorization were redacted")):
        assert main(["--sandbox-test"])==1
    output=capsys.readouterr().out
    assert "AUTHENTICATION_FAILED" in output and "--auth-test first" in output
    assert "Basic" not in output and "x:y" not in output

def test_free_labs_status_request_and_zero_paid_calls(monkeypatch,capsys):
    payload={"status_code":20000,"status_message":"Ok.","cost":0,"tasks":[{"status_code":20000,"result":[{"amazon":{"date_update":"2026-08-01"}}]}]}
    monkeypatch.setenv("DATAFORSEO_LOGIN","x"); monkeypatch.setenv("DATAFORSEO_PASSWORD","y")
    with patch("amazon_scout.dataforseo_doctor.load_dataforseo_environment",return_value=[]), patch("amazon_scout.sources.dataforseo.urllib.request.urlopen",return_value=FakeHTTPResponse(payload)) as call:
        assert main(["--labs-status-test"])==0
    request=call.call_args.args[0]; output=capsys.readouterr().out
    assert request.full_url==PRODUCTION_URL+ENDPOINTS["labs_status"] and request.method=="GET" and request.data is None
    assert "Amazon Labs status exists: YES" in output and "2026-08-01" in output and "Paid calls performed: 0" in output

def test_free_locations_request_reports_generic_sources_without_fabrication(monkeypatch,capsys):
    uae={"location_code":2784,"location_name":"United Arab Emirates","available_languages":[{"language_name":"Arabic","language_code":"ar","available_sources":["google"]},{"language_name":"English","language_code":"en","available_sources":["google"]}]}
    payload={"status_code":20000,"status_message":"Ok.","cost":0,"tasks":[{"status_code":20000,"result":[uae]}]}
    monkeypatch.setenv("DATAFORSEO_LOGIN","x"); monkeypatch.setenv("DATAFORSEO_PASSWORD","y")
    with patch("amazon_scout.dataforseo_doctor.load_dataforseo_environment",return_value=[]), patch("amazon_scout.sources.dataforseo.urllib.request.urlopen",return_value=FakeHTTPResponse(payload)) as call:
        assert main(["--locations-test"])==0
    output=capsys.readouterr().out; request=call.call_args.args[0]
    assert request.full_url==PRODUCTION_URL+ENDPOINTS["locations"] and request.method=="GET"
    assert "Location code 2784 exists: YES" in output and "Arabic (ar) — google" in output and "English (en) — google" in output
    assert "amazon" not in output.lower() and "Paid calls performed: 0" in output

def test_bulk_search_volume_wire_body_is_exact_one_element_array():
    settings=DataForSEOSettings(DataForSEOMode.SANDBOX,False,.25,10,"api-login","api-password"); source=DataForSEOSource(settings); budget=DataForSEOBudget.from_settings(settings)
    task={"keywords":["حقيبة سفر"],"location_code":2784,"language_code":"ar"}
    payload={"status_code":20000,"status_message":"Ok.","cost":0,"tasks":[]}
    with patch("amazon_scout.sources.dataforseo.urllib.request.urlopen",return_value=FakeHTTPResponse(payload)) as call: source.request(ENDPOINTS["bulk_search_volume"],task,budget)
    request=call.call_args.args[0]
    assert json.loads(request.data.decode())==[task]
    assert request.get_header("Content-type")=="application/json"
    assert request.header_items().count(("Authorization",request.get_header("Authorization")))==1
    assert base64.b64decode(request.get_header("Authorization").split()[1]).decode()=="api-login:api-password"
    assert request.get_header("User-agent")=="amazon-uae-product-scout/1.4A"

def test_production_probe_uses_arabic_keyword_ar_and_uae_location(monkeypatch):
    monkeypatch.setenv("DATAFORSEO_LOGIN","x"); monkeypatch.setenv("DATAFORSEO_PASSWORD","y"); monkeypatch.setenv("DATAFORSEO_ALLOW_PAID","true"); monkeypatch.setenv("DATAFORSEO_MAX_TASKS_PER_RUN","1"); monkeypatch.setenv("DATAFORSEO_MAX_COST_USD_PER_RUN","0.25")
    payload={"status_code":20000,"status_message":"Ok.","cost":0,"tasks":[]}
    with patch("amazon_scout.dataforseo_doctor.load_dataforseo_environment",return_value=[]), patch.object(DataForSEOSource,"request",return_value=(payload,False)) as request:
        assert main(["--production-test"])==0
    task=request.call_args.args[1]
    assert task=={"keywords":["حقيبة سفر"],"location_code":2784,"language_code":"ar"}

def test_sandbox_arabic_probe_uses_same_arabic_keyword_and_uae_location():
    assert _bulk_probe_task("ar")=={"keywords":["حقيبة سفر"],"location_code":2784,"language_code":"ar"}

def test_safe_403_body_parsing_and_redaction():
    secret_login="never-print-login"; secret_password="never-print-password"; token=base64.b64encode(f"{secret_login}:{secret_password}".encode()).decode()
    body={"status_code":40501,"status_message":f"Denied for {secret_login}; Authorization: Basic {token}","login":secret_login,"password":secret_password}
    headers={"Content-Type":"application/json","Server":"cloudflare"}
    error=urllib.error.HTTPError("https://api.dataforseo.com/x",403,"Forbidden",headers,io.BytesIO(json.dumps(body).encode()))
    details=safe_http_error(error); serialized=json.dumps(details)
    assert details["http_status"]==403 and details["provider_status_code"]==40501 and details["content_type"]=="application/json" and details["server"]=="cloudflare"
    assert secret_login not in serialized and secret_password not in serialized and token not in serialized

def test_40104_maps_to_account_verification_required(monkeypatch,capsys):
    body={"status_code":40104,"status_message":"Account verification is required"}; error=urllib.error.HTTPError(PRODUCTION_URL+ENDPOINTS["labs_status"],403,"Forbidden",{"Content-Type":"application/json"},io.BytesIO(json.dumps(body).encode()))
    monkeypatch.setenv("DATAFORSEO_LOGIN","x"); monkeypatch.setenv("DATAFORSEO_PASSWORD","y")
    with patch("amazon_scout.dataforseo_doctor.load_dataforseo_environment",return_value=[]), patch("amazon_scout.sources.dataforseo.urllib.request.urlopen",side_effect=error): assert main(["--labs-status-test"])==1
    output=capsys.readouterr().out
    assert "ACCOUNT_VERIFICATION_REQUIRED" in output and "DataForSEO status_code: 40104" in output and "Paid calls performed: 0" in output

def test_free_diagnostics_reject_non_allowlisted_endpoint():
    source=DataForSEOSource(DataForSEOSettings(login="x",password="y"))
    with pytest.raises(PermissionError): source.free_get(ENDPOINTS["bulk_search_volume"])

def test_recent_errors_is_free_post_and_never_uses_paid_budget(monkeypatch,capsys):
    error_row={"datetime":"2026-08-14 10:00:00 +00:00","function":"dataforseo_labs/amazon/bulk_search_volume/live","error_code":40501,"error_message":"Invalid field","http_code":200,"http_url":"/v3/dataforseo_labs/amazon/bulk_search_volume/live"}
    payload={"status_code":20000,"status_message":"Ok.","cost":0,"tasks":[{"status_code":20000,"cost":0,"result":[error_row]}]}
    monkeypatch.setenv("DATAFORSEO_LOGIN","x"); monkeypatch.setenv("DATAFORSEO_PASSWORD","y")
    with patch("amazon_scout.dataforseo_doctor.load_dataforseo_environment",return_value=[]), patch("amazon_scout.sources.dataforseo.urllib.request.urlopen",return_value=FakeHTTPResponse(payload)) as call:
        assert main(["--recent-errors"])==0
    request=call.call_args.args[0]; output=capsys.readouterr().out
    assert request.full_url==PRODUCTION_URL+ENDPOINTS["recent_errors"] and request.method=="POST"
    assert json.loads(request.data.decode())==[{"limit":10}]
    assert "error_code: 40501" in output and "Invalid field" in output and "Paid Labs calls performed: 0" in output
    assert "bulk_search_volume/live" in output

def test_recent_errors_output_redacts_credentials(monkeypatch,capsys):
    login="secret-login"; password="secret-password"; token=base64.b64encode(f"{login}:{password}".encode()).decode()
    error_row={"datetime":"now","function":"amazon/bulk_search_volume/live","error_code":40103,"error_message":f"{login} Authorization: Basic {token} {password}","http_code":200,"http_url":"/amazon/bulk_search_volume/live","login":login,"password":password}
    payload={"status_code":20000,"status_message":"Ok.","tasks":[{"status_code":20000,"result":[error_row]}]}
    monkeypatch.setenv("DATAFORSEO_LOGIN",login); monkeypatch.setenv("DATAFORSEO_PASSWORD",password)
    with patch("amazon_scout.dataforseo_doctor.load_dataforseo_environment",return_value=[]), patch("amazon_scout.sources.dataforseo.urllib.request.urlopen",return_value=FakeHTTPResponse(payload)): main(["--recent-errors"])
    output=capsys.readouterr().out
    assert login not in output and password not in output and token not in output and "Authorization: [REDACTED]" in output

def test_nested_task_status_and_provider_cost_are_surfaced():
    payload={"status_code":20000,"status_message":"Ok.","cost":.0123,"tasks_error":1,"tasks":[{"status_code":40103,"status_message":"Task execution failed","cost":.0123,"result":None}]}
    settings=DataForSEOSettings(DataForSEOMode.SANDBOX,False,.25,10,"api-user","api-password"); budget=DataForSEOBudget.from_settings(settings)
    with patch("amazon_scout.sources.dataforseo.urllib.request.urlopen",return_value=FakeHTTPResponse(payload)), pytest.raises(DataForSEOProviderError) as caught:
        DataForSEOSource(settings).request(ENDPOINTS["bulk_search_volume"],{"keywords":["x"],"location_code":2784,"language_code":"ar"},budget)
    message=str(caught.value)
    assert "status_code: 40103" in message and "TASK_EXECUTION_FAILED" in message and "Task execution failed" in message
    assert "Provider reported cost: 0.0123" in message and budget.provider_reported_cost==.0123

@pytest.mark.parametrize("code,name",[
    (20000,"OK"),(40102,"NO_SEARCH_RESULTS"),(40103,"TASK_EXECUTION_FAILED"),(40210,"INSUFFICIENT_FUNDS"),
    (40501,"INVALID_FIELD"),(40502,"EMPTY_POST_DATA"),(40503,"INVALID_POST_DATA"),(40505,"OUTDATED_LOCATION_DATA"),
    (40506,"UNKNOWN_FIELDS"),(50303,"UPDATE_IN_PROGRESS"),(50304,"FUNCTION_UNAVAILABLE"),
])
def test_official_provider_status_code_mapping(code,name):
    assert PROVIDER_STATUS_NAMES[code]==name
