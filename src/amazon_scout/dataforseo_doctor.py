from __future__ import annotations
import argparse, os, tempfile
from .sources.dataforseo import (ENDPOINTS, PRODUCTION_URL, SANDBOX_URL, DataForSEOBudget, DataForSEOCache, DataForSEOMode, DataForSEOSettings, DataForSEOSource, EvidenceEnvironment, load_dataforseo_environment, parse_bulk_search_volume, parse_labs_status, parse_locations, parse_product_competitors, parse_ranked_keywords, parse_recent_errors, parse_uae_location_diagnostic, redact)

def _print_config(s):
    print(f"DataForSEO credentials: {'PRESENT' if s.login and s.password else 'MISSING'}"); print(f"Mode: {s.mode.value}")
    print(f"Sandbox endpoint: {SANDBOX_URL}"); print(f"Production endpoint: {PRODUCTION_URL}")
    print(f"Paid production calls: {'ENABLED' if s.allow_paid else 'DISABLED'}"); print(f"Max tasks/run: {s.max_tasks_per_run}")
    print(f"Max cost/run: USD {s.max_cost_usd_per_run:.2f} (local application limit; not account balance)")

def _print_support(support):
    print("Amazon UAE provider support:"); print(f"  location name: {support['location_name']}"); print(f"  location code: {support['location_code']}")
    languages=support.get("supported_languages") or []
    print("  supported language(s): "+(", ".join(f"{x.get('language_name')} ({x.get('language_code')})" for x in languages) or "NONE CONFIRMED"))
    print(f"  support status: {support['provider_support_status']}")
    if not any(x.get("language_code")=="en" for x in languages): print("  English Amazon UAE search-volume support: UNAVAILABLE / NOT CONFIRMED")

def _bulk_probe_task(language):
    return {"keywords":["حقيبة سفر" if language=="ar" else "airplane foot hammock"],"location_code":2784,"language_code":language}

def _sandbox_test(settings):
    sandbox=DataForSEOSettings(DataForSEOMode.SANDBOX,False,settings.max_cost_usd_per_run,settings.max_tasks_per_run,settings.login,settings.password); source=DataForSEOSource(sandbox); budget=DataForSEOBudget.from_settings(sandbox)
    with tempfile.TemporaryDirectory(prefix="dataforseo-doctor-") as directory:
        cache=DataForSEOCache(directory); locations,_=source.request(ENDPOINTS["locations"],None,budget,cache,method="GET"); support=parse_locations(locations); _print_support(support)
        language=(support.get("supported_languages") or [{"language_code":"ar"}])[0]["language_code"]
        requests=[("bulk_search_volume",_bulk_probe_task(language),parse_bulk_search_volume),("ranked_keywords",{"asin":"B000000000","location_code":2784,"language_code":language,"limit":1},parse_ranked_keywords),("product_competitors",{"asin":"B000000000","location_code":2784,"language_code":language,"limit":1},parse_product_competitors)]
        for name,task,parser in requests:
            payload,_=source.request(ENDPOINTS[name],task,budget,cache); parser(payload,EvidenceEnvironment.SANDBOX_DUMMY); cached,hit=source.request(ENDPOINTS[name],task,budget,cache); assert hit and cached==payload; print(f"{name}: PASS (sandbox dummy; not market evidence)")
        assert "Basic secret" not in str(redact({"Authorization":"Basic secret"})); print("authentication/parsers/normalization/cache/cost/redaction: PASS")
        print(f"Sandbox provider calls performed: {budget.tasks_attempted}"); print(f"Provider-reported sandbox cost: USD {budget.provider_reported_cost:.8f}")
    return 0

def _production_test(settings):
    if not settings.allow_paid: print("REFUSED: set DATAFORSEO_ALLOW_PAID=true for the explicit one-call production test."); return 2
    production=DataForSEOSettings(DataForSEOMode.PRODUCTION,True,settings.max_cost_usd_per_run,settings.max_tasks_per_run,settings.login,settings.password)
    if production.max_tasks_per_run<1 or production.max_cost_usd_per_run<=0: print("REFUSED: local production budget does not permit one task."); return 2
    budget=DataForSEOBudget.from_settings(production); payload,_=DataForSEOSource(production).request(ENDPOINTS["bulk_search_volume"],_bulk_probe_task("ar"),budget,None,estimated_cost=.01); parse_bulk_search_volume(payload,EvidenceEnvironment.PRODUCTION)
    print("Production minimal request: PASS"); print(f"Provider-reported cost: USD {budget.provider_reported_cost:.8f}"); print("Production calls performed: 1"); return 0

def _auth_test(diagnostics):
    blocking=[item for item in diagnostics if any(marker in item for marker in ("MISSING","EMPTY","WHITESPACE","QUOTES","NOT_LOADED","OVERRIDES"))]
    if blocking:
        print("AUTH: FAIL"); print("HTTP status: NOT_SENT"); print("DataForSEO API status code: CONFIGURATION_ERROR:"+",".join(blocking)); print("Account balance: UNAVAILABLE"); return 2
    settings=DataForSEOSettings(login=os.getenv("DATAFORSEO_LOGIN"),password=os.getenv("DATAFORSEO_PASSWORD"))
    result=DataForSEOSource(settings).user_data()
    print(f"AUTH: {result['auth']}"); print(f"HTTP status: {result['http_status'] if result['http_status'] is not None else 'UNAVAILABLE'}")
    print(f"DataForSEO API status code: {result['api_status_code'] if result['api_status_code'] is not None else 'UNAVAILABLE'}")
    print(f"Account balance: {result['account_balance'] if result['account_balance'] is not None else 'UNAVAILABLE'}")
    return 0 if result["auth"]=="PASS" else 1

def _configuration_blockers(diagnostics):
    return [item for item in diagnostics if any(marker in item for marker in ("MISSING","EMPTY","WHITESPACE","QUOTES","NOT_LOADED","OVERRIDES"))]

def _free_labs_test(endpoint,diagnostics):
    blockers=_configuration_blockers(diagnostics)
    if blockers:
        result={"http_status":"NOT_SENT","status_code":"CONFIGURATION_ERROR","status_message":",".join(blockers),"payload":{},"classification":"CONFIGURATION_ERROR","content_type":None,"server":None}
    else:
        settings=DataForSEOSettings(login=os.getenv("DATAFORSEO_LOGIN"),password=os.getenv("DATAFORSEO_PASSWORD")); result=DataForSEOSource(settings).free_get(endpoint)
    print(f"HTTP status: {result['http_status'] if result['http_status'] is not None else 'UNAVAILABLE'}")
    print(f"DataForSEO status_code: {result['status_code'] if result['status_code'] is not None else 'UNAVAILABLE'}")
    print(f"DataForSEO status_message: {result['status_message'] if result['status_message'] is not None else 'UNAVAILABLE'}")
    if result.get("classification")=="ACCOUNT_VERIFICATION_REQUIRED": print("ACCOUNT_VERIFICATION_REQUIRED")
    if endpoint==ENDPOINTS["labs_status"]:
        parsed=parse_labs_status(result["payload"]); print(f"Amazon Labs status exists: {'YES' if parsed['amazon_labs_status_exists'] else 'NO'}"); print(f"Amazon Labs last-update date: {parsed['amazon_last_update'] or 'UNAVAILABLE'}")
    else:
        parsed=parse_uae_location_diagnostic(result["payload"]); print(f"Location code 2784 exists: {'YES' if parsed['uae_location_exists'] else 'NO'}")
        if parsed["languages"]:
            for language in parsed["languages"]: print(f"UAE language/source: {language['language_name']} ({language['language_code']}) — {', '.join(language['available_sources']) or 'NO SOURCES REPORTED'}")
        else: print("UAE languages/sources: NONE REPORTED")
    if result.get("content_type"): print(f"Response content-type: {result['content_type']}")
    if result.get("server"): print(f"Server: {result['server']}")
    print("Paid calls performed: 0")
    return 0 if result.get("http_status")==200 and result.get("status_code")==20000 else 1

def _recent_errors(diagnostics):
    blockers=_configuration_blockers(diagnostics)
    if blockers:
        print("DataForSEO status_code: CONFIGURATION_ERROR"); print("Paid Labs calls performed: 0"); return 2
    settings=DataForSEOSettings(login=os.getenv("DATAFORSEO_LOGIN"),password=os.getenv("DATAFORSEO_PASSWORD")); result=DataForSEOSource(settings).free_post(ENDPOINTS["recent_errors"],{"limit":10})
    rows=parse_recent_errors(result.get("payload") or {})
    preferred=[row for row in rows if "bulk_search_volume" in f"{row.get('function') or ''} {row.get('endpoint') or ''}".lower() and "amazon" in f"{row.get('function') or ''} {row.get('endpoint') or ''}".lower()]
    selected=preferred or rows
    print(f"HTTP status: {result.get('http_status') if result.get('http_status') is not None else 'UNAVAILABLE'}")
    print(f"DataForSEO status_code: {result.get('status_code') if result.get('status_code') is not None else 'UNAVAILABLE'}")
    print(f"DataForSEO status_message: {result.get('status_message') or 'UNAVAILABLE'}")
    if not selected: print("Recent errors: NONE RETURNED")
    for row in selected:
        print(f"datetime: {row.get('datetime') or 'UNAVAILABLE'}")
        print(f"function: {row.get('function') or 'UNAVAILABLE'}")
        print(f"error_code: {row.get('error_code') if row.get('error_code') is not None else 'UNAVAILABLE'}")
        print(f"error_message: {row.get('error_message') or 'UNAVAILABLE'}")
        print(f"HTTP code: {row.get('http_code') if row.get('http_code') is not None else 'UNAVAILABLE'}")
        print(f"endpoint/path: {row.get('endpoint') or 'UNAVAILABLE'}")
    print("Paid Labs calls performed: 0")
    return 0 if result.get("http_status")==200 and result.get("status_code")==20000 else 1

def main(argv=None):
    parser=argparse.ArgumentParser(); group=parser.add_mutually_exclusive_group(); group.add_argument("--auth-test",action="store_true"); group.add_argument("--labs-status-test",action="store_true"); group.add_argument("--locations-test",action="store_true"); group.add_argument("--recent-errors",action="store_true"); group.add_argument("--sandbox-test",action="store_true"); group.add_argument("--production-test",action="store_true"); args=parser.parse_args(argv); diagnostics=load_dataforseo_environment()
    if args.auth_test: return _auth_test(diagnostics)
    if args.labs_status_test: return _free_labs_test(ENDPOINTS["labs_status"],diagnostics)
    if args.locations_test: return _free_labs_test(ENDPOINTS["locations"],diagnostics)
    if args.recent_errors: return _recent_errors(diagnostics)
    settings=DataForSEOSettings.from_environment(load_dotenv=False); _print_config(settings)
    if not settings.login or not settings.password:
        if args.sandbox_test or args.production_test: print("Test blocked: credentials are missing."); return 2
    if args.sandbox_test:
        try: return _sandbox_test(settings)
        except RuntimeError as exc:
            if "HTTP 401" in str(exc): print("Sandbox test: AUTHENTICATION_FAILED (HTTP 401). Run ./scripts/dataforseo-doctor --auth-test first.")
            elif getattr(exc,"details",{}).get("classification")=="ACCOUNT_VERIFICATION_REQUIRED": print("Sandbox test: ACCOUNT_VERIFICATION_REQUIRED")
            else: print(f"Sandbox test: FAIL — {exc}")
            print("Sandbox calls attempted: 1; production calls performed: 0")
            print("No sandbox values were persisted or treated as market evidence.")
            return 1
    if args.production_test: return _production_test(settings)
    _print_support({"location_name":"United Arab Emirates","location_code":2784,"supported_languages":[],"provider_support_status":"NOT_QUERIED_ZERO_CALL_DEFAULT"}); print("Provider calls performed: 0"); return 0
if __name__=="__main__": raise SystemExit(main())
