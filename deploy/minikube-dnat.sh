#!/usr/bin/env bash
#
# Wire (or tear down) an iptables DNAT rule that forwards external traffic
# arriving on this host's :80 to the minikube ingress on :80.
#
#   sudo ./deploy/minikube-dnat.sh         # apply the rules
#   sudo ./deploy/minikube-dnat.sh down    # remove the rules
#
# Both the host IP and the minikube IP are derived at runtime, so nothing is
# hard-coded:
#   * HOST_IP - the source address the kernel uses for off-box traffic
#   * MK_IP   - `minikube ip`
#   * MK_DEV  - the bridge/interface that actually reaches MK_IP
#
# The MASQUERADE rule ensures minikube's replies route back out through the
# host, and the FORWARD ACCEPT covers Docker's default-DROP FORWARD policy.
set -eo pipefail

PORT="${PORT:-80}"

# iptables needs root. But `minikube ip` reads the invoking user's ~/.minikube,
# so running the whole script under sudo makes it look in /root/.minikube (no
# cluster there) and fail with exit 85. Require root, but bounce minikube back
# to the original user via $SUDO_USER.
if [ "$(id -u)" -ne 0 ]; then
  echo "ERROR: must run as root (use: sudo $0 ${1:-up})" >&2; exit 1
fi

run_as_user() {
  if [ -n "${SUDO_USER:-}" ]; then sudo -u "$SUDO_USER" "$@"; else "$@"; fi
}

HOST_IP="$(ip -4 route get 1.1.1.1 | grep -oP 'src \K\S+')"
MK_IP="${MK_IP:-$(run_as_user minikube ip)}"
MK_DEV="$(ip -4 route get "$MK_IP" | grep -oP 'dev \K\S+')"

[ -n "$HOST_IP" ] || { echo "ERROR: could not derive HOST_IP" >&2; exit 1; }
[ -n "$MK_IP" ]   || { echo "ERROR: could not derive MK_IP"   >&2; exit 1; }
[ -n "$MK_DEV" ]  || { echo "ERROR: could not derive MK_DEV"  >&2; exit 1; }

echo "HOST_IP=$HOST_IP  MK_IP=$MK_IP  MK_DEV=$MK_DEV  PORT=$PORT"

# Rule specs (table + chain + match), kept here so apply/teardown stay in sync.
prerouting=(-t nat PREROUTING -d "$HOST_IP" -p tcp --dport "$PORT" -j DNAT --to-destination "$MK_IP:$PORT")
postrouting=(-t nat POSTROUTING -d "$MK_IP" -p tcp --dport "$PORT" -j MASQUERADE)
forward=(FORWARD -d "$MK_IP" -o "$MK_DEV" -p tcp --dport "$PORT" -j ACCEPT)

add() {  # $1 = -A|-I, rest = rule spec (may start with "-t nat <CHAIN> ...")
  local verb="$1"; shift
  # strip any existing copy first (ignore failure), then add
  if [ "${1:-}" = "-t" ]; then
    iptables -t "$2" -D "${@:3}" >/dev/null 2>&1 || true
    iptables -t "$2" "$verb" "${@:3}"
  else
    iptables -D "$@" >/dev/null 2>&1 || true
    iptables "$verb" "$@"
  fi
}

del() {
  if [ "${1:-}" = "-t" ]; then
    iptables -t "$2" -D "${@:3}" >/dev/null 2>&1 || true
  else
    iptables -D "$@" >/dev/null 2>&1 || true
  fi
}

case "${1:-up}" in
  up)
    add -A "${prerouting[@]}"
    add -A "${postrouting[@]}"
    add -I "${forward[@]}"
    echo "Applied. External traffic to ${HOST_IP}:${PORT} -> ${MK_IP}:${PORT}"
    ;;
  down)
    del "${prerouting[@]}"
    del "${postrouting[@]}"
    del "${forward[@]}"
    echo "Removed DNAT rules for ${HOST_IP}:${PORT} -> ${MK_IP}:${PORT}"
    ;;
  *)
    echo "usage: $0 [up|down]" >&2; exit 2 ;;
esac

echo "--- nat table (relevant) ---"
iptables -t nat -S | grep -E "DNAT|MASQUERADE" || true
