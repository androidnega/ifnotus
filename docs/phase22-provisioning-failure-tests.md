# PHASE 22 — Provisioning failure tests

Goal: failed setup must end as **PROVISIONING_FAILED** (or order
`provisioning_status=failed`), **never** false **ACTIVE**. Retries must be
idempotent (no `ifn_1024_2`, no duplicate domains/envs).

Code anchors:

- `ProvisioningEngine.run_job` / `_fail_job` / `classify_provision_failure`
- `docker_downgrade_allowed`
- `OrderService.retry_provision` (reuses in-flight jobs)
- `UnixIdentityService.username_for` (stable `ifn_<id>`)
- Unit tests: `backend/tests/unit/test_provisioning_failures_phase22.py`

---

## Expected outcomes

| Forced failure | Expected |
|----------------|----------|
| Disk / capacity full (`pick_node`) | job failed, env `provisioning_failed` or never created ACTIVE |
| Docker required but start fails | hard fail — **no** silent filesystem ACTIVE |
| nginx / web configure fails | hard fail — `provisioning_failed` |
| Unix identity / transfer fails | hard fail |
| SSL fails on student host | soft — may still reach ACTIVE with warning |
| DNS deferred / custom DNS not live | soft — may ACTIVE; attach later |
| DB/mail installer fails (stack) | stack job fail — not hosting ACTIVE false-positive |
| Invalid / duplicate hostname | hard fail or reuse existing domain row |
| Worker restart mid-job | retry resumes/reuses env; no second unix user |
| Server reboot | pending jobs re-queued; identity/docroot reused |

---

## How to force failures (staging / controlled)

```text
1) Capacity: temporarily set infra_* totals tiny or fill disk past host_disk_crit_pct
2) Docker: stop docker / remove nginx:alpine and use a docker-required pack
3) Nginx: break a test hostname path or deny write to sites-available briefly
4) Unix: make useradd fail (e.g. readonly /etc/passwd in a containerized test host)
5) SSL: block outbound 80/443 ACME for a custom domain test
6) Duplicate: retry_provision twice quickly — second should reuse inflight job / env
```

---

## Idempotency checks after retry

```sql
-- One env per subscription+domain
SELECT subscription_id, domain, count(*)
FROM customer_environments
WHERE status NOT IN ('terminated','terminating')
GROUP BY 1,2 HAVING count(*) > 1;

-- Unix username never suffixes _2
SELECT unix_username FROM customer_environments
WHERE unix_username ~ '_[0-9]+$' AND unix_username LIKE 'ifn_%';

-- Domain names unique
SELECT name, count(*) FROM domains GROUP BY 1 HAVING count(*) > 1;
```

```bash
# Unit suite
cd backend && .venv/bin/python -m pytest tests/unit/test_provisioning_failures_phase22.py -q
```

---

## Pass criteria

```text
[ ] Hard failures set env.status=provisioning_failed (when env exists)
[ ] order.provisioning_status=failed
[ ] job.status=failed with failure.category in job.result
[ ] No ACTIVE after nginx/docker-required/unix/capacity failure
[ ] retry_provision does not create duplicate ifn_* users
[ ] retry_provision reuses pending/running job when present
[ ] Active env reuse short-circuits to success without second domain row
```
