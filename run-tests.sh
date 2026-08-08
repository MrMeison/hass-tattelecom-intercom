#!/bin/sh
# Run the test suite in a resource-capped container.
#
# Never run pytest for this integration without caps: the SIP/RTP loops can spin
# without yielding, and an unbounded run has taken the whole machine down (OOM,
# lost SSH). Caps here + `timeout` in pytest.ini keep a hung test local damage.
#
#   ./run-tests.sh                     # whole suite
#   ./run-tests.sh tests/test_rtp.py   # a single file, extra pytest args pass through
set -eu

IMAGE="${IMAGE:-tatt-intercom-test}"
RUN_TIMEOUT="${RUN_TIMEOUT:-900}"

docker build -q -f Dockerfile.test -t "$IMAGE" . >/dev/null

exec timeout "$RUN_TIMEOUT" docker run --rm \
    --memory=2g --memory-swap=2g --cpus=2 --pids-limit=256 \
    "$IMAGE" python -m pytest "${@:-tests/}" -q --timeout=60 --timeout-method=signal
