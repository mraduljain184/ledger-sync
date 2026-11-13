import http from 'k6/http';
import { check, sleep } from 'k6';
import exec from 'k6/execution';

const VUS = Number(__ENV.VUS || 200);
const THINK = Number(__ENV.THINK || 2);          // seconds a phone waits between syncs
const BATCH = Number(__ENV.BATCH || 50);         // events per request
const MERCHANTS = Number(__ENV.MERCHANTS || 50);
const BASE = __ENV.BASE || 'http://localhost:8000';

export const options = {
    scenarios: {
        phones: {
            executor: 'ramping-vus',
            startVUs: 1,
            stages: [
                { duration: '15s', target: 10 },     // warm-up
                { duration: '20s', target: VUS },    // ramp
                { duration: '60s', target: VUS },    // steady state
                { duration: '5s', target: 0 },
            ],
        },
    },
    thresholds: {
        'http_req_duration{name:push,phase:steady}': ['p(95)<300'],
        'http_req_failed{name:push}': ['rate<0.01'],
        checks: ['rate>0.99'],
    },
};

function phase() {
    const t = Date.now() - exec.scenario.startTime;
    if (t < 35000) return 'ramp';
    if (t < 95000) return 'steady';
    return 'down';
}

export default function () {
    const merchant = `lt-${__VU % MERCHANTS}`;
    const device = `vu${__VU}`;
    const batchId = `${device}-${__ITER}-${Date.now()}`;

    const events = [];
    for (let i = 0; i < BATCH; i++) {
        events.push({
            id: `${batchId}-${i}`, device,
            hlc_wall: Date.now(), hlc_counter: i, hlc_device: device,
            entry: `${batchId}-${i}`, op: 'create',
            party: `p${i % 6}`, amount: 100 * (1 + (i % 500)), note: '', base: null,
        });
    }

    const res = http.post(
        `${BASE}/v1/sync`,
        JSON.stringify({ merchant, device, batch_id: batchId, events }),
        {
            headers: { 'Content-Type': 'application/json', 'Idempotency-Key': batchId },
            tags: { name: 'push', phase: phase() },
        },
    );

    check(res, {
        'status 200': (r) => r.status === 200,
        'all accepted': (r) => r.status === 200 && r.json('accepted') === BATCH,
    });
    sleep(THINK);
}