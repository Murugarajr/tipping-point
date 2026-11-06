# APIMatic PayPal Context Plugin — availability blocker

Review date: 2026-11-06. Environment: macOS, VS Code coding-agent session.
**No plugin invocation occurred. Do not claim APIMatic-informed implementation.**

Official setup source fetched:
https://context.apimatic.io/plugins/paypal/

The page advertises version 0.4.1, Node.js 18+, and
`npx context-plugins install paypal` for detected Claude Code, Cursor, VS Code
and Codex environments. This is the published setup command, **not an executed
installation** or evidence that this particular coding agent is configured.
Official source/installer links found through search:
https://github.com/apimatic/context-plugins-installer
https://github.com/apimatic/plugin-marketplace

Observed local checks before execution reliability failed:

- VS Code extension listing filtered for PayPal/APIMatic/Cline/context showed
  `rooveterinaryinc.roo-cline@3.54.0`, no PayPal/APIMatic extension.
- No matching PayPal/APIMatic extension directory or tracked project MCP/APIMatic
  configuration was found in the limited checks.
- This session exposes no APIMatic PayPal context tool. This does not prove that
  every user-level MCP/skill configuration is absent; those were not inspected.

Installed plugin version: unknown. Configuration scope: unverified. No guessed
IDE settings path, plugin installation, account change or credential disclosure
was performed. Shell execution became unreliable and was stopped.

Sanitized context requests/results: **none**. Contract findings in
`docs/channel3-paypal-closure-status.md` come from official PayPal REST references,
not from APIMatic. The recovered standalone adapter and its mocked offline tests
are `packages/tipping_point/paypal/client.py` and `tests/unit/test_paypal.py`;
their existence is not evidence of APIMatic use.

Next: human verifies official setup for the actual coding assistant and approval
for any installation/configuration change. Once genuinely available, use only
sanitized create AUTHORIZE / authorize / amount-currency / request-id / void
contract questions, record actual tool/version/scope/date and findings, and map
those findings to implemented code/tests. Never supply client secrets, tokens,
customer payloads or arbitrary HTTP headers to the plugin.
