"""Payments v2 contracts against MockTransport only."""

import asyncio
import json

import httpx
import pytest

from tipping_point.paypal.client import (
    PayPalGateway, PayPalOutcomeUnknownError, PayPalResponseError,
    build_capture_payload, build_refund_payload, parse_capture, parse_refund,
)


@pytest.mark.parametrize("status",["COMPLETED","PENDING","DECLINED"])
def test_capture_exact_payload_request_id_and_resource_state(status):
    requests=[]
    def transport(request):
        if request.url.path=="/v1/oauth2/token":
            return httpx.Response(200,json={"access_token":"offline","expires_in":3600})
        requests.append(request)
        return httpx.Response(201,json={"id":"CAPTURE","status":status,"amount":{"currency_code":"GBP","value":"10.00"},
            "supplementary_data":{"related_ids":{"authorization_id":"AUTH","order_id":"ORDER"}},
            "seller_receivable_breakdown":{"paypal_fee":{"currency_code":"GBP","value":"0.59"}}})
    async def run():
        async with PayPalGateway(client_id="offline",client_secret="offline",transport=httpx.MockTransport(transport)) as gateway:
            result=await gateway.capture_authorization("AUTH",amount_minor=1000,currency="GBP",operation_id="capture-uuid")
            assert result.status==status and result.amount_minor==1000 and result.fee_minor==59
            assert result.authorization_id=="AUTH" and result.order_id=="ORDER"
    asyncio.run(run())
    assert len(requests)==1
    assert requests[0].url.path=="/v2/payments/authorizations/AUTH/capture"
    assert requests[0].headers["PayPal-Request-Id"]=="capture-uuid"
    assert requests[0].headers["Prefer"]=="return=representation"
    assert json.loads(requests[0].content)==build_capture_payload(1000,"GBP")=={
        "amount":{"currency_code":"GBP","value":"10.00"},"final_capture":True}


@pytest.mark.parametrize("status",["COMPLETED","PENDING","FAILED"])
def test_refund_preserves_capture_linkage_and_pending_status(status):
    calls=[]
    def transport(request):
        if request.url.path=="/v1/oauth2/token":
            return httpx.Response(200,json={"access_token":"offline","expires_in":3600})
        calls.append(request)
        return httpx.Response(201,json={"id":"REFUND","status":status,"amount":{"currency_code":"GBP","value":"10.00"},
            "links":[{"rel":"up","href":"https://api-m.sandbox.paypal.com/v2/payments/captures/CAPTURE"}]})
    async def run():
        async with PayPalGateway(client_id="offline",client_secret="offline",transport=httpx.MockTransport(transport)) as gateway:
            result=await gateway.refund_capture("CAPTURE",amount_minor=1000,currency="GBP",operation_id="refund-uuid")
            assert result.capture_id=="CAPTURE" and result.status==status and result.amount_minor==1000
    asyncio.run(run())
    assert calls[0].url.path=="/v2/payments/captures/CAPTURE/refund"
    assert calls[0].headers["PayPal-Request-Id"]=="refund-uuid"
    assert json.loads(calls[0].content)==build_refund_payload(1000,"GBP")


@pytest.mark.parametrize("kind",["capture","refund"])
@pytest.mark.parametrize("failure",["timeout","server","malformed","known_id_malformed_money"])
def test_uncertain_mutations_are_unknown_and_never_automatically_retried(kind,failure):
    mutations=[]
    def transport(request):
        if request.url.path=="/v1/oauth2/token":
            return httpx.Response(200,json={"access_token":"offline","expires_in":3600})
        mutations.append(request)
        if failure=="timeout": raise httpx.ReadTimeout("offline",request=request)
        if failure=="server":return httpx.Response(503)
        if failure=="malformed":return httpx.Response(201,text="not JSON")
        return httpx.Response(201,json={"id":"RESOURCE","status":"COMPLETED","amount":{"currency_code":"GBP","value":"bad"}})
    async def run():
        async with PayPalGateway(client_id="offline",client_secret="offline",transport=httpx.MockTransport(transport)) as gateway:
            method=gateway.capture_authorization if kind=="capture" else gateway.refund_capture
            with pytest.raises(PayPalOutcomeUnknownError) as error:
                await method("EXISTING",amount_minor=1000,currency="GBP",operation_id="stable-original-uuid")
            assert error.value.operation_id=="stable-original-uuid"
            if failure=="known_id_malformed_money":assert error.value.resource_id=="RESOURCE"
    asyncio.run(run())
    assert len(mutations)==1


@pytest.mark.parametrize("kind",["capture","refund"])
def test_retrieval_requires_the_requested_resource_identity(kind):
    def transport(request):
        if request.url.path=="/v1/oauth2/token":
            return httpx.Response(200,json={"access_token":"offline","expires_in":3600})
        assert request.method=="GET"
        return httpx.Response(200,json={"id":"FOREIGN","status":"COMPLETED"})
    async def run():
        async with PayPalGateway(client_id="offline",client_secret="offline",transport=httpx.MockTransport(transport)) as gateway:
            with pytest.raises(PayPalResponseError):
                await (gateway.get_capture("EXPECTED") if kind=="capture" else gateway.get_refund("EXPECTED"))
    asyncio.run(run())


def test_untrusted_or_conflicting_resource_links_are_not_association_proof():
    assert parse_refund({"id":"R","links":[{"rel":"up","href":"https://evil.invalid/v2/payments/captures/C"}]}).capture_id is None
    assert parse_refund({"id":"R","links":[{"rel":"up","href":"https://api-m.paypal.com/v2/payments/captures/C"}]}).capture_id is None
    with pytest.raises(PayPalResponseError):
        parse_refund({"id":"R","supplementary_data":{"related_ids":{"capture_id":"A"}},
                      "links":[{"rel":"up","href":"https://api-m.sandbox.paypal.com/v2/payments/captures/B"}]})
    assert parse_capture({"id":"C"}).amount_minor is None


@pytest.mark.parametrize("value",[0,-1,True,1.5])
def test_invalid_financial_amounts_are_rejected_before_network(value):
    with pytest.raises(ValueError):build_capture_payload(value,"GBP")
    with pytest.raises(ValueError):build_refund_payload(value,"GBP")
