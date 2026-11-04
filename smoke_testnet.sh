#!/usr/bin/env bash
# Live smoke test of the deployed IntentGuard contract on NEAR testnet. No mainnet, no real funds.
# Re-runnable: SETUP=1 (default) re-registers bot1, which resets its 24h window.
# Prints only public data (tx hashes, results, errors). Keys are read from ~/.near-credentials.
set -uo pipefail
export PATH="$HOME/.cargo/bin:$PATH"
OWNER=${OWNER:-intentguard-5821c5.testnet}
C=${CONTRACT:-guard.$OWNER}
AGENT_KEY_FILE=${AGENT_KEY_FILE:-$HOME/.near-credentials/testnet/agent-keys/bot1.json}
AGENT_PK=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['public_key'])" "$AGENT_KEY_FILE")
NET="network-config testnet"
strip() { sed 's/\x1b\[[0-9;]*m//g'; }
summ() { strip | grep -E "Transaction ID|ERR_[A-Z_]+|MethodNameMismatch|Smart contract panicked|\"agent\"|remaining_daily|\"settlement_id\"|Function execution return value|^\s*(true|false|null|\"|\{)" | grep -viE "private|seed" | head -12; }
view() { echo "--- view $1 $2"; near contract call-function as-read-only $C "$1" json-args "$2" $NET now 2>&1 | strip | sed -n '/return value/,$p' | grep -v "console command" | head -20; }
call_owner() { echo "--- owner($OWNER) $1 $2"; near contract call-function as-transaction $C "$1" json-args "$2" prepaid-gas '50 Tgas' attached-deposit '0 NEAR' sign-as $OWNER $NET sign-with-legacy-keychain send 2>&1 | summ; }
call_agent() { echo "--- agent-key settle $1 (expect $2)"; near contract call-function as-transaction $C settle json-args "$1" prepaid-gas '30 Tgas' attached-deposit '0 NEAR' sign-as $C $NET sign-with-access-key-file "$AGENT_KEY_FILE" send 2>&1 | summ; }
call_agent_m() { echo "--- agent-key $1 $2 (expect protocol reject: key limited to settle)"; near contract call-function as-transaction $C "$1" json-args "$2" prepaid-gas '30 Tgas' attached-deposit '0 NEAR' sign-as $C $NET sign-with-access-key-file "$AGENT_KEY_FILE" send 2>&1 | strip | grep -E "Transaction ID|MethodNameMismatch|method|Error|ERR_" | grep -viE "private|seed" | head -5; }
call_fullkey() { echo "--- contract FULL-ACCESS key settle $1 (expect ERR_KEY_NOT_BOUND)"; near contract call-function as-transaction $C settle json-args "$1" prepaid-gas '30 Tgas' attached-deposit '0 NEAR' sign-as $C $NET sign-with-legacy-keychain send 2>&1 | summ; }
S() { echo "{\"amount\":\"$1\",\"token_in\":\"usdc.near\",\"token_out\":\"wrap.near\",\"intent_hash\":\"$2\"}"; }

view get_owner '{}'; view is_killed '{}'
if [ "${SETUP:-1}" = 1 ]; then
  call_owner register_agent '{"agent":"bot1","per_tx_cap":"100000000","daily_cap":"250000000"}'
  BOUND=$(near contract call-function as-read-only $C agent_for_key json-args "{\"public_key\":\"$AGENT_PK\"}" $NET now 2>/dev/null | tr -d '"[:space:]')
  [ "$BOUND" = bot1 ] && echo "--- agent key already bound to bot1, skipping add_agent_key" || call_owner add_agent_key "{\"agent\":\"bot1\",\"public_key\":\"$AGENT_PK\",\"allowance_yocto\":\"250000000000000000000000\"}"
fi
view agent_for_key "{\"public_key\":\"$AGENT_PK\"}"
echo "--- non-owner (contract full key) register_agent (expect ERR_NOT_OWNER)"
near contract call-function as-transaction $C register_agent json-args '{"agent":"evil","per_tx_cap":"1","daily_cap":"1"}' prepaid-gas '30 Tgas' attached-deposit '0 NEAR' sign-as $C $NET sign-with-legacy-keychain send 2>&1 | summ
call_agent "$(S 50000000 smoke-1)" "OK, remaining 200000000"
call_agent "$(S 150000000 smoke-2)" "ERR_OVER_PER_TX_CAP"
call_fullkey "$(S 1000000 smoke-3)"
echo "--- owner settle directly (expect ERR_MUST_USE_AGENT_KEY)"
near contract call-function as-transaction $C settle json-args "$(S 1000000 smoke-4)" prepaid-gas '30 Tgas' attached-deposit '0 NEAR' sign-as $OWNER $NET sign-with-legacy-keychain send 2>&1 | summ
call_owner set_kill_switch '{"on":true}'
call_agent "$(S 10000000 smoke-5)" "ERR_KILL_SWITCH_ON"
call_agent_m set_kill_switch '{"on":false}'
call_owner set_kill_switch '{"on":false}'
call_agent "$(S 100000000 smoke-6)" "OK, remaining 100000000"
call_agent "$(S 100000000 smoke-7)" "OK, remaining 0"
call_agent "$(S 1000000 smoke-8)" "ERR_OVER_DAILY_CAP"
view get_policy '{"agent":"bot1"}'; view is_killed '{}'
