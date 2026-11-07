import assert from "node:assert/strict";
import test from "node:test";
import { bookingPresentation, campaignStatusMessage, guestSettlementPresentation } from "../src/guest/model.ts";

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
