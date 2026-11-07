import assert from "node:assert/strict";
import test from "node:test";
import { bookingPresentation, campaignStatusMessage, guestSettlementPresentation } from "../src/guest/model.ts";
import { settlementHeadline } from "../src/host/model.ts";

test("only a fully collected, explicitly confirmed own booking displays workshop confirmation",()=>{
  const booking={state:"PAID",amount_minor:1000,captured_minor:1000,refunded_minor:0,campaign_status:"CONFIRMED",workshop_confirmed:true};
  assert.equal(guestSettlementPresentation(booking)[0],"Workshop confirmed");
  for(const change of [
    {state:"AUTHORIZED"},{state:"CAPTURE_PENDING"},{workshop_confirmed:false},
    {campaign_status:"SETTLING"},{captured_minor:0},{refunded_minor:1000},
  ])assert.notEqual(guestSettlementPresentation({...booking,...change})[0],"Workshop confirmed");
  assert.notEqual(guestSettlementPresentation({state:"PAID"})[0],"Workshop confirmed");
});

test("pending capture is not collection and refunds do not promise immediate completion",()=>{
  assert.match(bookingPresentation("CAPTURE_PENDING")[1],/No completed collection/);
  assert.match(bookingPresentation("REFUND_PENDING")[1],/not yet guaranteed/);
  assert.equal(bookingPresentation("REFUNDED")[0],"Payment refunded");
  assert.match(campaignStatusMessage("COMPENSATING"),/processing/);
  assert.match(campaignStatusMessage("CANCELLED"),/release or refund status.*separately/);
  assert.equal(campaignStatusMessage("OPEN"),null);
});

test("sandbox test cleanup never presents confirmation or completed cleanup prematurely",()=>{
  const booking={state:"REFUND_PENDING",amount_minor:100,captured_minor:100,refunded_minor:0,campaign_status:"COMPENSATING",workshop_confirmed:false,sandbox_cleanup_status:"REFUND_PROCESSING"};
  assert.notEqual(guestSettlementPresentation(booking)[0],"Workshop confirmed");
  assert.notEqual(guestSettlementPresentation({...booking,state:"PAID",campaign_status:"CONFIRMED"})[0],"Workshop confirmed");
  assert.match(campaignStatusMessage("COMPENSATING","REFUND_PROCESSING"),/Test campaign cancelled; refund processing/);
  assert.match(campaignStatusMessage("COMPENSATING","REVIEW_REQUIRED"),/operator review.*No completed refund/);
  assert.match(campaignStatusMessage("COMPENSATING","REFUNDED"),/refund processing/);
  assert.match(campaignStatusMessage("CANCELLED","REFUNDED"),/full Sandbox refund.*verified/);
  const host={state:"COMPENSATING",review_required:false,sandbox_cleanup:{status:"REFUND_PROCESSING",reason:"x",requested_at:null,previously_confirmed:true,review_reason:null}};
  assert.equal(settlementHeadline(host),"Test campaign cancelled; refund processing");
  assert.equal(settlementHeadline({...host,sandbox_cleanup:{...host.sandbox_cleanup,status:"REFUNDED"}}),"Test campaign cancelled; refund processing");
  assert.equal(settlementHeadline({...host,state:"CANCELLED",sandbox_cleanup:{...host.sandbox_cleanup,status:"REFUNDED"}}),"Test campaign cancelled; full Sandbox refund verified");
  assert.equal(settlementHeadline({...host,sandbox_cleanup:{...host.sandbox_cleanup,status:"REVIEW_REQUIRED"}}),"Test campaign cancelled; refund requires operator review");
  assert.equal(settlementHeadline({state:"CONFIRMED",sandbox_cleanup:null}),"Workshop financially confirmed");
  assert.equal(settlementHeadline({state:"CANCELLED"}),"Campaign cancelled after cleanup");
});
